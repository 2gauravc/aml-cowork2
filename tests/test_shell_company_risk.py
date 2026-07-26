from unittest.mock import patch

from src.agents.nodes import assess_shell_company_risk
from src.tools.shell_company_risk import load_shell_company_risk_definition


def _state() -> dict:
    return {"metadata": {"customer": {"name": "Example Ltd", "account_location": "SG"}}, "cdd": {"company_business_profile": {"customer_static": {"name": "Example Ltd", "registration_number": "123", "paid_up_capital": "SGD 1000", "incorporation_date": "2026-01-01", "activity_type": "Engineering", "registered_address": {"country_code": "SG"}}}, "ownership_and_control": {"status": "complete", "ubos": [{"name": "Alex", "nationality": "Singaporean"}], "members": {"controlling_members": [{"name": "Alex", "role": "Director", "jurisdiction": "SG"}]}}}, "evidence": [{"evidence_id": "profile", "tool": "get_customer_static_by_case_id", "source": "KYC API", "cdd_section": "customer_business_profile"}, {"evidence_id": "ownership", "tool": "get_company_members_by_case_id", "source": "KYC API", "cdd_section": "ownership_and_control"}], "assessments": [{"assessment_type": "digital_footprint", "digital_business_profile": {"business_activity": "Engineering", "geographic_presence": ["SG"]}}], "risk_flags": [{"finding_id": "csp_address:category", "category": "csp_address", "evaluation": "no", "severity": "none"}]}


def _clear() -> dict:
    return {key: {"outcome": "not_triggered", "summary": "No indicator identified.", "rationale": "Retained facts are clear."} for key in ("low_paid_up_capital", "recent_incorporation", "foreign_controllers_outside_ao", "no_business_presence_in_ao")}


def test_shell_factors_create_assessments_without_findings_and_do_not_duplicate_csp() -> None:
    with patch("src.tools.shell_company_risk._classify", return_value=_clear()): result = assess_shell_company_risk(_state())
    assert len(result["assessments"]) == 4
    assert result["findings"] == []
    assert load_shell_company_risk_definition()["assessment"]["schema"] == "shell_company_risk_assessment/v1"


def test_triggered_or_inconclusive_factor_creates_linked_finding() -> None:
    classified = _clear(); classified["low_paid_up_capital"] = {"outcome": "triggered", "summary": "Capital needs review.", "rationale": "Low capital may not fit the stated activity."}
    with patch("src.tools.shell_company_risk._classify", return_value=classified): result = assess_shell_company_risk(_state())
    finding = next(item for item in result["findings"] if item["check_id"] == "low_paid_up_capital")
    assert finding["assessment_id"]
