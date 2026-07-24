"""Tests for the canonical case-status projection."""

from src.utils.case_status import build_case_status, sync_case_status


def test_case_status_summarizes_all_risk_evaluations() -> None:
    status = build_case_status(
        "completed",
        [
            {"description": "Ownership: Evaluation: Yes."},
            {"description": "Ownership: Evaluation: No."},
            {"description": "CSP: Evaluation: Inconclusive."},
            {"evidence": {"assessment": {"is_csp": "yes"}}},
        ],
    )

    assert status["cdd_generation"] == "completed"
    assert status["risk_summary"]["totals"] == {"yes": 2, "inconclusive": 1, "no": 1}


def test_case_status_refreshes_after_chat_adds_a_risk_flag() -> None:
    session = {
        "case_status": {"cdd_generation": "completed", "risk_summary": {"by_category": {}, "totals": {"yes": 0, "inconclusive": 0, "no": 0}}},
        "risk_flags": [{"description": "CSP: Evaluation: Yes."}],
    }

    assert sync_case_status(session)["risk_summary"]["totals"]["yes"] == 1


def test_case_status_records_pipeline_failure() -> None:
    session = {"risk_flags": []}

    assert sync_case_status(session, generation="failed") == {
        "cdd_generation": "failed",
        "risk_summary": {"by_category": {}, "totals": {"yes": 0, "inconclusive": 0, "no": 0}},
    }
