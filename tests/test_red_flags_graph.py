"""Tests for the red-flags LangGraph subgraph and parent adapter."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from src.agents.nodes import evaluate_risk_flags
from src.agents.red_flags_graph import run_red_flags_graph


POLICY = {
    "policy_name": "test",
    "source_path": "test",
    "rules": [
        {"category": category, "evaluation": evaluation, "severity": severity}
        for category, severity in (("aml", "high"), ("ownership", "medium"), ("csp_address", "medium"))
        for evaluation in ("yes", "inconclusive")
    ] + [
        {"category": category, "evaluation": "no", "severity": "none"}
        for category in ("aml", "ownership", "csp_address")
    ],
}


class RedFlagsGraphTests(unittest.TestCase):
    @patch("src.agents.red_flags_graph.evaluate_csp_address")
    def test_subgraph_combines_existing_flags_and_csp_evidence(self, evaluate_csp) -> None:
        evaluate_csp.return_value = {
            "assessment": {
                "is_csp": "yes",
                "confidence": "high",
                "explanation": "The source advertises registered-office services at the address.",
            },
            "sources": [{"title": "Provider", "url": "https://example.test"}],
        }
        result = run_red_flags_graph(
            customer_static={
                "name": "Example Ltd",
                "registered_address": {"full_address": "1 Example Street"},
            },
            ownership_and_control={
                "status": "complete",
                "ubos": [],
                "org_chart": {"status": "complete"},
                "members": {"status": "complete", "controlling_members": [{"name": "Alex", "kyc": {"is_aml_positive": True}}]},
            },
            severity_policy=POLICY,
        )

        self.assertEqual({flag["category"] for flag in result["risk_flags"]}, {"ownership", "aml", "csp_address"})
        csp_flag = next(flag for flag in result["risk_flags"] if flag["category"] == "csp_address")
        self.assertEqual(csp_flag["evidence"]["assessment"]["is_csp"], "yes")
        self.assertEqual(result["evidence"][0]["tool"], "csp_address_assessment")

    @patch("src.agents.nodes.interpret_risk_severity_policy", return_value=POLICY)
    @patch("src.agents.red_flags_graph.evaluate_csp_address")
    def test_parent_adapter_returns_subgraph_outputs_for_main_state(self, evaluate_csp, _) -> None:
        evaluate_csp.return_value = {"assessment": {"is_csp": "no"}, "sources": []}
        result = evaluate_risk_flags(
            {
                "cdd": {
                    "company_business_profile": {
                        "customer_static": {"registered_address": {"full_address": "1 Example Street"}}
                    },
                    "ownership_and_control": {"status": "complete", "org_chart": {"status": "complete"}, "members": {"status": "complete", "controlling_members": []}, "ubos": [{"name": "Owner"}]},
                }
            }
        )

        csp_flag = next(flag for flag in result["risk_flags"] if flag["category"] == "csp_address")
        self.assertEqual(csp_flag["evaluation"], "no")
        self.assertEqual(result["evidence"][0]["data"]["assessment"]["is_csp"], "no")

    @patch("src.agents.red_flags_graph.evaluate_csp_address")
    def test_subgraph_records_cleared_results_for_every_negative_indicator(self, evaluate_csp) -> None:
        evaluate_csp.return_value = {
            "assessment": {"is_csp": "no", "explanation": "Operational business site."},
            "sources": [],
        }
        result = run_red_flags_graph(
            customer_static={"registered_address": {"full_address": "1 Example Street"}},
            ownership_and_control={"status": "complete", "org_chart": {"status": "complete"}, "ubos": [{"name": "Alex Owner"}], "members": {"status": "complete", "controlling_members": []}},
            severity_policy=POLICY,
        )

        self.assertEqual({flag["category"] for flag in result["risk_flags"]}, {"ownership", "aml", "csp_address"})
        self.assertTrue(all(flag["evaluation"] == "no" for flag in result["risk_flags"]))

    @patch("src.agents.red_flags_graph.evaluate_csp_address")
    def test_aml_keeps_individual_mixed_findings(self, evaluate_csp) -> None:
        evaluate_csp.return_value = {"assessment": {"is_csp": "no"}, "sources": []}
        result = run_red_flags_graph(
            customer_static={"registered_address": {"full_address": "1 Example Street"}},
            ownership_and_control={
                "status": "complete",
                "org_chart": {"status": "complete"},
                "ubos": [{"name": "Owner"}],
                "members": {"status": "complete", "controlling_members": [
                    {"name": "Positive", "case_common_id": "1", "kyc": {"is_aml_positive": True}},
                    {"name": "Unknown", "case_common_id": "2", "kyc": {}},
                    {"name": "Negative", "case_common_id": "3", "kyc": {"is_aml_positive": False}},
                ]},
            },
            severity_policy=POLICY,
        )
        aml = [flag for flag in result["risk_flags"] if flag["category"] == "aml"]
        self.assertEqual([flag["evaluation"] for flag in aml], ["yes", "inconclusive", "no"])
        self.assertEqual([flag["severity"] for flag in aml], ["high", "high", "none"])


if __name__ == "__main__":
    unittest.main()
