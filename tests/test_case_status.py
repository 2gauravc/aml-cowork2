"""Tests for the canonical case-status projection."""

from src.utils.case_status import build_case_status, sync_case_status


def test_case_status_records_generation_only() -> None:
    status = build_case_status("completed")

    assert status["cdd_generation"] == "completed"
    assert status == {"cdd_generation": "completed"}


def test_case_status_refreshes_after_chat_adds_a_finding() -> None:
    session = {
        "case_status": {"cdd_generation": "completed"},
        "findings": [{"category": "csp_address"}],
    }

    assert sync_case_status(session) == {"cdd_generation": "completed"}


def test_case_status_records_pipeline_failure() -> None:
    session = {"findings": []}

    assert sync_case_status(session, generation="failed") == {"cdd_generation": "failed"}
