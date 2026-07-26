"""Tests for the canonical case-status projection."""

from src.utils.case_status import build_case_status, sync_case_status


def test_case_status_records_generation_only() -> None:
    status = build_case_status("completed")

    assert status["cdd_generation"] == "completed"
    assert status == {"cdd_generation": "completed"}


def test_case_status_refreshes_after_chat_adds_a_risk_flag() -> None:
    session = {
        "case_status": {"cdd_generation": "completed"},
        "risk_flags": [{"description": "CSP: Evaluation: Yes."}],
    }

    assert sync_case_status(session) == {"cdd_generation": "completed"}


def test_case_status_records_pipeline_failure() -> None:
    session = {"risk_flags": []}

    assert sync_case_status(session, generation="failed") == {"cdd_generation": "failed"}
