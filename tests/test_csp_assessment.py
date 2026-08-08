from unittest.mock import patch

from src.agents.nodes import assess_csp_address


@patch("src.tools.csp_assessment.evaluate_csp_address")
def test_csp_node_replaces_only_prior_csp_records(evaluate_csp):
    evaluate_csp.return_value = {"assessment": {"is_csp": "yes", "confidence": "high", "explanation": "Provider evidence."}, "sources": [{"url": "https://example.test"}], "skill_path": "skills/csp-detector/SKILL.md"}
    state = {"cdd": {"company_business_profile": {"customer_static": {"name": "Example Ltd", "registered_address": {"full_address": "1 Example Street"}}}}, "assessments": [{"assessment_type": "csp_address", "assessment_id": "old"}, {"assessment_type": "other", "assessment_id": "keep"}], "findings": [{"category": "csp_address", "finding_id": "old"}, {"category": "other", "finding_id": "keep"}]}

    result = assess_csp_address(state)

    assert len(result["assessments"].value) == 2
    assert {item["assessment_type"] for item in result["assessments"].value} == {"csp_address", "other"}
    assert {item["category"] for item in result["findings"].value} == {"csp_address", "other"}
    assert result["findings"].value[-1]["schema_version"] == "finding/v1"


@patch("src.tools.csp_assessment.evaluate_csp_address")
def test_clear_csp_result_has_assessment_but_no_finding(evaluate_csp):
    evaluate_csp.return_value = {"assessment": {"is_csp": "no", "confidence": "high", "explanation": "No provider evidence."}, "sources": [], "skill_path": "skills/csp-detector/SKILL.md"}
    result = assess_csp_address({"cdd": {"company_business_profile": {"customer_static": {"registered_address": {"full_address": "1 Example Street"}}}}})
    assert result["assessments"].value[0]["outcome"] == "not_triggered"
    assert result["findings"].value == []


@patch("src.tools.csp_assessment.evaluate_csp_address")
def test_inconclusive_csp_result_has_a_finding(evaluate_csp):
    evaluate_csp.return_value = {"assessment": {"is_csp": "inconclusive", "confidence": "medium", "explanation": "Building-level evidence only."}, "sources": [], "skill_path": "skills/csp-detector/SKILL.md"}
    result = assess_csp_address({"cdd": {"company_business_profile": {"customer_static": {"registered_address": {"full_address": "1 Example Street"}}}}})
    assert result["assessments"].value[0]["outcome"] == "inconclusive"
    assert result["findings"].value[0]["category"] == "csp_address"
