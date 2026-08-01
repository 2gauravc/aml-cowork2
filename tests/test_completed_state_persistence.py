"""Verify the pipeline saves state only after a successful completion."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from src.backend.app import _complete_pipeline_for_session, _migrate_legacy_risk_rating


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
