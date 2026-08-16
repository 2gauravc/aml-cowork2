from src.agents.nodes import (
    customer_information_route,
    request_company_profile_documents,
)
from src.agents.state import new_cdd_state
from src.utils.ownership_validation import validate_ownership_resolution


def test_documents_first_creates_a_company_profile_requirement_without_kyc() -> None:
    state = new_cdd_state(
        customer_name="Example Ltd",
        jurisdiction="GB",
        account_location="GB",
        customer_information_source="documents",
    )
    assert customer_information_route(state) == "documents"
    update = request_company_profile_documents(state)
    document = update["documents"][0]
    assert document["purpose"] == "company_profile"
    assert document["document_type"] == "registry_document"
    assert document["gap"]["status"] == "outstanding"
    assert update["cdd"]["company_business_profile"]["customer_static"]["name"] == "Example Ltd"


def test_ownership_validation_reports_invalid_allocation_without_mutating_graph() -> None:
    root = {
        "name": "Customer",
        "shareholders": [
            {"name": "A", "nationality_id": "document", "ownership": {"shares": 60}},
            {"name": "B", "nationality_id": "document", "ownership": {"shares": 30}},
        ],
    }
    result = validate_ownership_resolution(root)
    assert result["outcome"] == "requires_review"
    assert result["issues"] == [{"code": "direct_ownership_not_100", "entity": "Customer", "total": 90.0}]
    assert root["shareholders"][0]["ownership"]["shares"] == 60
