"""Coverage for clearing stale CDD data when a new run is accepted."""

import asyncio

from fastapi import BackgroundTasks

from src.backend.app import _response, _run_pipeline_for_session


def _previous_case_session() -> dict:
    return {
        "session_id": "session-1",
        "customer_name": "Previous Co",
        "jurisdiction": "GB",
        "case_id": "previous-case",
        "messages": [{"role": "assistant", "content": "Previous case result"}],
        "graph_state": {"cdd": {"company_business_profile": {"customer_static": {"name": "Previous Co"}}}, "evidence": [{"source": "old"}], "documents": [{"name": "old.pdf"}], "document_requirements": [{"id": "old"}], "risk_flags": [{"finding_id": "old"}], "findings": [{"finding_id": "old-finding"}], "assessments": [{"assessment_id": "old-assessment"}], "case_assessment_summary": {"summary": "old"}, "case_status": {"cdd_generation": "completed"}},
        "graph_thread_id": "session-1",
        "document_results": [{"name": "old.pdf"}],
        "case_review_decision": {"decision": "approve"},
        "pdf_path": "/tmp/old.pdf",
        "pipeline_status": "complete",
        "pipeline_error": "old error",
        "demo_csp_result": {"result": "independent tool result"},
    }


def test_accepted_new_run_returns_no_previous_cdd_artifacts() -> None:
    session = _previous_case_session()

    response = asyncio.run(
        _run_pipeline_for_session(
            session,
            customer_name="New Co",
            jurisdiction="US",
            account_location="SG",
            case_id=None,
            background_tasks=BackgroundTasks(),
        )
    )

    assert response["status"] == "running"
    assert response["cdd"]["company_business_profile"]["status"] == "incomplete"
    assert response["documents"] == []
    assert response["risk_flags"] == []
    assert response["findings"] == []
    assert response["assessments"] == []
    assert response["case_assessment_summary"] is None
    assert response["case_review_decision"] is None
    assert response["pdf_url"] is None
    assert response["case_status"]["cdd_generation"] == "in_progress"
    assert response["case_id"] is None
    assert response["account_location"] == "SG"
    assert session["account_location"] == "SG"
    assert response["demo_csp_result"] == {"result": "independent tool result"}
    assert "Previous case result" not in response["messages"][-1]["content"]
    assert session["graph_thread_id"] != "session-1"


def test_rejected_new_run_preserves_previous_cdd_artifacts() -> None:
    session = _previous_case_session()

    response = asyncio.run(
        _run_pipeline_for_session(
            session,
            customer_name=None,
            jurisdiction="US",
            account_location="SG",
            background_tasks=BackgroundTasks(),
        )
    )

    assert response["status"] == "needs_input"
    assert response["cdd"] == _previous_case_session()["graph_state"]["cdd"]
    assert response["pdf_url"] == "/api/pdf/session-1"


def test_response_without_a_cdd_state_is_empty() -> None:
    session = {
        "session_id": "legacy-session",
        "messages": [],
    }

    response = _response(session, status="complete")

    assert response["case_assessment_summary"] is None
    assert response["cdd_state"] == {}
