"""Shared LangGraph state for the CDD agent flow."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


SectionStatus = Literal["complete", "incomplete"]
FinalRecommendation = Literal["completed", "human_review", "rejected"]


class CustomerMetadata(TypedDict, total=False):
    name: str
    jurisdiction: str
    registration_number: str


class CaseMetadata(TypedDict, total=False):
    case_id: int | str
    status_id: int
    status: str
    ready: bool
    selected_registry_match: dict[str, Any]


class Metadata(TypedDict, total=False):
    customer: CustomerMetadata
    kyc_case: CaseMetadata


class CDDSection(TypedDict, total=False):
    status: SectionStatus
    missing_items: list[str]
    notes: list[str]


class CustomerStaticCDD(CDDSection, total=False):
    name: str
    company_type: str
    registration_number: str
    former_company_number: str
    company_status: str
    activity_type: str
    total_shares: str
    share_capital: str
    registration_date: str
    incorporation_date: str
    creation_date: str
    previous_names: str
    jurisdiction: str
    registered_address: dict[str, Any]
    registry_properties: dict[str, Any]


class MembersCDD(CDDSection, total=False):
    controlling_members: list[dict[str, Any]]
    shareholders_and_beneficial_owners: list[dict[str, Any]]
    ultimate_beneficial_owners: list[dict[str, Any]]
    counts: dict[str, int]


class OrgChartCDD(CDDSection, total=False):
    org_chart: dict[str, Any]
    counts: dict[str, int]


class OwnershipAndControlCDD(CDDSection, total=False):
    ubos: list[dict[str, Any]]
    shareholders_over_10_percent: list[dict[str, Any]]
    related_parties: list[dict[str, Any]]
    members: MembersCDD
    org_chart: OrgChartCDD


class CompanyBusinessProfileCDD(CDDSection, total=False):
    customer_static: CustomerStaticCDD


class CDD(TypedDict, total=False):
    status: SectionStatus
    started_at: str
    completed_at: str
    ownership_and_control: OwnershipAndControlCDD
    company_business_profile: CompanyBusinessProfileCDD


class CaseDocument(TypedDict, total=False):
    name: str
    category: str
    url: str
    path: str
    source: str
    collected_at: str


class EvidenceItem(TypedDict, total=False):
    source: str
    tool: str
    description: str
    data: dict[str, Any] | list[Any]
    collected_at: str


class RiskFlag(TypedDict, total=False):
    category: str
    severity: Literal["low", "medium", "high"]
    description: str
    source: str
    status: Literal["open", "cleared"]


class CDDState(TypedDict, total=False):
    metadata: Metadata
    cdd: CDD
    documents: list[CaseDocument]
    evidence: list[EvidenceItem]
    risk_flags: list[RiskFlag]
    final_recommendation: FinalRecommendation | None
    messages: Annotated[list[AnyMessage], add_messages]


def new_cdd_state(
    *,
    customer_name: str | None = None,
    jurisdiction: str | None = None,
    case_id: int | str | None = None,
) -> CDDState:
    """Create the minimal initial state for a CDD graph run."""
    customer: CustomerMetadata = {}
    if customer_name:
        customer["name"] = customer_name
    if jurisdiction:
        customer["jurisdiction"] = jurisdiction

    kyc_case: CaseMetadata = {}
    if case_id is not None:
        kyc_case["case_id"] = case_id

    return {
        "metadata": {
            "customer": customer,
            "kyc_case": kyc_case,
        },
        "cdd": {
            "status": "incomplete",
            "started_at": datetime.now(UTC).isoformat(),
            "ownership_and_control": {
                "status": "incomplete",
                "missing_items": [],
                "notes": [],
                "ubos": [],
                "shareholders_over_10_percent": [],
                "related_parties": [],
            },
            "company_business_profile": {
                "status": "incomplete",
                "missing_items": [],
                "notes": [],
            },
        },
        "documents": [],
        "evidence": [],
        "risk_flags": [],
        "final_recommendation": None,
        "messages": [],
    }
