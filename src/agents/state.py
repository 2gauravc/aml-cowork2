"""Shared LangGraph state for the CDD agent flow."""

from __future__ import annotations

from datetime import UTC, datetime
from operator import add
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


SectionStatus = Literal["complete", "incomplete"]
GenerationStatus = Literal["not_started", "in_progress", "completed", "incomplete", "failed"]


class CustomerMetadata(TypedDict, total=False):
    name: str
    jurisdiction: str
    account_location: Literal["SG", "HK", "GB"]
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
    paid_up_capital: str
    capital_fields: list[dict[str, Any]]
    display_capital: dict[str, Any]
    registration_date: str
    incorporation_date: str
    creation_date: str
    previous_names: str
    jurisdiction: str
    registered_address: dict[str, Any]
    registry_properties: dict[str, Any]
    source: dict[str, Any]


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


class IndividualIdentityVerificationCDD(CDDSection, total=False):
    policy: dict[str, Any]
    required_individuals: list[dict[str, Any]]


class CDD(TypedDict, total=False):
    started_at: str
    completed_at: str
    ownership_and_control: OwnershipAndControlCDD
    company_business_profile: CompanyBusinessProfileCDD
    individual_identity_verification: IndividualIdentityVerificationCDD


class CaseStatus(TypedDict):
    cdd_generation: GenerationStatus


class CaseDocument(TypedDict, total=False):
    document_id: str
    purpose: str
    subject: dict[str, Any]
    requirement: dict[str, Any]
    status: str
    gap: dict[str, Any]
    acquisition: dict[str, Any]
    storage: dict[str, Any]
    processing: dict[str, Any]
    name: str
    category: str
    url: str
    path: str
    source: str
    collected_at: str


def merge_documents(
    existing: list[CaseDocument] | None, updates: list[CaseDocument] | None
) -> list[CaseDocument]:
    """Merge document lifecycle updates by stable document ID.

    Documents are stateful requirements, not append-only artefacts: locating a file,
    extracting it, and validating it must update the same record.
    """
    merged: list[CaseDocument] = []
    positions: dict[str, int] = {}
    for document in [*(existing or []), *(updates or [])]:
        document_id = str(document.get("document_id") or "")
        if document_id and document_id in positions:
            index = positions[document_id]
            merged[index] = {**merged[index], **document}
        else:
            if document_id:
                positions[document_id] = len(merged)
            merged.append(document)
    return merged


class EvidenceItem(TypedDict, total=False):
    evidence_id: str
    source: str
    tool: str
    description: str
    relevance_tags: list[str]
    data: dict[str, Any] | list[Any]
    collected_at: str
    source_url: str
    publisher: str
    published_at: str
    cdd_section: Literal["customer_business_profile", "ownership_and_control", "identity_verification", "screening"]
    evidence_area: str
    related_sections: list[str]


_EVIDENCE_CLASSIFICATIONS = {
    "create_company_case": ("customer_business_profile", "case and registry match"),
    "get_customer_static_by_case_id": ("customer_business_profile", "legal existence and registration"),
    "generate_registry_document": ("customer_business_profile", "registry document"),
    "extract_registry_document": ("customer_business_profile", "registry document"),
    "get_company_org_chart_by_case_id": ("ownership_and_control", "ownership chart and UBOs"),
    "get_company_members_by_case_id": ("ownership_and_control", "members and controllers"),
    "establish_idv_requirements": ("identity_verification", "ID&V requirements"),
    "generate_idv_documents": ("identity_verification", "identity documents"),
    "extract_idv_documents": ("identity_verification", "identity-document validation"),
    "digital_footprint_assessment": ("screening", "Digital Footprint"),
    "adverse_news_screening": ("screening", "Adverse News"),
    "csp_address_assessment": ("screening", "CSP address screening"),
}


def classify_evidence_item(item: EvidenceItem) -> EvidenceItem:
    """Add CDD organisation metadata without changing the canonical evidence payload."""
    if item.get("cdd_section"):
        return item
    section, area = _EVIDENCE_CLASSIFICATIONS.get(
        str(item.get("tool") or ""),
        ("screening", "Other screening or assessment"),
    )
    return {**item, "cdd_section": section, "evidence_area": area, "related_sections": item.get("related_sections") or []}


class Finding(TypedDict, total=False):
    finding_id: str
    schema_version: Literal["finding/v1"]
    category: str
    title: str
    summary: str
    subject: dict[str, Any]
    confidence: dict[str, Any]
    severity: dict[str, Any]
    potential_impact_risk: str
    recommended_action_rfi: dict[str, Any]
    source: dict[str, Any]
    relevant_evidence_ids: list[str]


class CDDState(TypedDict, total=False):
    metadata: Metadata
    cdd: CDD
    documents: Annotated[list[CaseDocument], merge_documents]
    evidence: Annotated[list[EvidenceItem], add]
    findings: Annotated[list[Finding], add]
    assessments: Annotated[list[dict[str, Any]], add]
    case_status: CaseStatus
    case_assessment_summary: dict[str, Any] | None
    messages: Annotated[list[AnyMessage], add_messages]


def new_cdd_state(
    *,
    customer_name: str | None = None,
    jurisdiction: str | None = None,
    account_location: Literal["SG", "HK", "GB"] | None = None,
    case_id: int | str | None = None,
) -> CDDState:
    """Create the minimal initial state for a CDD graph run."""
    customer: CustomerMetadata = {}
    if customer_name:
        customer["name"] = customer_name
    if jurisdiction:
        customer["jurisdiction"] = jurisdiction
    if account_location:
        customer["account_location"] = account_location

    kyc_case: CaseMetadata = {}
    if case_id is not None:
        kyc_case["case_id"] = case_id

    return {
        "metadata": {
            "customer": customer,
            "kyc_case": kyc_case,
        },
        "cdd": {
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
            "individual_identity_verification": {
                "status": "incomplete",
                "missing_items": [],
                "notes": [],
                "required_individuals": [],
            },
        },
        "documents": [],
        "evidence": [],
        "findings": [],
        "assessments": [],
        "case_status": {"cdd_generation": "in_progress"},
        "case_assessment_summary": None,
        "messages": [],
    }
