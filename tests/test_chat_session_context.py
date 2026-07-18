"""Tests for deterministic, session-grounded chatbot context answers."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from src.agents.chat_graph import _execute_tool_call, _record_tool_result, _tool_specs


class ChatSessionContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.session = {
            "session_id": "session-1",
            "customer_name": "SC ENGINEERING PRIVATE LIMITED",
            "jurisdiction": "SG",
            "case_id": "sg-001",
            "pipeline_status": "awaiting_documents",
            "cdd": {
                "customer": {"name": "SC ENGINEERING PRIVATE LIMITED"},
                "documents": [
                    {
                        "artifact": {
                            "person_name": "Claire Wallace",
                            "document_type": "passport",
                            "storage": {"bucket": "documents", "key": "GB/claire-passport.pdf"},
                        },
                        "classification": {"document_type": "passport", "confidence": 0.99},
                        "extract": {"full_name": "Claire Wallace", "document_number": "P123456"},
                    }
                ],
            },
            "graph_state": {"metadata": {"case_id": "sg-001"}},
            "documents": [{"name": "registry.pdf"}],
            "document_requirements": [
                {
                    "id": "passport-1",
                    "entity_name": "Claire Wallace",
                    "document_type": "passport",
                    "status": "processed",
                    "source": "customer_upload",
                },
                {"id": "passport-2", "status": "not_found"},
            ],
            "evidence": [
                {
                    "source": "tool",
                    "tool": "get_customer_static_by_name",
                    "description": "Customer static profile",
                },
                {
                    "source": "graph",
                    "tool": "extract_idv_documents",
                    "description": "ID&V extraction",
                },
            ],
            "risk_flags": [{"severity": "low"}],
            "messages": [],
        }

    def test_session_inspection_tool_returns_live_session_state(self) -> None:
        result = _execute_tool_call("inspect_current_session", {}, self.session)

        self.assertEqual(result["customer_name"], "SC ENGINEERING PRIVATE LIMITED")
        self.assertEqual(result["pipeline_status"], "awaiting_documents")
        self.assertEqual(result["document_requirement_counts"], {"processed": 1, "not_found": 1})
        self.assertIn("metadata", result["graph_state_keys"])

    def test_evidence_tool_returns_retained_evidence_and_scope(self) -> None:
        result = _execute_tool_call("list_session_evidence", {}, self.session)

        self.assertEqual(result["count"], 2)
        self.assertEqual(result["records"][0]["tool"], "get_customer_static_by_name")
        self.assertEqual(result["records"][1]["tool"], "extract_idv_documents")
        self.assertIn("automatic audit log", result["retention_note"])

    def test_evidence_inspection_can_be_recorded_and_serialized(self) -> None:
        result = _execute_tool_call("list_session_evidence", {}, self.session)
        _record_tool_result(self.session, "list_session_evidence", result)

        json.dumps(result)
        self.assertEqual(
            self.session["tool_results"][-1],
            {"tool": "list_session_evidence", "data": {"status": "session inspected"}},
        )
        self.assertEqual(len(self.session["evidence"]), 2)

    @patch("src.agents.chat_graph.presign_document_url", return_value="https://signed.example/claire")
    def test_document_tool_returns_live_status_extract_and_requested_download_link(self, presign) -> None:
        result = _execute_tool_call(
            "get_document_information",
            {
                "person_name": "Claire Wallace",
                "include_extracted_information": True,
                "include_download_url": True,
            },
            self.session,
        )

        self.assertEqual(result["document_status_counts"], {"processed": 1, "not_found": 1})
        self.assertEqual(len(result["documents"]), 1)
        document = result["documents"][0]
        self.assertEqual(document["status"], "processed")
        self.assertEqual(document["extracted_information"]["document_number"], "P123456")
        self.assertEqual(document["download_url"], "https://signed.example/claire")
        presign.assert_called_once_with(
            bucket="documents", key="GB/claire-passport.pdf", expires_in_seconds=15 * 60
        )

    def test_document_tool_is_exposed_with_live_status_and_download_guidance(self) -> None:
        tool = next(tool for tool in _tool_specs() if tool.name == "get_document_information")

        self.assertIn("authoritative source", tool.description)
        self.assertIn("pre-signed URL", tool.description)
