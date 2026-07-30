from unittest.mock import patch

from src.agents.nodes import assess_other_risk_factors
from src.tools.other_risk_factors import load_other_risk_factors_definition


def _state() -> dict:
    return {
        "metadata": {"customer": {"name": "Example Ltd", "account_location": "GB"}},
        "cdd": {
            "company_business_profile": {"customer_static": {"name": "Example Ltd", "registration_number": "123", "jurisdiction": "GB", "activity_type": "Engineering services"}},
            "ownership_and_control": {"status": "complete", "missing_items": [], "members": {"controlling_members": [], "shareholders_and_beneficial_owners": [], "ultimate_beneficial_owners": []}, "org_chart": {"org_chart": {"shareholders": []}}},
        },
        "evidence": [
            {"evidence_id": "profile", "tool": "get_customer_static_by_case_id", "source": "KYC API", "cdd_section": "customer_business_profile"},
            {"evidence_id": "ownership", "tool": "get_company_org_chart_by_case_id", "source": "KYC API", "cdd_section": "ownership_and_control"},
        ],
        "assessments": [{"assessment_id": "assessment:digital", "assessment_type": "digital_footprint", "digital_business_profile": {"business_activity": "Engineering services", "geographic_presence": ["GB"]}}],
        "findings": [{"finding_id": "finding:digital", "category": "digital_footprint"}],
    }


def test_all_configured_factors_create_assessments_without_duplicate_upstream_findings() -> None:
    with patch("src.tools.other_risk_factors._classify_industry", return_value={"outcome": "not_triggered", "rationale": "Engineering is not high risk.", "risk_indicators": []}), patch("src.tools.other_risk_factors._classify_aml_jurisdiction", return_value={"outcome": "not_triggered", "rationale": "No link identified.", "matched_link_indexes": []}), patch("src.tools.other_risk_factors._classify_tax_jurisdiction", return_value={"outcome": "not_triggered", "rationale": "No link identified.", "matched_link_indexes": []}):
        result = assess_other_risk_factors(_state())
    assert len(result["assessments"]) == 5
    assert result["findings"] == []
    assert all(item["assessment_type"] == "other_risk_factors" for item in result["assessments"])
    assert all(item["upstream_finding_ids"] == ["finding:digital"] for item in result["assessments"])
    assert load_other_risk_factors_definition()["assessment"]["schema"] == "other_risk_factors_assessment/v1"


def test_jurisdiction_factors_are_assigned_to_customer_business_profile() -> None:
    factors = {item["id"]: item for item in load_other_risk_factors_definition()["factors"]}

    assert factors["high_aml_risk_jurisdiction_link"]["cdd_section"] == "customer_business_profile"
    assert factors["high_tax_risk_jurisdiction_link"]["cdd_section"] == "customer_business_profile"


def test_industry_and_jurisdiction_indicators_raise_linked_findings() -> None:
    state = _state()
    state["cdd"]["company_business_profile"]["customer_static"]["activity_type"] = "Cryptocurrency exchange"
    state["cdd"]["ownership_and_control"]["members"]["ultimate_beneficial_owners"] = [{"jurisdiction": "IR"}]
    with patch("src.tools.other_risk_factors._classify_industry", return_value={"outcome": "triggered", "rationale": "Virtual assets are high risk.", "risk_indicators": ["cryptocurrency exchange"]}), patch("src.tools.other_risk_factors._classify_aml_jurisdiction", return_value={"outcome": "triggered", "rationale": "An AML-risk link needs review.", "matched_link_indexes": [0]}), patch("src.tools.other_risk_factors._classify_tax_jurisdiction", return_value={"outcome": "not_triggered", "rationale": "No link identified.", "matched_link_indexes": []}):
        result = assess_other_risk_factors(state)
    triggered = {item["check_id"] for item in result["findings"]}
    assert {"high_risk_industry", "high_aml_risk_jurisdiction_link"} <= triggered
    assert all(item["assessment_id"] for item in result["findings"])


def test_incomplete_ownership_makes_nominee_assessment_inconclusive() -> None:
    state = _state()
    state["cdd"]["ownership_and_control"]["status"] = "incomplete"
    with patch("src.tools.other_risk_factors._classify_industry", return_value={"outcome": "not_triggered", "rationale": "Engineering is not high risk.", "risk_indicators": []}), patch("src.tools.other_risk_factors._classify_aml_jurisdiction", return_value={"outcome": "not_triggered", "rationale": "No link identified.", "matched_link_indexes": []}), patch("src.tools.other_risk_factors._classify_tax_jurisdiction", return_value={"outcome": "not_triggered", "rationale": "No link identified.", "matched_link_indexes": []}):
        result = assess_other_risk_factors(state)
    assessment = next(item for item in result["assessments"] if item["factor_id"] == "trust_or_nominee_arrangement")
    assert assessment["outcome"] == "inconclusive"
    assert any(item["assessment_id"] == assessment["assessment_id"] for item in result["findings"])


def test_trust_indicator_requires_configured_evidence_and_retains_its_source_field() -> None:
    state = _state()
    state["cdd"]["ownership_and_control"]["notes"] = ["Trust should not trigger from derived CDD text."]
    state["evidence"].append({"evidence_id": "members-trust", "tool": "get_company_members_by_case_id", "source": "KYC API", "cdd_section": "ownership_and_control", "data": {"controlling_members": [{"role": "Trustee"}]}})
    with patch("src.tools.other_risk_factors._classify_industry", return_value={"outcome": "not_triggered", "rationale": "Engineering is not high risk.", "risk_indicators": []}), patch("src.tools.other_risk_factors._classify_aml_jurisdiction", return_value={"outcome": "not_triggered", "rationale": "No link identified.", "matched_link_indexes": []}), patch("src.tools.other_risk_factors._classify_tax_jurisdiction", return_value={"outcome": "not_triggered", "rationale": "No link identified.", "matched_link_indexes": []}):
        result = assess_other_risk_factors(state)
    assessment = next(item for item in result["assessments"] if item["factor_id"] == "trust_or_nominee_arrangement")
    assert assessment["outcome"] == "triggered"
    indicator = assessment["detail"]["matched_indicators"][0]
    assert indicator == {"term": "trust", "evidence_id": "members-trust", "field_path": "data.controlling_members[0].role", "value": "Trustee"}


def test_trust_in_an_address_does_not_trigger_a_nominee_or_trust_finding() -> None:
    state = _state()
    state["evidence"].append({"evidence_id": "members-address", "tool": "get_company_members_by_case_id", "source": "KYC API", "cdd_section": "ownership_and_control", "data": {"controlling_members": [{"address": {"full_address": "WORLD TRUST TOWER"}}]}})
    with patch("src.tools.other_risk_factors._classify_industry", return_value={"outcome": "not_triggered", "rationale": "Engineering is not high risk.", "risk_indicators": []}), patch("src.tools.other_risk_factors._classify_aml_jurisdiction", return_value={"outcome": "not_triggered", "rationale": "No link identified.", "matched_link_indexes": []}), patch("src.tools.other_risk_factors._classify_tax_jurisdiction", return_value={"outcome": "not_triggered", "rationale": "No link identified.", "matched_link_indexes": []}):
        result = assess_other_risk_factors(state)
    assessment = next(item for item in result["assessments"] if item["factor_id"] == "trust_or_nominee_arrangement")
    assert assessment["outcome"] == "not_triggered"


def test_tax_jurisdiction_uses_only_retained_link_indexes() -> None:
    state = _state()
    state["cdd"]["company_business_profile"]["customer_static"]["jurisdiction"] = "KY"
    with patch("src.tools.other_risk_factors._classify_industry", return_value={"outcome": "not_triggered", "rationale": "Engineering is not high risk.", "risk_indicators": []}), patch("src.tools.other_risk_factors._classify_aml_jurisdiction", return_value={"outcome": "not_triggered", "rationale": "No link identified.", "matched_link_indexes": []}), patch("src.tools.other_risk_factors._classify_tax_jurisdiction", return_value={"outcome": "triggered", "rationale": "A retained link needs review.", "matched_link_indexes": [0]}):
        result = assess_other_risk_factors(state)
    assessment = next(item for item in result["assessments"] if item["factor_id"] == "high_tax_risk_jurisdiction_link")
    assert assessment["outcome"] == "triggered"
    assert assessment["detail"]["matched_jurisdiction_links"]
