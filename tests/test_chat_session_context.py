"""Tests for deterministic, session-grounded chatbot context answers."""

from __future__ import annotations

import json
import unittest
from unittest.mock import Mock, patch

from langchain_core.messages import AIMessage, HumanMessage

from src.agents.chat_graph import (
    _agent_node,
    _displayable_response_text,
    _execute_tool_call,
    _record_tool_result,
    _tool_specs,
)


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

    @patch("src.agents.chat_graph.ChatOpenAI")
    def test_tool_enabled_chat_uses_responses_api_for_gpt_5_6(self, chat_openai) -> None:
        bound_llm = Mock()
        bound_llm.invoke.return_value = AIMessage(content="I can help with that.")
        chat_openai.return_value.bind_tools.return_value = bound_llm

        result = _agent_node(
            {
                "messages": [HumanMessage(content="What can you do?")],
                "session": {"messages": []},
            }
        )

        chat_openai.assert_called_once_with(
            model="gpt-5.6",
            timeout=30,
            use_responses_api=True,
        )
        self.assertEqual(result["status"], "answered")

    def test_response_text_omits_responses_reasoning_blocks(self) -> None:
        content = _displayable_response_text(
            [
                {
                    "type": "reasoning",
                    "encrypted_content": "encrypted reasoning must not reach the UI",
                },
                {"type": "text", "text": "The customer has no UBO above 25%."},
            ]
        )

        self.assertEqual(content, "The customer has no UBO above 25%.")
        self.assertNotIn("encrypted", content)

    def test_response_text_preserves_legacy_string_content(self) -> None:
        self.assertEqual(
            _displayable_response_text("A normal chat completion."),
            "A normal chat completion.",
        )

    @patch("src.agents.chat_graph.interpret_risk_severity_policy", return_value={"policy_name": "test", "source_path": "test", "rules": [{"category": "csp_address", "evaluation": "yes", "severity": "medium"}]})
    @patch("src.agents.chat_graph.evaluate_csp_address")
    def test_csp_tool_uses_the_address_in_the_active_cdd_session(self, evaluate_csp, _) -> None:
        self.session["cdd"] = {
            "company_business_profile": {
                "customer_static": {
                    "name": "SC ENGINEERING PRIVATE LIMITED",
                    "registered_address": {"full_address": "1 Example Street"},
                }
            }
        }
        evaluate_csp.return_value = {
            "assessment": {"is_csp": "yes", "explanation": "Provider evidence."},
            "sources": [],
        }

        result = _execute_tool_call("evaluate_csp_address", {}, self.session)

        evaluate_csp.assert_called_once_with("1 Example Street", company_name="SC ENGINEERING PRIVATE LIMITED")
        self.assertEqual(result["assessment"]["is_csp"], "yes")
        self.assertEqual(self.session["risk_flags"][-1]["category"], "csp_address")
