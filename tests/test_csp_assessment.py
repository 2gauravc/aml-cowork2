from unittest.mock import patch

from src.agents.nodes import assess_csp_address


def _tool_result(outcome: str, *, refs: list[str] | None = None) -> dict:
    refs = refs or ["evidence:csp-address:tool:1"]
    return {
        "assessment": {
            "assessment_id": "assessment:csp-address:tool",
            "source_evidence_ids": refs,
            "is_csp": outcome,
            "confidence": "high",
            "explanation": "Provider evidence.",
            "limitations": [],
        },
        "finding_evidence_ids": refs,
        "finding_required": outcome != "no",
        "search_query": "Example address CSP",
        "sources": [
            {
                "evidence_id": refs[0],
                "title": "Provider",
                "url": "https://example.test",
                "content": "Registered office service.",
            }
        ],
        "definition": {
            "contract_path": "skills/csp-detector/contract.yaml",
            "contract_version": "test",
            "presentation_path": "skills/csp-detector/presentation.yaml",
            "presentation_version": "test",
        },
    }


@patch("src.tools.csp_assessment.evaluate_csp_address")
def test_csp_node_replaces_only_prior_csp_records(evaluate_csp):
    evaluate_csp.return_value = _tool_result("yes")
    state = {
        "cdd": {
            "company_business_profile": {
                "customer_static": {
                    "name": "Example Ltd",
                    "registered_address": {"full_address": "1 Example Street"},
                }
            }
        },
        "assessments": [
            {"assessment_type": "csp_address", "assessment_id": "old"},
            {"assessment_type": "other", "assessment_id": "keep"},
        ],
        "findings": [
            {"category": "csp_address", "finding_id": "old"},
            {"category": "other", "finding_id": "keep"},
        ],
    }

    result = assess_csp_address(state)

    assessment = next(
        item
        for item in result["assessments"].value
        if item["assessment_type"] == "csp_address"
    )
    finding = next(
        item for item in result["findings"].value if item["category"] == "csp_address"
    )
    assert assessment["schema_version"] == "csp_address_assessment/v2"
    assert assessment["source_evidence_ids"] == ["evidence:csp-address:tool:1"]
    assert finding["assessment_id"] == assessment["assessment_id"]
    assert finding["relevant_evidence_ids"] == assessment["source_evidence_ids"]
    assert finding["severity"]["level"] == "not_applicable"


@patch("src.tools.csp_assessment.evaluate_csp_address")
def test_clear_csp_result_has_assessment_but_no_finding(evaluate_csp):
    evaluate_csp.return_value = _tool_result("no")
    result = assess_csp_address(
        {
            "cdd": {
                "company_business_profile": {
                    "customer_static": {
                        "registered_address": {"full_address": "1 Example Street"}
                    }
                }
            }
        }
    )
    assert result["assessments"].value[0]["outcome"] == "not_triggered"
    assert result["findings"].value == []


@patch("src.tools.csp_assessment.evaluate_csp_address")
def test_inconclusive_csp_result_has_a_finding(evaluate_csp):
    evaluate_csp.return_value = _tool_result("inconclusive")
    result = assess_csp_address(
        {
            "cdd": {
                "company_business_profile": {
                    "customer_static": {
                        "registered_address": {"full_address": "1 Example Street"}
                    }
                }
            }
        }
    )
    assert result["assessments"].value[0]["outcome"] == "inconclusive"
    assert result["findings"].value[0]["category"] == "csp_address"
    assert result["findings"].value[0]["severity"]["level"] == "not_applicable"
