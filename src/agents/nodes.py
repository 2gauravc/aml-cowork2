"""LangGraph node functions for the CDD agent."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from langchain_core.messages import AIMessage

from src.agents.businesslogic import build_ownership_tables
from src.agents.state import CDDState
from src.tools.cdd_enrichment import (
    apply_document_extract_to_cdd,
    missing_about_customer_fields,
)
from src.tools.customer_static import _fetch_customer_static
from src.tools.document_extraction import classify_document, extract_document
from src.tools.idv_policy import interpret_idv_policy
from src.tools.idv_requirements import establish_idv_requirements as apply_idv_requirements
from src.tools.members import _fetch_company_members
from src.tools.orgchart import _fetch_company_org_chart
from src.utils.create_case import BASE_URL, CLIENT_ID, CLIENT_SECRET, KycClient, create_company_case
from src.utils.document_pipeline import generate_registry_document
from src.utils.idv_document_pipeline import generate_idv_documents


def collect_required_inputs(state: CDDState) -> dict[str, Any]:
    """Ask for missing required customer inputs before calling KYC tools."""
    metadata = deepcopy(state.get("metadata", {}))
    customer = metadata.setdefault("customer", {})
    missing = []
    if not customer.get("name"):
        missing.append("customer name")
    if not customer.get("jurisdiction"):
        missing.append("jurisdiction")

    if not missing:
        return {"metadata": metadata}

    cdd = deepcopy(state.get("cdd", {}))
    for section_name in ("ownership_and_control", "company_business_profile"):
        section = cdd.setdefault(section_name, {})
        section["status"] = "incomplete"
        section["missing_items"] = missing

    message = AIMessage(
        content=(
            "Please provide the customer name and jurisdiction before I start "
            "the CDD onboarding checks."
        )
    )
    return {"metadata": metadata, "cdd": cdd, "messages": [message]}


def has_required_inputs(state: CDDState) -> str:
    customer = state.get("metadata", {}).get("customer", {})
    if customer.get("name") and customer.get("jurisdiction"):
        return "ready"
    return "missing_inputs"


def create_or_reuse_case(state: CDDState) -> dict[str, Any]:
    """Create one KYC case if the state does not already contain a case_id."""
    metadata = deepcopy(state.get("metadata", {}))
    customer = metadata.setdefault("customer", {})
    kyc_case = metadata.setdefault("kyc_case", {})

    if kyc_case.get("case_id"):
        return {"metadata": metadata}

    client = _client()
    case_result = create_company_case(
        customer["name"],
        customer["jurisdiction"],
        client=client,
    )
    kyc_case.update(
        {
            "case_id": case_result.get("case_id"),
            "status_id": case_result.get("status_id"),
            "ready": case_result.get("ready"),
            "selected_registry_match": case_result.get("selected_registry_match", {}),
        }
    )
    if case_result.get("selected_registry_match", {}).get("registrationNumber"):
        customer["registration_number"] = case_result["selected_registry_match"][
            "registrationNumber"
        ]
    return {
        "metadata": metadata,
        "evidence": [
            _evidence(
                tool="create_company_case",
                description="Created or reused KYC company case",
                data=case_result,
                relevance_tags=["case", "registry_match", "kyc_case"],
            )
        ],
    }


def fetch_customer_static(state: CDDState) -> dict[str, Any]:
    case_id = _case_id(state)
    result = _fetch_customer_static(case_id, client=_client())
    return {
        "evidence": [
            _evidence(
                tool="get_customer_static_by_case_id",
                description="Fetched static company profile",
                data=result,
                relevance_tags=[
                    "customer_static",
                    "company_profile",
                    "address",
                    "registration",
                    "status",
                    "activity",
                ],
            )
        ]
    }


def fetch_org_chart(state: CDDState) -> dict[str, Any]:
    case_id = _case_id(state)
    result = _fetch_company_org_chart(case_id, client=_client())
    return {
        "evidence": [
            _evidence(
                tool="get_company_org_chart_by_case_id",
                description="Fetched recursive ownership org chart",
                data=result,
                relevance_tags=[
                    "org_chart",
                    "ownership",
                    "shareholders",
                    "ubos",
                    "related_parties",
                    "officers",
                ],
            )
        ]
    }


def fetch_members(state: CDDState) -> dict[str, Any]:
    case_id = _case_id(state)
    result = _fetch_company_members(case_id, client=_client())
    return {
        "evidence": [
            _evidence(
                tool="get_company_members_by_case_id",
                description="Fetched company members",
                data=result,
                relevance_tags=[
                    "members",
                    "directors",
                    "controlling_members",
                    "shareholders",
                    "aml",
                    "addresses",
                    "nationality",
                ],
            )
        ]
    }


def build_company_business_profile(state: CDDState) -> dict[str, Any]:
    cdd = deepcopy(state.get("cdd", {}))
    profile = cdd.setdefault("company_business_profile", {})
    static_result = _latest_evidence_data(state, "get_customer_static_by_case_id")
    customer_static = static_result.get("customer_static", {}) if static_result else {}

    profile["customer_static"] = {
        "status": _section_status(customer_static, required=("name", "company_status")),
        "missing_items": _missing(customer_static, ("name", "company_status")),
        "notes": [],
        **customer_static,
    }
    profile["status"] = profile["customer_static"]["status"]
    profile["missing_items"] = profile["customer_static"]["missing_items"]
    profile["notes"] = []
    return {"cdd": cdd}


def generate_registry_document_node(state: CDDState) -> dict[str, Any]:
    """Generate a synthetic registry document from the current CDD object."""
    cdd = state.get("cdd", {})
    artifact = generate_registry_document(cdd)
    return {
        "messages": [AIMessage(content="Generating registry document.")],
        "evidence": [
            _evidence(
                tool="generate_registry_document",
                description="Generated synthetic registry business profile document",
                source="Synthetic demo document generator",
                data=artifact,
                relevance_tags=[
                    "document",
                    "registry_document",
                    "company_profile",
                    "synthetic_demo",
                ],
            )
        ]
    }


def extract_registry_document(state: CDDState) -> dict[str, Any]:
    """Classify and extract structured data from the generated registry document."""
    artifact = _latest_evidence_data(state, "generate_registry_document") or {}
    if not artifact:
        raise ValueError("Generated registry document artifact is required")

    classification = classify_document(artifact["pdf_path"])
    extract = extract_document(artifact, classification=classification)
    return {
        "messages": [AIMessage(content="Extracting registry document.")],
        "evidence": [
            _evidence(
                tool="extract_registry_document",
                description="Classified and extracted registry document data",
                source="OpenAI document extraction",
                data={
                    "classification": classification,
                    "extract": extract,
                    "artifact": artifact,
                },
                relevance_tags=[
                    "document",
                    "registry_document",
                    "document_extraction",
                    "company_profile",
                ],
            )
        ]
    }


def enrich_cdd_from_registry_document(state: CDDState) -> dict[str, Any]:
    """Populate missing CDD profile fields from the registry document extract."""
    cdd = deepcopy(state.get("cdd", {}))
    document_data = _latest_evidence_data(state, "extract_registry_document") or {}
    extract = document_data.get("extract") or {}
    artifact = document_data.get("artifact") or {}
    classification = document_data.get("classification") or {}
    missing_before = missing_about_customer_fields(cdd)
    applied_fields = apply_document_extract_to_cdd(cdd, extract)
    document_result = {
        "classification": classification,
        "missing_fields_before": missing_before,
        "applied_fields": applied_fields,
        "artifact": artifact,
    }
    cdd.setdefault("documents", []).append(document_result)
    return {"cdd": cdd}


def build_ownership_and_control(state: CDDState) -> dict[str, Any]:
    cdd = deepcopy(state.get("cdd", {}))
    ownership = cdd.setdefault("ownership_and_control", {})
    members_result = _latest_evidence_data(state, "get_company_members_by_case_id") or {}
    org_result = _latest_evidence_data(state, "get_company_org_chart_by_case_id") or {}

    ownership["members"] = {
        "status": "complete" if members_result and not members_result.get("error") else "incomplete",
        "missing_items": [] if members_result and not members_result.get("error") else ["members"],
        "notes": [],
        "controlling_members": members_result.get("controlling_members", []),
        "shareholders_and_beneficial_owners": members_result.get(
            "shareholders_and_beneficial_owners", []
        ),
        "ultimate_beneficial_owners": members_result.get("ultimate_beneficial_owners", []),
        "counts": members_result.get("counts", {}),
    }
    ownership["org_chart"] = {
        "status": "complete" if org_result and not org_result.get("error") else "incomplete",
        "missing_items": [] if org_result and not org_result.get("error") else ["org_chart"],
        "notes": [],
        "org_chart": org_result.get("org_chart", {}),
        "counts": org_result.get("counts", {}),
    }
    ownership.update(build_ownership_tables(org_result))

    missing_items = []
    if ownership["members"]["status"] == "incomplete":
        missing_items.append("members")
    if ownership["org_chart"]["status"] == "incomplete":
        missing_items.append("org_chart")

    ownership["status"] = "complete" if not missing_items else "incomplete"
    ownership["missing_items"] = missing_items
    ownership["notes"] = []
    return {"cdd": cdd}


def establish_idv_requirements(state: CDDState) -> dict[str, Any]:
    """Interpret the ID&V policy and apply it to required individuals."""
    cdd = deepcopy(state.get("cdd", {}))
    policy = interpret_idv_policy()
    idv = apply_idv_requirements(cdd, policy)
    cdd["individual_identity_verification"] = idv
    return {
        "cdd": cdd,
        "messages": [AIMessage(content="Establishing ID&V requirements.")],
        "evidence": [
            _evidence(
                tool="establish_idv_requirements",
                description="Interpreted ID&V policy and applied it to the case",
                source="OpenAI policy interpretation",
                data=idv,
                relevance_tags=["idv", "policy", "ubo", "directors"],
            )
        ],
    }


def generate_idv_documents_node(state: CDDState) -> dict[str, Any]:
    """Generate synthetic identity documents for ID&V-required people."""
    cdd = state.get("cdd", {})
    idv = cdd.get("individual_identity_verification", {})
    individuals = idv.get("required_individuals", [])
    artifacts = generate_idv_documents(individuals)
    return {
        "messages": [AIMessage(content="Generating ID&V documents.")],
        "evidence": [
            _evidence(
                tool="generate_idv_documents",
                description="Generated synthetic ID&V documents",
                source="Synthetic demo document generator",
                data={"artifacts": artifacts},
                relevance_tags=["idv", "document", "synthetic_demo"],
            )
        ],
    }


def extract_idv_documents(state: CDDState) -> dict[str, Any]:
    """Extract generated ID&V documents and populate the ID&V CDD section."""
    cdd = deepcopy(state.get("cdd", {}))
    idv = cdd.setdefault("individual_identity_verification", {})
    individuals = idv.get("required_individuals", [])
    artifact_data = _latest_evidence_data(state, "generate_idv_documents") or {}
    artifacts = artifact_data.get("artifacts") or []

    extracts = []
    for artifact in artifacts:
        classification = classify_document(artifact["pdf_path"])
        extract = extract_document(artifact, classification=classification)
        extracts.append(
            {
                "artifact": artifact,
                "classification": classification,
                "extract": extract,
            }
        )

    _apply_idv_extracts(individuals, extracts)
    idv["required_individuals"] = individuals
    idv["missing_items"] = [
        row.get("name") for row in individuals if row.get("status") != "verified"
    ]
    idv["status"] = "complete" if not idv["missing_items"] else "incomplete"
    cdd["individual_identity_verification"] = idv
    cdd.setdefault("documents", []).extend(extracts)
    return {
        "cdd": cdd,
        "messages": [AIMessage(content="Extracting ID&V documents.")],
        "evidence": [
            _evidence(
                tool="extract_idv_documents",
                description="Classified and extracted ID&V document data",
                source="OpenAI document extraction",
                data={"documents": extracts},
                relevance_tags=["idv", "document_extraction"],
            )
        ],
    }


def evaluate_risk_flags(state: CDDState) -> dict[str, Any]:
    flags = []
    cdd = state.get("cdd", {})
    ownership = cdd.get("ownership_and_control", {})
    if not ownership.get("ubos"):
        flags.append(
            {
                "category": "ownership",
                "severity": "medium",
                "description": "No individual UBO above 25% was identified.",
                "source": "org_chart",
                "status": "open",
            }
        )
    for member in ownership.get("members", {}).get("controlling_members", []):
        kyc = member.get("kyc", {})
        if kyc.get("is_aml_positive"):
            flags.append(
                {
                    "category": "aml",
                    "severity": "high",
                    "description": f"AML review flag for {member.get('name')}.",
                    "source": "members",
                    "status": "open",
                }
            )
    return {"risk_flags": flags}


def finalize_cdd(state: CDDState) -> dict[str, Any]:
    cdd = deepcopy(state.get("cdd", {}))
    section_statuses = [
        cdd.get("ownership_and_control", {}).get("status"),
        cdd.get("company_business_profile", {}).get("status"),
        cdd.get("individual_identity_verification", {}).get("status"),
    ]
    complete = all(status == "complete" for status in section_statuses)
    open_flags = [flag for flag in state.get("risk_flags", []) if flag.get("status") == "open"]

    if complete and not open_flags:
        recommendation = "completed"
        cdd["status"] = "complete"
        cdd["completed_at"] = datetime.now(UTC).isoformat()
    else:
        recommendation = "human_review"
        cdd["status"] = "incomplete"

    return {"cdd": cdd, "final_recommendation": recommendation}


def _client() -> KycClient:
    if not CLIENT_ID or not CLIENT_SECRET:
        raise ValueError("KYCCLIENTID and KYCCLIENTSECRET are required")
    return KycClient(BASE_URL, CLIENT_ID, CLIENT_SECRET)


def _case_id(state: CDDState) -> int | str:
    case_id = state.get("metadata", {}).get("kyc_case", {}).get("case_id")
    if case_id is None:
        raise ValueError("metadata.kyc_case.case_id is required")
    return case_id


def _evidence(
    *,
    tool: str,
    description: str,
    data: dict[str, Any],
    relevance_tags: list[str],
    source: str = "KYC API",
) -> dict[str, Any]:
    return {
        "source": source,
        "tool": tool,
        "description": description,
        "relevance_tags": relevance_tags,
        "data": data,
        "collected_at": datetime.now(UTC).isoformat(),
    }


def _latest_evidence_data(state: CDDState, tool: str) -> dict[str, Any] | None:
    for item in reversed(state.get("evidence", [])):
        if item.get("tool") == tool:
            data = item.get("data")
            if isinstance(data, dict):
                return data
    return None


def _apply_idv_extracts(
    individuals: list[dict[str, Any]],
    extracts: list[dict[str, Any]],
) -> None:
    by_key = {}
    for item in extracts:
        artifact = item.get("artifact", {})
        extract = item.get("extract", {})
        key = _identity_key(
            {
                "name": artifact.get("person_name") or extract.get("full_name"),
                "case_common_id": artifact.get("case_common_id"),
            }
        )
        by_key[key] = item

    for individual in individuals:
        item = by_key.get(_identity_key(individual))
        if not item:
            continue
        extract = item.get("extract", {})
        artifact = item.get("artifact", {})
        document = {
            "document_type": extract.get("document_type"),
            "full_name": extract.get("full_name"),
            "document_number": extract.get("document_number"),
            "nationality": extract.get("nationality"),
            "date_of_birth": extract.get("date_of_birth"),
            "expiry_date": extract.get("expiry_date"),
            "issuing_country": extract.get("issuing_country"),
            "address": extract.get("address"),
            "source": extract.get("extraction", {}).get("source") or artifact.get("source"),
            "document_path": extract.get("extraction", {}).get("document_path")
            or artifact.get("pdf_path"),
        }
        individual["document"] = _drop_empty(document)
        individual["status"] = "verified"


def _identity_key(row: dict[str, Any]) -> tuple[str, str]:
    case_common_id = row.get("case_common_id")
    if case_common_id not in (None, ""):
        return ("id", str(case_common_id))
    return ("name", " ".join(str(row.get("name") or "").casefold().split()))


def _drop_empty(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if value not in (None, "", [], {})}


def _section_status(data: dict[str, Any], *, required: tuple[str, ...]) -> str:
    return "complete" if not _missing(data, required) else "incomplete"


def _missing(data: dict[str, Any], required: tuple[str, ...]) -> list[str]:
    return [field for field in required if data.get(field) in (None, "", [], {})]
