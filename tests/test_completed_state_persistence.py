"""Verify the pipeline saves state only after a successful completion."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from jsonschema import Draft202012Validator

from src.backend.app import CDDStateLookupRequest, SESSIONS, _complete_pipeline_for_session, _migrate_legacy_risk_rating, _queue_resume_if_ready, _resume_if_ready, load_completed_cdd_state
from src.tools.adverse_news import load_finding_schema
from src.utils.legacy_cdd_state import migrate_legacy_adverse_news, migrate_legacy_risk_flags
from src.utils.adverse_news_view import AdverseNewsViewError, adverse_news_view
from src.tools.adverse_news import load_adverse_news_definition


def test_completed_pipeline_persists_the_full_graph_state() -> None:
    graph_state = {
        "metadata": {"kyc_case": {"case_id": 42}},
        "cdd": {"completed_at": "2026-07-27T00:00:00+00:00"},
        "documents": [],
        "messages": [],
        "case_status": {},
    }
    session = {
        "session_id": "session-1",
        "messages": [],
        "pipeline_status": "running",
        "pipeline_progress": {},
    }
    saved = {"saved_at": "2026-07-27T00:00:01+00:00", "identity": {"customer_name": "UBIZENSE LIMITED"}}

    with patch("src.backend.app.run_cdd_agent_state", return_value=graph_state), patch(
        "src.backend.app.save_completed_state", return_value=saved
    ) as persist:
        asyncio.run(
            _complete_pipeline_for_session(
                session,
                customer_name="UBIZENSE LIMITED",
                jurisdiction="HK",
                account_location="HK",
                graph_thread_id="thread-1",
            )
        )

    persist.assert_called_once_with(
        graph_state,
        customer_name="UBIZENSE LIMITED",
        jurisdiction="HK",
        case_id=None,
    )
    assert session["pipeline_status"] == "complete"
    assert session["saved_cdd_state"] == saved
    assert session["messages"][-1]["content"] == "Completed CDD state saved to S3."


def test_loading_legacy_state_replaces_its_model_rating_with_the_rule_based_rating() -> None:
    graph_state = {
        "findings": [],
        "assessments": [
            {"assessment_id": "adverse", "assessment_type": "adverse_news", "outcome": "completed_no_material_findings", "created_at": "2026-01-01T00:00:00Z", "source_evidence_ids": []},
            {"assessment_id": "shell", "assessment_type": "shell_company_risk", "outcome": "not_triggered", "created_at": "2026-01-01T00:00:00Z", "source_evidence_ids": []},
            {"assessment_id": "industry", "assessment_type": "other_risk_factors", "factor_id": "high_risk_industry", "outcome": "not_triggered", "created_at": "2026-01-01T00:00:00Z", "source_evidence_ids": []},
            {"assessment_id": "aml", "assessment_type": "other_risk_factors", "factor_id": "high_aml_risk_jurisdiction_link", "outcome": "not_triggered", "created_at": "2026-01-01T00:00:00Z", "source_evidence_ids": []},
            {"assessment_id": "tax", "assessment_type": "other_risk_factors", "factor_id": "high_tax_risk_jurisdiction_link", "outcome": "not_triggered", "created_at": "2026-01-01T00:00:00Z", "source_evidence_ids": []},
            {"assessment_id": "legacy", "assessment_type": "risk_rating", "rating": "standalone_high", "summary": "Legacy model result"},
        ],
    }

    assert _migrate_legacy_risk_rating(graph_state) is True
    ratings = [item for item in graph_state["assessments"] if item["assessment_type"] == "risk_rating"]
    assert len(ratings) == 1
    assert ratings[0]["rating"] == "low"
    assert ratings[0]["total_score"] == 0
    assert ratings[0]["provenance"] == {"method": "deterministic_rule_based"}


def _legacy_csp_state(evaluation: str | None) -> dict:
    return {
        "cdd": {"company_business_profile": {"customer_static": {"name": "Example Ltd", "registered_address": {"full_address": "1 Example Street"}}}},
        "evidence": [], "assessments": [], "findings": [],
        "risk_flags": [{"finding_id": "csp_address:legacy", "category": "csp_address", "evaluation": evaluation, "severity": "medium", "description": "Legacy CSP result.", "evidence": {"assessment": {"is_csp": evaluation, "confidence": "medium", "explanation": "Legacy explanation."}, "sources": [{"url": "https://example.test/csp"}]}}],
    }


def test_legacy_csp_outcomes_become_canonical_records() -> None:
    for evaluation, outcome, findings in (("no", "not_triggered", 0), ("yes", "triggered", 1), ("inconclusive", "inconclusive", 1)):
        state = _legacy_csp_state(evaluation)
        assert migrate_legacy_risk_flags(state) is True
        assert "risk_flags" not in state
        assert state["assessments"][-1]["schema_version"] == "csp_address_assessment/v1"
        assert state["assessments"][-1]["outcome"] == outcome
        assert len(state["findings"]) == findings
        if findings:
            assert state["findings"][-1]["severity"]["level"] == "not_applicable"


def test_legacy_ownership_only_flags_are_dropped_and_migration_is_idempotent() -> None:
    state = {"risk_flags": [{"category": "ownership", "evaluation": "yes"}], "evidence": [], "assessments": [], "findings": []}
    assert migrate_legacy_risk_flags(state) is True
    assert "risk_flags" not in state
    assert state["assessments"] == []
    assert migrate_legacy_risk_flags(state) is False


def test_malformed_legacy_csp_is_visible_as_an_inconclusive_migration_limitation() -> None:
    state = _legacy_csp_state(None)
    state["risk_flags"][0].pop("evidence")
    migrate_legacy_risk_flags(state)
    assert state["assessments"][-1]["outcome"] == "inconclusive"
    assert state["assessments"][-1]["provenance"]["limitations"]
    assert state["findings"][-1]["confidence"]["limitations"]
    assert state["findings"][-1]["source"]["producer_type"] == "tool"
    assert state["findings"][-1]["migration"]["method"] == "legacy_risk_flags_migration"
    assert not list(Draft202012Validator(load_finding_schema()).iter_errors(state["findings"][-1]))


def test_loading_a_migrated_legacy_snapshot_persists_it() -> None:
    state = _legacy_csp_state("yes")
    state["assessments"].append({"assessment_id": "rating", "assessment_type": "risk_rating", "provenance": {"method": "deterministic_rule_based"}})
    snapshot = {"saved_at": "2026-01-01T00:00:00Z", "identity": {"customer_name": "Example Ltd", "jurisdiction": "GB", "case_id": "1"}, "graph_state": state}
    SESSIONS.clear()
    to_thread = AsyncMock(side_effect=lambda func, *args, **kwargs: func(*args, **kwargs))
    with patch("src.backend.app.get_completed_state", return_value=snapshot), patch("src.backend.app.save_completed_state", return_value={"saved_at": "2026-01-02T00:00:00Z", "identity": snapshot["identity"]}) as persist, patch("src.backend.app.asyncio.to_thread", to_thread):
        response = asyncio.run(load_completed_cdd_state(CDDStateLookupRequest(session_id="migration-test", customer_name="Example Ltd", jurisdiction="GB")))
    assert "risk_flags" not in response["cdd_state"]
    assert response["cdd_state"]["findings"][-1]["category"] == "csp_address"
    persist.assert_called_once()


def test_legacy_adverse_news_artifacts_are_normalized_idempotently() -> None:
    state = {
        "evidence": [{"evidence_id": "evidence:adverse:1", "tool": "adverse_news_screening", "source": "Brave Search", "description": "Notice", "source_url": "https://example.test/notice", "collected_at": "2026-01-01T00:00:00Z", "data": {"id": "source:1", "entity_key": "ubo:0", "query": "Alex Chen", "content": "Notice"}}],
        "assessments": [],
        "findings": [{"finding_id": "finding:adverse:1", "category": "adverse_news", "subject": {"entity_type": "ultimate_beneficial_owner", "name": "Alex Chen"}, "relevant_evidence_ids": ["evidence:adverse:1"], "adverse_news": {"screening_coverage": {"queries": ["Alex Chen"]}}, "source": {"created_at": "2026-01-01T00:00:00Z"}}],
    }
    assert migrate_legacy_adverse_news(state) is True
    finding = state["findings"][0]
    assessment = state["assessments"][0]
    assert finding["assessment_id"] == assessment["assessment_id"]
    assert assessment["source_evidence_ids"] == ["evidence:adverse:1"]
    assert state["evidence"][0]["data"]["web_search_evidence"]["schema_version"] == "web_search_evidence/v1"
    assert finding["confidence"]["level"] == "low"
    assert finding["severity"]["level"] == "not_applicable"
    assert not list(Draft202012Validator(load_finding_schema()).iter_errors(finding))
    assert migrate_legacy_adverse_news(state) is False


def test_adverse_news_view_hides_storage_shape_from_the_ui() -> None:
    state = {"assessments": [{"assessment_id": "assessment:adverse", "assessment_type": "adverse_news", "outcome": "completed_no_material_findings"}], "findings": [], "evidence": []}
    view = adverse_news_view(state)
    assert view["schema_version"] == "tool_view/v1"
    assert view["status"] == "completed_no_material_findings"


def test_presentation_label_edit_changes_the_compiled_view() -> None:
    state = {"assessments": [{"assessment_id": "assessment:adverse", "assessment_type": "adverse_news", "outcome": "completed_no_material_findings", "summary": "Clear", "limitations": [], "screened_entities": [], "source_evidence_ids": []}], "findings": [], "evidence": []}
    definition = load_adverse_news_definition()
    definition["presentation"]["summary"]["metrics"][0]["label"] = "Subjects screened"
    assert adverse_news_view(state, definition)["summary"]["metrics"][0]["label"] == "Subjects screened"


def test_invalid_presentation_binding_is_rejected() -> None:
    definition = load_adverse_news_definition()
    definition["presentation"]["summary"]["text"] = "assessment.not_a_field"
    with pytest.raises(AdverseNewsViewError, match="does not resolve"):
        adverse_news_view({"assessments": [], "findings": [], "evidence": []}, definition)


def test_loading_legacy_adverse_news_persists_the_normalized_snapshot() -> None:
    state = {"evidence": [{"evidence_id": "evidence:adverse:1", "tool": "adverse_news_screening", "data": {"id": "source:1"}}], "assessments": [], "findings": [{"finding_id": "finding:adverse:1", "category": "adverse_news", "subject": {"entity_type": "company", "name": "Example Ltd"}, "relevant_evidence_ids": ["evidence:adverse:1"]}]}
    snapshot = {"saved_at": "2026-01-01T00:00:00Z", "identity": {"customer_name": "Example Ltd", "jurisdiction": "GB", "case_id": "1"}, "graph_state": state}
    SESSIONS.clear()
    to_thread = AsyncMock(side_effect=lambda func, *args, **kwargs: func(*args, **kwargs))
    with patch("src.backend.app.get_completed_state", return_value=snapshot), patch("src.backend.app.save_completed_state", return_value={"saved_at": "2026-01-02T00:00:00Z", "identity": snapshot["identity"]}) as persist, patch("src.backend.app.asyncio.to_thread", to_thread):
        response = asyncio.run(load_completed_cdd_state(CDDStateLookupRequest(session_id="adverse-migration-test", customer_name="Example Ltd", jurisdiction="GB")))
    assert response["cdd_state"]["tool_views"]["adverse_news"]["schema_version"] == "tool_view/v1"
    assert response["cdd_state"]["findings"][0]["assessment_id"]
    assert response["cdd_state"]["tool_views"]["adverse_news"]["detailed"]["findings"][0]["tags"][2]["value"] == "Not retained"
    persist.assert_called_once()


def test_resumed_pipeline_syncs_completion_and_persists_the_completed_state() -> None:
    resumed_state = {
        "metadata": {"kyc_case": {"case_id": 42}},
        "cdd": {"completed_at": "2026-07-27T00:00:00+00:00"},
        "documents": [{"document_id": "document:idv:p1:1", "gap": {"status": "resolved"}, "status": "processed"}],
        "messages": [],
        "case_status": {"cdd_generation": "in_progress"},
    }
    session = {
        "session_id": "session-1",
        "messages": [],
        "customer_name": "UBIZENSE LIMITED",
        "jurisdiction": "HK",
        "case_id": 42,
        "graph_thread_id": "thread-1",
        "graph_state": {"documents": resumed_state["documents"], "case_status": {"cdd_generation": "in_progress"}},
    }
    saved = {"saved_at": "2026-07-27T00:00:01+00:00", "identity": {"customer_name": "UBIZENSE LIMITED"}}

    with patch("src.backend.app.resume_cdd_agent_state", return_value=resumed_state) as resume, patch(
        "src.backend.app.save_completed_state", return_value=saved
    ) as persist:
        asyncio.run(_resume_if_ready(session))

    resume.assert_called_once()
    persist.assert_called_once_with(
        resumed_state,
        customer_name="UBIZENSE LIMITED",
        jurisdiction="HK",
        case_id=42,
    )
    assert session["pipeline_status"] == "complete"
    assert session["graph_state"]["case_status"] == {"cdd_generation": "completed"}
    assert session["pipeline_progress"]["status"] == "completed"
    assert session["saved_cdd_state"] == saved


def test_document_action_queues_a_resume_without_waiting_for_the_full_pipeline() -> None:
    session = {
        "session_id": "session-1",
        "messages": [],
        "graph_thread_id": "thread-1",
        "graph_state": {"documents": [{"gap": {"status": "resolved"}}], "case_status": {}},
    }

    with patch("src.backend.app.asyncio.create_task") as create_task:
        asyncio.run(_queue_resume_if_ready(session))

    assert session["pipeline_status"] == "running"
    assert create_task.call_count == 1
    create_task.call_args.args[0].close()
