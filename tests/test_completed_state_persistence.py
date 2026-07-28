"""Verify the pipeline saves state only after a successful completion."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from src.backend.app import _complete_pipeline_for_session


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
