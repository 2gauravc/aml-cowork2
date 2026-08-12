"""Tests for GPT-5.6 case-checker synthesis and deterministic guardrails."""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.agents.nodes import generate_case_checker
from src.tools.case_checker import (
    CASE_PACKET_SAFETY_INSTRUCTIONS,
    generate_case_checker_summary,
    load_case_checker_skill,
    unavailable_case_checker,
)
from src.utils.skill_definitions import load_skill_definition


class CaseCheckerTests(unittest.TestCase):
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
            "src.tools.case_checker.OpenAI", return_value=client
        ):
            result = generate_case_checker_summary(
                cdd={},
                case_status={"cdd_generation": "completed"},
                findings=[{"finding_id": "finding:csp-address:1", "category": "csp_address", "summary": "Address evidence is incomplete.", "severity": {"level": "medium"}}],
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
        self.assertTrue(result["skill_path"].endswith("skills/case-checker/SKILL.md"))
        request = client.responses.create.call_args.kwargs
        self.assertEqual(request["model"], "gpt-5.6")
        self.assertTrue(request["text"]["format"]["strict"])
        self.assertNotIn("temperature", request)
        prompt = request["input"][0]["content"][0]["text"]
        self.assertIn("# CDD Case Checker", prompt)
        self.assertIn(CASE_PACKET_SAFETY_INSTRUCTIONS, prompt)
        self.assertIn("Case packet:\n", prompt)

    def test_loads_reusable_case_checker_skill(self) -> None:
        skill = load_case_checker_skill()

        self.assertEqual(load_skill_definition(Path(__file__).parents[1] / "skills" / "case-checker" / "SKILL.md")[0]["name"], "case-checker")
        self.assertIn("# CDD Case Checker", skill)
        self.assertIn("Requests for Information", skill)
        self.assertNotIn("untrusted", skill)
        self.assertNotIn("source_refs", skill)
        self.assertNotIn("Required output", skill)

    @patch("src.agents.nodes.generate_case_checker_summary")
    def test_node_passes_case_status_and_findings(self, generate_summary) -> None:
        generate_summary.return_value = {
            "status": "available",
            "executive_summary": "No material issues.",
            "key_evidence": [],
            "limitations": [],
            "recommended_actions": [],
            "requests_for_information": [],
            "finding_assessments": [{"finding_id": "ownership:category", "confidence": "medium", "confidence_rationale": "Ownership evidence is complete.", "potential_impact_risk": "Ownership may be opaque.", "recommended_action_or_rfi": {"type": "none", "text": ""}}],
        }
        result = generate_case_checker(
            {
                "cdd": {},
                "case_status": {"cdd_generation": "completed"},
                "findings": [{"finding_id": "finding:ownership:1", "category": "cdd_completeness"}],
                "evidence": [],
            }
        )

        self.assertEqual(result["case_checker_summary"]["status"], "available")
        self.assertNotIn("case_assessment_summary", result)
        self.assertNotIn("findings", result)
        self.assertEqual(generate_summary.call_args.kwargs["case_status"], {"cdd_generation": "completed"})

    def test_unavailable_review_records_limitation(self) -> None:
        result = unavailable_case_checker("OpenAI unavailable")

        self.assertEqual(result["status"], "unavailable")
        self.assertIn("OpenAI unavailable", result["limitations"])


if __name__ == "__main__":
    unittest.main()
