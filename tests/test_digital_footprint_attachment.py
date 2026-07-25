"""Ensure standalone footprint output reaches the shared Case Review evidence path only on attachment."""

import asyncio
from unittest.mock import patch

from src.backend.app import DigitalFootprintAttachRequest, SESSIONS, attach_digital_footprint


def test_attachment_explicitly_appends_normalized_evidence() -> None:
    SESSIONS.clear()
    SESSIONS["session-1"] = {
        "session_id": "session-1",
        "graph_state": {"cdd": {"status": "complete"}, "evidence": [], "assessments": [], "findings": []},
        "messages": [],
    }
    result = {"evidence": [{"tool": "digital_footprint_assessment"}], "assessments": [{"assessment_type": "digital_footprint", "schema_version": "digital_footprint_assessment/v1"}], "findings": [{"category": "digital_footprint"}]}
    response = asyncio.run(attach_digital_footprint(DigitalFootprintAttachRequest(session_id="session-1", result=result)))

    assert SESSIONS["session-1"]["graph_state"]["evidence"] == result["evidence"]
    assert SESSIONS["session-1"]["graph_state"]["assessments"] == result["assessments"]
    assert SESSIONS["session-1"]["graph_state"]["findings"] == result["findings"]
    assert response["status"] == "digital_footprint_attached"
