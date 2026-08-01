"""Verify the pipeline saves state only after a successful completion."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from src.backend.app import _complete_pipeline_for_session, _migrate_legacy_risk_rating, _queue_resume_if_ready, _resume_if_ready


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
