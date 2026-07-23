"""Tests for GPT-5.6 case-review synthesis and deterministic guardrails."""

from __future__ import annotations

import json
import os
import unittest
from unittest.mock import Mock, patch

from src.agents.nodes import generate_case_review
from src.tools.case_review import generate_case_review_summary, load_case_review_skill, unavailable_case_review


class CaseReviewTests(unittest.TestCase):
    def test_summary_uses_strict_schema_and_returns_finding_assessments(self) -> None:
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
                "finding_assessments": [
                    {
                        "finding_id": "csp_address:category",
                        "confidence": "low",
                        "confidence_rationale": "Only building-level evidence is available.",
                        "potential_impact_risk": "The address may conceal a service-provider relationship.",
                        "recommended_action_or_rfi": {"type": "rfi", "text": "Provide operating-address evidence."},
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
                case_status={"cdd_generation": "completed", "risk_summary": {"by_category": {}, "totals": {"yes": 0, "inconclusive": 1, "no": 0}}},
                risk_flags=[{"finding_id": "csp_address:category", "category": "csp_address", "evaluation": "inconclusive", "severity": "medium", "description": "Address evidence is incomplete."}],
                evidence=[
                    {
                        "tool": "csp_address_assessment",
                        "description": "Address assessed",
                        "data": {"sources": [{"url": "https://example.test/csp"}]},
                    }
                ],
            )

        self.assertEqual(result["status"], "available")
        self.assertEqual(result["finding_assessments"][0]["confidence"], "low")
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
    def test_node_passes_case_status_and_merges_finding_assessments(self, generate_summary) -> None:
        generate_summary.return_value = {
            "status": "available",
            "executive_summary": "No material issues.",
            "key_evidence": [],
            "limitations": [],
            "recommended_actions": [],
            "requests_for_information": [],
            "finding_assessments": [{"finding_id": "ownership:category", "confidence": "medium", "confidence_rationale": "Ownership evidence is complete.", "potential_impact_risk": "Ownership may be opaque.", "recommended_action_or_rfi": {"type": "none", "text": ""}}],
        }
        result = generate_case_review(
            {
                "cdd": {},
                "case_status": {"cdd_generation": "completed", "risk_summary": {"by_category": {}, "totals": {"yes": 1, "inconclusive": 0, "no": 0}}},
                "risk_flags": [{"finding_id": "ownership:category", "evaluation": "yes", "category": "ownership"}],
                "evidence": [],
            }
        )

        self.assertEqual(result["risk_flags"][0]["case_review"]["confidence"], "medium")
        self.assertEqual(generate_summary.call_args.kwargs["case_status"]["risk_summary"]["totals"]["yes"], 1)

    def test_unavailable_review_records_limitation(self) -> None:
        result = unavailable_case_review("OpenAI unavailable")

        self.assertEqual(result["status"], "unavailable")
        self.assertIn("OpenAI unavailable", result["limitations"])


if __name__ == "__main__":
    unittest.main()
