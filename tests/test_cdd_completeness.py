from src.agents.nodes import assess_cdd_completeness


def _state() -> dict:
    return {
        "cdd": {
            "company_business_profile": {"customer_static": {
                "name": "Example Ltd", "jurisdiction": "GB", "company_status": "Active",
                "registration_number": "123", "company_type": "Limited", "activity_type": "Trading",
                "incorporation_date": "2020-01-01", "registered_address": {"full_address": "1 Example Street"},
            }},
            "ownership_and_control": {"status": "complete", "missing_items": [], "ubos": [{"name": "Alex Example"}]},
            "individual_identity_verification": {"required_individuals": [{"name": "Alex Example"}]},
        },
        "assessments": [{"assessment_type": "digital_footprint", "digital_business_profile": {"business_activity": "Engineering services"}}],
        "documents": [{"document_id": "document:idv:1", "purpose": "identity_verification", "subject": {"name": "Alex Example"}, "status": "processed", "gap": {"status": "resolved"}, "processing": {"validation": {"accepted_type": True, "name_match": True}}}],
    }


def test_complete_checks_create_assessments_without_findings() -> None:
    result = assess_cdd_completeness(_state())
    assert len(result["assessments"]) == 4
    assert {item["outcome"] for item in result["assessments"]} == {"not_triggered"}
    assert result["findings"] == []


def test_missing_document_creates_linked_finding() -> None:
    state = _state()
    state["documents"][0]["status"] = "required"
    state["documents"][0]["gap"] = {"status": "outstanding"}
    result = assess_cdd_completeness(state)
    finding = next(item for item in result["findings"] if item["check_id"] == "idv_documents_obtained")
    assessment = next(item for item in result["assessments"] if item["check_id"] == "idv_documents_obtained")
    assert finding["assessment_id"] == assessment["assessment_id"]
