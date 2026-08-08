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
            "graph_state": {"metadata": {"case_id": "sg-001"}, "cdd": {"customer": {"name": "SC ENGINEERING PRIVATE LIMITED"}, "company_business_profile": {"customer_static": {}}}, "documents": [
                {"document_id": "document:idv:claire:1", "purpose": "identity_verification", "subject": {"name": "Claire Wallace"}, "document_type": "passport", "status": "processed", "gap": {"status": "resolved"}, "storage": {"bucket": "documents", "key": "GB/claire-passport.pdf"}, "processing": {"classification": {"document_type": "passport", "confidence": 0.99}, "extract": {"full_name": "Claire Wallace", "document_number": "P123456"}}},
                {"document_id": "document:idv:missing:1", "purpose": "identity_verification", "document_type": "passport", "status": "required", "gap": {"status": "outstanding"}}
            ], "evidence": [{"source": "tool", "tool": "get_customer_static_by_name", "description": "Customer static profile"}, {"source": "graph", "tool": "extract_idv_documents", "description": "ID&V extraction"}], "findings": [_adverse_news_finding()]},
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
            "findings": [_adverse_news_finding()],
            "messages": [],
        }

    def test_session_inspection_tool_returns_live_session_state(self) -> None:
        result = _execute_tool_call("inspect_current_session", {}, self.session)

        self.assertEqual(result["customer_name"], "SC ENGINEERING PRIVATE LIMITED")
        self.assertEqual(result["pipeline_status"], "awaiting_documents")
        self.assertEqual(result["document_status_counts"], {"processed": 1, "required": 1})
        self.assertIn("metadata", result["graph_state_keys"])
        self.assertEqual(result["findings_count"], 1)
        self.assertEqual(result["findings"][0]["category"], "adverse_news")

    def test_context_answers_adverse_news_rfi_from_findings(self) -> None:
        result = _execute_tool_call(
            "answer_from_context",
            {"question": "What RFI is recommended for Alex Chen's adverse news finding?"},
            self.session,
        )

        self.assertIn("Provide the regulatory notice", result["answer"])

    def test_session_inspection_handles_no_findings(self) -> None:
        self.session["graph_state"].pop("findings")

        result = _execute_tool_call("inspect_current_session", {}, self.session)

        self.assertEqual(result["findings_count"], 0)
        self.assertEqual(result["findings"], [])

    def test_findings_are_described_to_the_chatbot(self) -> None:
        inspect_tool = next(tool for tool in _tool_specs() if tool.name == "inspect_current_session")

        self.assertIn("adverse_news", inspect_tool.description)
        self.assertIn("neutral findings", inspect_tool.description)

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

        self.assertEqual(result["document_status_counts"], {"processed": 1, "required": 1})
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

    @patch("src.agents.chat_graph.assess_csp_address")
    def test_csp_tool_uses_the_address_in_the_active_cdd_session(self, assess_csp) -> None:
        self.session["graph_state"]["cdd"] = {
            "company_business_profile": {
                "customer_static": {
                    "name": "SC ENGINEERING PRIVATE LIMITED",
                    "registered_address": {"full_address": "1 Example Street"},
                }
            }
        }
        assess_csp.return_value = {"evidence": [], "assessments": [{"assessment_type": "csp_address", "result": {"assessment": {"is_csp": "yes"}}}], "findings": [{"category": "csp_address"}]}

        result = _execute_tool_call("evaluate_csp_address", {}, self.session)

        assess_csp.assert_called_once_with(self.session["graph_state"], address="1 Example Street", company_name="SC ENGINEERING PRIVATE LIMITED")
        self.assertEqual(result["assessment"]["is_csp"], "yes")
        self.assertEqual(self.session["graph_state"]["findings"][-1]["category"], "csp_address")


def _adverse_news_finding() -> dict:
    return {
        "category": "adverse_news",
        "summary": "Public reporting may concern the UBO; identity remains ambiguous.",
        "subject": {"name": "Alex Chen"},
        "confidence": {"level": "medium"},
        "severity": {"level": "high"},
        "recommended_action_rfi": {
            "rfi": [
                {
                    "request": "Provide the regulatory notice and explain the reported matter.",
                    "reason": "Confirm identity and status.",
                    "priority": "high",
                }
            ]
        },
    }
