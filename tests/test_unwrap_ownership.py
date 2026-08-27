from __future__ import annotations

from src.agents.nodes import unwrap_ownership
from src.tools.unwrap_ownership import load_ownership_definition
from src.utils.ownership_view import ownership_view
from src.utils.legacy_cdd_state import migrate_legacy_orchestration
from src.agents.chat_graph import _run_ownership_tool
from src.utils.cdd_policy import evaluate_case_actions, load_standard_company_policy


def _state(relations: list[dict], *, listed: bool = False) -> dict:
    profile = {"name": "Example Ltd", "is_listed": listed}
    if listed:
        profile["authorised_executive"] = {"name": "Executive Doe"}
    return {
        "cdd": {"company_business_profile": {"customer_static": profile}, "ownership_and_control": {}},
        "evidence": [{"evidence_id": "evidence:registry:1", "tool": "unwrap_ownership_document", "source": "Analyst registry document", "data": {"ownership_relationships": relations, "source_citations": [{"page": 2}]}}],
        "assessments": [], "findings": [], "orchestration": {},
    }


def test_contract_uses_canonical_artifact_sections() -> None:
    definition = load_ownership_definition()
    contract = definition["contract"]
    assert set(("evidence", "assessment", "finding")) <= set(contract)
    assert contract["assessment"]["schema"] == "ownership_unwrap_assessment/v1"
    assert load_standard_company_policy()["required_outcomes"][-1] == "corporate_shareholders_over_10_percent"


def test_document_evidence_produces_neutral_threshold_lists() -> None:
    state = _state([
        {"owner_name": "Jane Doe", "owner_type": "Individual", "direct_shareholding_percent": 60, "effective_shareholding_percent": 60},
        {"owner_name": "Exactly Twenty Five", "owner_type": "Individual", "direct_shareholding_percent": 25, "effective_shareholding_percent": 25},
        {"owner_name": "Minor Owner", "owner_type": "Individual", "direct_shareholding_percent": 15, "effective_shareholding_percent": 15},
    ])
    result = unwrap_ownership(state)
    assessment = result["assessments"][0]
    assert assessment["outcome"] == "complete"
    assert [item["name"] for item in assessment["ubo_list"]] == ["Jane Doe"]
    assert assessment["corporate_shareholders_over_10_percent"] == []
    assert result["findings"] == []
    assert assessment["source_evidence_ids"] == ["evidence:registry:1"]
    assert result["cdd"]["ownership_and_control"]["ubos"] == [assessment["ubo_list"][0]]


def test_incomplete_evidence_creates_lineage_safe_review_finding() -> None:
    result = unwrap_ownership(_state([]))
    assessment = result["assessments"][0]
    finding = result["findings"][0]
    assert assessment["outcome"] == "incomplete"
    assert finding["assessment_id"] == assessment["assessment_id"]
    assert set(finding["relevant_evidence_ids"]) <= set(assessment["source_evidence_ids"])


def test_listed_company_uses_authorised_executive_without_shareholding() -> None:
    result = unwrap_ownership(_state([], listed=True))
    assessment = result["assessments"][0]
    assert assessment["outcome"] == "listed_company_exception"
    assert assessment["ubo_list"] == [{"name": "Executive Doe", "case_common_id": None, "basis": "listed_company_authorised_executive", "effective_shareholding_percent": None}]


def test_stable_view_projects_assessment_without_exposing_contract_overlay() -> None:
    state = _state([{"owner_name": "Jane Doe", "owner_type": "Individual", "effective_shareholding_percent": 30}])
    result = unwrap_ownership(state)
    state["evidence"].extend(result["evidence"])
    state["assessments"].extend(result["assessments"])
    view = ownership_view(state)
    assert view["schema_version"] == "tool_view/v1"
    assert view["summary"]["metrics"][0] == {"label": "UBOs identified", "value": 1}


def test_legacy_orchestration_migration_is_idempotent() -> None:
    state: dict = {}
    assert migrate_legacy_orchestration(state) is True
    assert state["orchestration"]["policy_id"] == "standard_company_cdd"
    assert migrate_legacy_orchestration(state) is False


def test_chat_tool_uses_canonical_ownership_node() -> None:
    state = _state([
        {"owner_name": "Jane Doe", "owner_type": "Individual", "effective_shareholding_percent": 30}
    ])
    result = _run_ownership_tool(session={"graph_state": state})
    assert result["outcome"] == "complete"
    assert result["ubo_list"][0]["name"] == "Jane Doe"
    assert state["assessments"][0]["assessment_type"] == "ownership_unwrap"


def test_chat_result_keeps_retained_corporate_shareholder_when_conflicted() -> None:
    state = _state([])
    state["evidence"] = [{"evidence_id": "evidence:org:1", "tool": "get_company_org_chart_by_case_id", "source": "KYC API", "data": {"org_chart": {"name": "Example Ltd", "shareholders": [{"name": "Holdings Ltd", "type": "Company", "ownership": {"shares": 100}, "shareholders": [{"name": "Duplicate Owner", "type": "Individual", "ownership": {"shares": 60}}, {"name": "Duplicate Owner", "type": "Individual", "ownership": {"shares": 60}}]}]}}}]
    result = _run_ownership_tool(session={"graph_state": state})
    assert result["outcome"] == "conflicting_sources"
    assert result["corporate_shareholder_status"] == "retained_not_fully_unwrapped"
    assert result["retained_corporate_shareholders_over_10_percent"][0]["name"] == "Holdings Ltd"
    assert "Holdings Ltd (100.0%)" in result["conclusion"]


def test_policy_eligibility_requires_profile_before_ownership() -> None:
    state = _state([])
    assert evaluate_case_actions(state)["eligible_actions"] == ["establish_company_profile"]
    state["cdd"]["company_business_profile"]["customer_static"]["company_status"] = "Active"
    assert evaluate_case_actions(state)["eligible_actions"] == ["unwrap_ownership"]


def test_duplicates_and_unreconciled_layer_create_conflict_finding() -> None:
    state = _state([
        {"owner_name": "Somerset Creameries Group Limited", "owner_type": "Company", "direct_shareholding_percent": 93.6106, "effective_shareholding_percent": 93.6106},
        {"owner_name": "Somerset Creameries Group Limited", "owner_type": "Company", "direct_shareholding_percent": 13.2806, "effective_shareholding_percent": 13.2806},
        {"owner_name": "Joint holders", "owner_type": "Individual", "direct_shareholding_percent": 0, "effective_shareholding_percent": 0},
    ])
    result = unwrap_ownership(state)
    assessment = result["assessments"][0]
    assert assessment["outcome"] == "conflicting_sources"
    assert any(item["kind"] == "duplicate" for item in assessment["unresolved_branches"])
    assert any(item["kind"] == "reconciliation" for item in assessment["unresolved_branches"])
    assert result["findings"][0]["assessment_id"] == assessment["assessment_id"]


def test_immediate_corporate_owner_without_children_is_not_fully_unwrapped() -> None:
    state = _state([])
    state["evidence"] = [{"evidence_id": "evidence:org:1", "tool": "get_company_org_chart_by_case_id", "source": "KYC API", "data": {"org_chart": {"name": "Cropwell Bishop", "shareholders": [{"name": "Somerset Creameries Group Limited", "type": "Company", "ownership": {"shares": 100}}]}}}]
    result = unwrap_ownership(state)
    assessment = result["assessments"][0]
    assert assessment["outcome"] == "incomplete"
    assert assessment["ubo_list"] == []
    assert assessment["unresolved_branches"][0]["kind"] == "unresolved_corporate_branch"
    assert result["findings"][0]["category"] == "ownership_review"


def test_conflicting_unwrap_preserves_existing_cdd_ubo_claims() -> None:
    state = _state([])
    prior = [
        {"name": "Chin Eng Lee", "case_common_id": "ubo-1", "effective_shareholding_percent": 34},
        {"name": "Chong Chwee Seng", "case_common_id": "ubo-2", "effective_shareholding_percent": 33},
        {"name": "David Soon Kin Mun", "case_common_id": "ubo-3", "effective_shareholding_percent": 33},
    ]
    state["cdd"]["ownership_and_control"]["ubos"] = prior
    state["evidence"] = [{"evidence_id": "evidence:org:1", "tool": "get_company_org_chart_by_case_id", "source": "KYC API", "data": {"org_chart": {"name": "SC Engineering", "shareholders": [{"name": "Unknown Holdings", "type": "Company", "ownership": {"shares": 100}}]}}}]
    result = unwrap_ownership(state)
    assessment = result["assessments"][0]
    assert assessment["outcome"] == "incomplete"
    assert assessment["retained_ubo_claims"] == prior
    assert any(item.get("kind") == "retained_ubo_conflict" for item in assessment["unresolved_branches"])
    assert result["cdd"]["ownership_and_control"]["ubos"] == prior


def test_members_ubo_claims_are_reconciled_with_the_ownership_graph() -> None:
    state = _state([])
    state["evidence"] = [
        {"evidence_id": "evidence:members:1", "tool": "get_company_members_by_case_id", "source": "KYC API", "data": {"ultimate_beneficial_owners": [{"name": "Existing Owner", "case_common_id": "person-1", "ownership": {"percentage": 100}}]}},
        {"evidence_id": "evidence:org:1", "tool": "get_company_org_chart_by_case_id", "source": "KYC API", "data": {"org_chart": {"name": "Example Ltd", "shareholders": [{"name": "Different Owner", "type": "Individual", "case_common_id": "person-2", "ownership": {"shares": 100}}]}}},
    ]
    result = unwrap_ownership(state)
    assessment = result["assessments"][0]
    assert assessment["outcome"] == "incomplete"
    assert assessment["retained_ubo_claims"][0]["name"] == "Existing Owner"


def test_sc_engineering_direct_ubo_layer_is_resolved_from_kyc_org_chart() -> None:
    """Regression case from retained SC Engineering state (KYC case 1000002142)."""
    state = _state([])
    state["cdd"]["ownership_and_control"]["ubos"] = [
        {"name": "Chin Eng Lee", "case_common_id": 1000002144, "effective_shareholding_percent": 34},
        {"name": "Chong Chwee Seng", "case_common_id": 1000002145, "effective_shareholding_percent": 33},
        {"name": "David Soon Kin Mun", "case_common_id": 1000002146, "effective_shareholding_percent": 33},
    ]
    state["evidence"] = [
        {
            "evidence_id": "evidence:org:sc-engineering",
            "tool": "get_company_org_chart_by_case_id",
            "source": "KYC API",
            "data": {
                "org_chart": {
                    "name": "SC ENGINEERING PRIVATE LIMITED",
                    "shareholders": [
                        {"name": "Chin Eng Lee", "role": "Shareholder", "case_common_id": 1000002144, "ownership": {"effective_percentage": 34, "shares": 34}},
                        {"name": "Chong Chwee Seng", "role": "Shareholder", "case_common_id": 1000002145, "ownership": {"effective_percentage": 33, "shares": 33}},
                        {"name": "David Soon Kin Mun", "role": "Shareholder", "case_common_id": 1000002146, "ownership": {"effective_percentage": 33, "shares": 33}},
                    ],
                }
            },
        },
        {
            "evidence_id": "evidence:members:sc-engineering",
            "tool": "get_company_members_by_case_id",
            "source": "KYC API",
            "data": {
                "ultimate_beneficial_owners": [
                    {"name": "LEE CHIN ENG", "member_type": "Individual", "case_common_id": 1000002144},
                    {"name": "CHONG CHWEE SENG", "member_type": "Individual", "case_common_id": 1000002145},
                    {"name": "DAVID SOON KIN MUN", "member_type": "Individual", "case_common_id": 1000002146},
                ]
            },
        },
    ]

    result = unwrap_ownership(state)
    assessment = result["assessments"][0]

    assert assessment["outcome"] == "complete"
    assert [(ubo["case_common_id"], ubo["effective_shareholding_percent"]) for ubo in assessment["ubo_list"]] == [
        (1000002144, 34.0),
        (1000002145, 33.0),
        (1000002146, 33.0),
    ]
    assert assessment["corporate_shareholders_over_10_percent"] == []
    assert assessment["unresolved_branches"] == []
    assert result["findings"] == []
    normalized_org_chart = next(item for item in result["evidence"] if item["source"] == "KYC API")
    assert len(normalized_org_chart["data"]["ownership_relationships"]) == 3
