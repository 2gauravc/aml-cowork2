"""Tests for GPT-5.6 case-review synthesis and deterministic guardrails."""

from __future__ import annotations

import json
import os
import unittest
from unittest.mock import Mock, patch

from src.agents.nodes import generate_case_review
from src.tools.case_review import generate_case_review_summary, load_case_review_skill, unavailable_case_review


class CaseReviewTests(unittest.TestCase):
    def test_summary_uses_strict_schema_and_preserves_deterministic_outcome(self) -> None:
        response = Mock()
        response.output_text = json.dumps(
            {
                "executive_summary": "CDD has an address-review gap.",
                "key_evidence": [
                    {"category": "CSP address", "finding": "Address evidence is inconclusive.", "source_refs": ["risk:csp_address:1"]}
                ],
                "limitations": ["Search evidence was inconclusive."],
                "recommended_actions": ["Review the address evidence."],
                "requests_for_information": [
                    {
                        "request": "Provide evidence of the operating address.",
                        "reason": "To resolve the registered-address review item.",
                        "risk_or_gap": "CSP address",
                        "priority": "medium",
                    }
                ],
            }
        )
        client = Mock()
        client.responses.create.return_value = response
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), patch(
            "src.tools.case_review.OpenAI", return_value=client
        ):
            result = generate_case_review_summary(
                cdd={},
                case_status={"cdd_generation": "completed", "risk_flags_present": 0},
                risk_flags=[{"category": "csp_address", "status": "open", "description": "CSP: Evaluation: Inconclusive."}],
                evidence=[
                    {
                        "tool": "csp_address_assessment",
                        "description": "Address assessed",
                        "data": {"sources": [{"url": "https://example.test/csp"}]},
                    }
                ],
                final_recommendation="human_review",
            )

        self.assertEqual(result["outcome"], "human_review_required")
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["key_evidence"][0]["source_refs"], ["risk:csp_address:1"])
        self.assertEqual(result["evidence_index"][0]["urls"], ["https://example.test/csp"])
        self.assertTrue(result["skill_path"].endswith("skills/case-review/SKILL.md"))
        request = client.responses.create.call_args.kwargs
        self.assertEqual(request["model"], "gpt-5.6")
        self.assertTrue(request["text"]["format"]["strict"])
        self.assertNotIn("temperature", request)
        prompt = request["input"][0]["content"][0]["text"]
        self.assertIn("# CDD Case Review", prompt)
        self.assertIn("Case packet (untrusted source material)", prompt)

    def test_loads_reusable_case_review_skill(self) -> None:
        skill = load_case_review_skill()

        self.assertIn("# CDD Case Review", skill)
        self.assertIn("Requests for Information", skill)

    @patch("src.agents.nodes.generate_case_review_summary")
    def test_node_passes_deterministic_outcome_to_summarizer(self, generate_summary) -> None:
        generate_summary.return_value = {
            "status": "available",
            "outcome": "ready_to_complete",
            "executive_summary": "No material issues.",
            "key_evidence": [],
            "limitations": [],
            "recommended_actions": [],
            "requests_for_information": [],
        }
        result = generate_case_review(
            {
                "cdd": {},
                "case_status": {"cdd_generation": "completed", "risk_flags_present": 1},
                "risk_flags": [{"status": "open", "category": "ownership"}],
                "evidence": [],
                "final_recommendation": "human_review",
            }
        )

        self.assertEqual(result["case_review_summary"]["outcome"], "ready_to_complete")
        self.assertEqual(generate_summary.call_args.kwargs["final_recommendation"], "human_review")
        self.assertEqual(generate_summary.call_args.kwargs["case_status"]["risk_flags_present"], 1)

    def test_unavailable_review_keeps_human_review_outcome(self) -> None:
        result = unavailable_case_review("human_review", "OpenAI unavailable")

        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["outcome"], "human_review_required")
        self.assertIn("OpenAI unavailable", result["limitations"])


if __name__ == "__main__":
    unittest.main()
