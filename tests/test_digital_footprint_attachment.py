"""Ensure standalone footprint output reaches the shared Case Review evidence path only on attachment."""

import asyncio
from unittest.mock import patch

from src.backend.app import DigitalFootprintAttachRequest, SESSIONS, attach_digital_footprint


def test_attachment_explicitly_appends_normalized_evidence() -> None:
    SESSIONS.clear()
    SESSIONS["session-1"] = {
        "session_id": "session-1",
        "cdd": {"status": "complete"},
        "evidence": [],
        "messages": [],
        "case_status": {},
    }
    normalized = {"tool": "digital_footprint", "relevance_tags": ["digital_footprint"], "data": {"sources": []}}
    with patch("src.backend.app.normalize_digital_footprint_evidence", return_value=normalized):
        response = asyncio.run(
            attach_digital_footprint(
                DigitalFootprintAttachRequest(session_id="session-1", result={"any": "result"})
            )
        )

    assert SESSIONS["session-1"]["evidence"] == [normalized]
    assert response["status"] == "digital_footprint_attached"
