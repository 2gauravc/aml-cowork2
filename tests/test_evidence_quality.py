from src.agents.nodes import assess_evidence_quality
from src.agents.state import classify_evidence_item
from src.tools.evidence_quality import load_evidence_quality_definition


def _state() -> dict:
    return {
        "metadata": {"customer": {"name": "Example Ltd"}, "kyc_case": {"case_id": 42}},
        "cdd": {
            "company_business_profile": {"customer_static": {"name": "Example Ltd", "registration_number": "123", "jurisdiction": "GB", "company_status": "Active"}},
            "ownership_and_control": {"status": "complete", "ubos": [{"name": "Alex Example"}]},
            "individual_identity_verification": {"required_individuals": [{"name": "Alex Example"}]},
        },
        "documents": [{"document_id": "document:idv:1", "purpose": "identity_verification", "status": "processed", "gap": {"status": "resolved"}, "processing": {"validation": {"accepted_type": True, "name_match": True}}}],
        "assessments": [{"assessment_type": "digital_footprint", "digital_business_profile": {"business_activity": "Engineering services", "geographic_presence": ["GB"]}}],
        "evidence": [
            {"evidence_id": "static", "source": "KYC API", "tool": "get_customer_static_by_case_id", "description": "Static", "data": {"name": "Example Ltd", "registration_number": "123", "jurisdiction": "GB"}},
            {"evidence_id": "org", "source": "KYC API", "tool": "get_company_org_chart_by_case_id", "description": "Org", "data": {"case_id": 42, "ubos": ["Alex Example"]}},
            {"evidence_id": "members", "source": "KYC API", "tool": "get_company_members_by_case_id", "description": "Members", "data": {"case_id": 42}},
            {"evidence_id": "idv-policy", "source": "Policy", "tool": "establish_idv_requirements", "description": "IDV policy", "data": {"name": "Alex Example"}},
            {"evidence_id": "idv", "source": "Extraction", "tool": "extract_idv_documents", "description": "IDV", "data": {"name": "Alex Example"}},
            {"evidence_id": "footprint", "source": "Tavily", "tool": "digital_footprint_assessment", "description": "Example Ltd Engineering services", "data": {"name": "Example Ltd", "business_activity": "Engineering services"}},
        ],
    }


def test_supported_claims_create_assessments_without_findings() -> None:
    result = assess_evidence_quality(_state())
    assert len(result["assessments"]) == 4
    assert {item["outcome"] for item in result["assessments"]} == {"not_triggered"}
    assert result["findings"] == []
    assert all(item["selected_evidence"] for item in result["assessments"])
    assert result["assessments"][0]["definition"]["dimensions"] == load_evidence_quality_definition()["dimensions"]


def test_evidence_is_classified_under_a_cdd_section() -> None:
    record = classify_evidence_item({"tool": "get_customer_static_by_case_id"})
    assert record["cdd_section"] == "customer_business_profile"
    assert record["evidence_area"] == "legal existence and registration"


def test_missing_or_mismatched_evidence_creates_linked_finding() -> None:
    state = _state()
    state["evidence"] = [item for item in state["evidence"] if item["evidence_id"] != "static"]
    result = assess_evidence_quality(state)
    assessment = next(item for item in result["assessments"] if item["claim_id"] == "company_legal_existence")
    finding = next(item for item in result["findings"] if item["assessment_id"] == assessment["assessment_id"])
    assert assessment["outcome"] == "unavailable"
    assert finding["category"] == "evidence_quality"
    assert finding["relevant_evidence_ids"]


def test_explicit_synthetic_provenance_evidence_is_not_clear() -> None:
    state = _state()
    static = next(item for item in state["evidence"] if item["evidence_id"] == "static")
    static["data"]["artifact"] = {"source": "Synthetic demo registry document"}
    result = assess_evidence_quality(state)
    assessment = next(item for item in result["assessments"] if item["claim_id"] == "company_legal_existence")
    assert assessment["dimensions"]["veracity_source_integrity"]["outcome"] == "inconclusive"
    assert any(item["assessment_id"] == assessment["assessment_id"] for item in result["findings"])


def test_incidental_generated_text_does_not_make_evidence_synthetic() -> None:
    state = _state()
    static = next(item for item in state["evidence"] if item["evidence_id"] == "static")
    static["description"] = "The page contains generated commentary."
    result = assess_evidence_quality(state)
    assessment = next(item for item in result["assessments"] if item["claim_id"] == "company_legal_existence")
    assert assessment["dimensions"]["veracity_source_integrity"]["outcome"] == "not_triggered"


def test_unknown_provenance_evidence_creates_a_source_integrity_finding() -> None:
    state = _state()
    static = next(item for item in state["evidence"] if item["evidence_id"] == "static")
    static["source"] = ""
    result = assess_evidence_quality(state)
    assessment = next(item for item in result["assessments"] if item["claim_id"] == "company_legal_existence")
    assert assessment["dimensions"]["veracity_source_integrity"]["outcome"] == "inconclusive"
