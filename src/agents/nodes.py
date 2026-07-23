"""LangGraph node functions for the CDD agent."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage
from langgraph.types import interrupt

from src.agents.businesslogic import build_ownership_tables
from src.agents.red_flags_graph import run_red_flags_graph
from src.agents.state import CDDState
from src.tools.cdd_enrichment import (
    apply_document_extract_to_cdd,
    missing_about_customer_fields,
)
from src.tools.customer_static import _fetch_customer_static
from src.tools.document_extraction import classify_document, extract_document
from src.tools.idv_policy import interpret_idv_policy
from src.tools.idv_requirements import establish_idv_requirements as apply_idv_requirements
from src.tools.case_review import (
    CaseReviewError,
    generate_case_review_summary,
    merge_case_review_assessments,
    unavailable_case_review,
)
from src.tools.risk_severity_policy import interpret_risk_severity_policy
from src.tools.members import _fetch_company_members
from src.tools.orgchart import _fetch_company_org_chart
from src.utils.create_case import BASE_URL, CLIENT_ID, CLIENT_SECRET, KycClient, create_company_case
from src.utils.case_status import build_case_status
from src.utils.document_pipeline import REGISTRY_SOURCE_LABEL, generate_registry_document
from src.utils.idv_document_pipeline import IDV_SOURCE_LABELS, generate_idv_documents
from src.utils.s3_documents import (
    download_document_from_s3,
    find_documents_in_s3,
    reusable_document_name,
    s3_upload_skip_reason,
    upload_document_to_s3,
)


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
    """Reuse or generate a synthetic registry document for the current CDD object."""
    cdd = state.get("cdd", {})
    company_name, jurisdiction = _document_scope(state)
    existing_documents = find_documents_in_s3(
        company_name=company_name,
        jurisdiction=jurisdiction,
    )
    expected_name = (
        reusable_document_name(
            document_type="registry_document",
            company_name=company_name,
        )
        if company_name
        else None
    )
    document = _find_document(existing_documents, expected_name)
    if document:
        artifact = _reused_artifact(
            document,
            document_type="registry_document",
            source=REGISTRY_SOURCE_LABEL,
        )
    else:
        artifact = generate_registry_document(cdd)
        document = upload_document_to_s3(
            artifact["pdf_path"],
            category=artifact["document_type"],
            case_id=state.get("metadata", {}).get("kyc_case", {}).get("case_id"),
            source=artifact.get("source"),
            company_name=company_name,
            jurisdiction=jurisdiction,
            object_name=expected_name,
        )
    if document:
        artifact["s3_url"] = document["url"]
        artifact["storage"] = document["storage"]
        document["collected_at"] = artifact.get("generated_at")
    else:
        artifact["storage"] = {
            "provider": "s3",
            "status": "skipped",
            "reason": s3_upload_skip_reason() or "upload did not return a document URL",
        }
    update = {
        "messages": [
            AIMessage(
                content=(
                    "Reusing registry document from S3."
                    if artifact.get("reused_from_s3")
                    else "Generating registry document."
                )
            )
        ],
        "evidence": [
            _evidence(
                tool="generate_registry_document",
                description=(
                    "Reused registry business profile document from S3"
                    if artifact.get("reused_from_s3")
                    else "Generated synthetic registry business profile document"
                ),
                source=(
                    "S3 document store"
                    if artifact.get("reused_from_s3")
                    else "Synthetic demo document generator"
                ),
                data=artifact,
                relevance_tags=[
                    "document",
                    "registry_document",
                    "company_profile",
                    "synthetic_demo",
                ],
            )
        ],
    }
    if document:
        update["documents"] = [document]
    return update


def extract_registry_document(state: CDDState) -> dict[str, Any]:
    """Classify and extract structured data from the generated registry document."""
    artifact = _latest_evidence_data(state, "generate_registry_document") or {}
    if not artifact:
        raise ValueError("Generated registry document artifact is required")

    classification = classify_document(artifact["pdf_path"])
    extract = extract_document(artifact, classification=classification)
    deleted_local_paths = []
    if artifact.get("s3_url"):
        deleted_local_paths = _delete_local_document_artifacts(artifact)
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
                    "deleted_local_paths": deleted_local_paths,
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


def locate_available_documents(state: CDDState) -> dict[str, Any]:
    """Build the officer work queue and locate reusable S3 documents."""
    cdd = state.get("cdd", {})
    individuals = cdd.get("individual_identity_verification", {}).get("required_individuals", [])
    company_name, jurisdiction = _document_scope(state)
    available = find_documents_in_s3(company_name=company_name, jurisdiction=jurisdiction)
    by_name = {item.get("name"): item for item in available}
    requirements = []
    registry_artifact = _latest_evidence_data(state, "generate_registry_document") or {}
    if registry_artifact:
        requirements.append({
            "id": "registry-document",
            "entity_name": "Registry document",
            "document_type": "registry_document",
            "individual": {},
            "status": "processed",
            "cache_document": registry_artifact.get("storage") and {
                "storage": registry_artifact.get("storage"),
                "url": registry_artifact.get("s3_url"),
            },
        })
    for index, individual in enumerate(individuals):
        document_type = individual.get("selected_document_type") or "passport"
        expected_name = reusable_document_name(
            document_type=document_type,
            company_name=company_name or "Company",
            person_name=individual.get("name"),
        )
        cached = by_name.get(expected_name)
        requirements.append({
            "id": f"idv-{index}-{document_type}",
            "entity_name": individual.get("name"),
            "document_type": document_type,
            "individual": individual,
            "status": "cache_found" if cached else "not_found",
            "cache_document": cached,
        })
    return {"document_requirements": requirements}


def await_documents(state: CDDState) -> dict[str, Any]:
    """Pause the graph until every officer document requirement is available."""
    requirements = state.get("document_requirements", [])
    outstanding = [row for row in requirements if row.get("status") == "not_found"]
    if outstanding:
        interrupt({"status": "awaiting_documents", "requirements": outstanding})
    return {}


def process_available_documents(state: CDDState) -> dict[str, Any]:
    """Process cached documents before pausing for outstanding officer documents."""
    return extract_idv_documents(state)


def generate_idv_documents_node(state: CDDState) -> dict[str, Any]:
    """Reuse S3 identity documents and generate only those still required."""
    cdd = state.get("cdd", {})
    idv = cdd.get("individual_identity_verification", {})
    individuals = idv.get("required_individuals", [])
    company_name, jurisdiction = _document_scope(state)
    existing_documents = find_documents_in_s3(
        company_name=company_name,
        jurisdiction=jurisdiction,
    )
    artifacts = []
    documents = []
    case_id = state.get("metadata", {}).get("kyc_case", {}).get("case_id")
    missing_individuals = []
    for individual in individuals:
        document_type = individual.get("selected_document_type") or "passport"
        expected_name = (
            reusable_document_name(
                document_type=document_type,
                company_name=company_name,
                person_name=individual.get("name"),
            )
            if company_name and individual.get("name")
            else None
        )
        document = _find_document(existing_documents, expected_name)
        if not document:
            missing_individuals.append(individual)
            continue
        document["person_name"] = individual.get("name")
        document["source"] = IDV_SOURCE_LABELS.get(document_type, "Identity Document")
        artifact = _reused_artifact(
            document,
            document_type=document_type,
            source=document["source"],
            person_name=individual.get("name"),
        )
        artifacts.append(artifact)
        documents.append(document)

    for artifact in generate_idv_documents(missing_individuals):
        document = upload_document_to_s3(
            artifact["pdf_path"],
            category=artifact["document_type"],
            case_id=case_id,
            person_name=artifact.get("person_name"),
            source=artifact.get("source"),
            company_name=company_name,
            jurisdiction=jurisdiction,
            object_name=(
                reusable_document_name(
                    document_type=artifact["document_type"],
                    company_name=company_name,
                    person_name=artifact.get("person_name"),
                )
                if company_name and artifact.get("person_name")
                else None
            ),
        )
        artifacts.append(artifact)
        if not document:
            artifact["storage"] = {
                "provider": "s3",
                "status": "skipped",
                "reason": s3_upload_skip_reason() or "upload did not return a document URL",
            }
            continue
        artifact["s3_url"] = document["url"]
        artifact["storage"] = document["storage"]
        document["collected_at"] = artifact["generated_at"]
        documents.append(document)

    update = {
        "messages": [
            AIMessage(
                content=(
                    "Reusing available ID&V documents from S3 and generating missing documents."
                    if any(artifact.get("reused_from_s3") for artifact in artifacts)
                    else "Generating ID&V documents."
                )
            )
        ],
        "evidence": [
            _evidence(
                tool="generate_idv_documents",
                description="Reused available S3 ID&V documents and generated missing documents",
                source="Synthetic demo document generator",
                data={"artifacts": artifacts},
                relevance_tags=["idv", "document", "synthetic_demo"],
            )
        ],
    }
    if documents:
        update["documents"] = documents
    return update


def extract_idv_documents(state: CDDState) -> dict[str, Any]:
    """Extract generated ID&V documents and populate the ID&V CDD section."""
    cdd = deepcopy(state.get("cdd", {}))
    idv = cdd.setdefault("individual_identity_verification", {})
    individuals = idv.get("required_individuals", [])
    artifact_data = _latest_evidence_data(state, "generate_idv_documents") or {}
    artifacts = artifact_data.get("artifacts") or _document_requirement_artifacts(state)

    extracts = []
    for artifact in artifacts:
        classification = classify_document(artifact["pdf_path"])
        extract = extract_document(artifact, classification=classification)
        deleted_local_paths = []
        if artifact.get("s3_url"):
            deleted_local_paths = _delete_local_document_artifacts(artifact)
        extracts.append(
            {
                "artifact": artifact,
                "classification": classification,
                "extract": extract,
                "deleted_local_paths": deleted_local_paths,
            }
        )

    _apply_idv_extracts(individuals, extracts)
    requirements = deepcopy(state.get("document_requirements", []))
    processed_keys = {
        _identity_key(
            {
                "name": item.get("artifact", {}).get("person_name")
                or item.get("extract", {}).get("full_name"),
                "case_common_id": item.get("artifact", {}).get("case_common_id"),
            }
        )
        for item in extracts
    }
    for requirement in requirements:
        identity = _identity_key(requirement.get("individual", {}))
        if identity in processed_keys:
            requirement["status"] = "processed"
            requirement["processed_at"] = datetime.now(UTC).isoformat()
    idv["required_individuals"] = individuals
    idv["missing_items"] = [
        row.get("name") for row in individuals if row.get("status") != "verified"
    ]
    idv["status"] = "complete" if not idv["missing_items"] else "incomplete"
    cdd["individual_identity_verification"] = idv
    cdd.setdefault("documents", []).extend(extracts)
    update = {
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
    if requirements:
        update["document_requirements"] = requirements
    return update


def _document_requirement_artifacts(state: CDDState) -> list[dict[str, Any]]:
    """Materialize cached or officer-supplied requirements for graph extraction."""
    artifacts = []
    for requirement in state.get("document_requirements", []):
        if requirement.get("status") not in {"cache_found", "provided", "received"}:
            continue
        artifact = deepcopy(requirement.get("artifact") or {})
        cached = requirement.get("cache_document")
        if cached and not artifact:
            artifact = {
                "pdf_path": download_document_from_s3(cached),
                "s3_url": cached.get("url"),
                "storage": cached.get("storage"),
                "source": "S3 document cache",
            }
        if not artifact.get("pdf_path"):
            continue
        artifact.setdefault("document_type", requirement.get("document_type"))
        artifact.setdefault("person_name", requirement.get("entity_name"))
        artifact.setdefault("case_common_id", requirement.get("individual", {}).get("case_common_id"))
        if not artifact.get("s3_url"):
            company_name, jurisdiction = _document_scope(state)
            document = upload_document_to_s3(
                artifact["pdf_path"],
                category=requirement.get("document_type") or "passport",
                person_name=requirement.get("entity_name"),
                source=artifact.get("source"),
                company_name=company_name,
                jurisdiction=jurisdiction,
                object_name=reusable_document_name(
                    document_type=requirement.get("document_type") or "passport",
                    company_name=company_name or "Company",
                    person_name=requirement.get("entity_name"),
                ),
            )
            if document:
                artifact["s3_url"] = document["url"]
                artifact["storage"] = document["storage"]
        artifacts.append(artifact)
    return artifacts


def evaluate_risk_flags(state: CDDState) -> dict[str, Any]:
    """Run the focused red-flags subgraph and merge its additive outputs."""
    cdd = state.get("cdd", {})
    severity_policy = interpret_risk_severity_policy()
    result = run_red_flags_graph(
        customer_static=cdd.get("company_business_profile", {}).get("customer_static", {}),
        ownership_and_control=cdd.get("ownership_and_control", {}),
        severity_policy=severity_policy,
    )
    return {
        "evidence": [
            *result.get("evidence", []),
            _evidence(
                tool="interpret_risk_severity_policy",
                description="Interpreted and applied the risk-severity policy",
                source="OpenAI policy interpretation",
                data=severity_policy,
                relevance_tags=["risk", "severity", "policy"],
            ),
        ],
        "risk_flags": result.get("risk_flags", []),
    }


def finalize_cdd(state: CDDState) -> dict[str, Any]:
    cdd = deepcopy(state.get("cdd", {}))
    section_statuses = [
        cdd.get("ownership_and_control", {}).get("status"),
        cdd.get("company_business_profile", {}).get("status"),
        cdd.get("individual_identity_verification", {}).get("status"),
    ]
    complete = all(status == "complete" for status in section_statuses)
    findings_needing_review = [
        flag for flag in state.get("risk_flags", [])
        if flag.get("evaluation") in {"yes", "inconclusive"}
    ]

    cdd["completed_at"] = datetime.now(UTC).isoformat()
    return {
        "cdd": cdd,
        "case_status": build_case_status("completed" if complete else "incomplete", state.get("risk_flags", [])),
    }


def generate_case_review(state: CDDState) -> dict[str, Any]:
    """Create a reviewer brief from completed CDD data without changing its outcome."""
    try:
        summary = generate_case_review_summary(
            cdd=state.get("cdd", {}),
            case_status=state.get("case_status", {}),
            risk_flags=state.get("risk_flags", []),
            evidence=state.get("evidence", []),
        )
    except CaseReviewError as exc:
        summary = unavailable_case_review(str(exc))
    return {
        "case_review_summary": summary,
        "risk_flags": merge_case_review_assessments(state.get("risk_flags", []), summary),
    }


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


def _delete_local_document_artifacts(artifact: dict[str, Any]) -> list[str]:
    deleted = []
    for key in ("pdf_path", "html_path", "json_path"):
        value = artifact.get(key)
        if not value:
            continue
        path = Path(value)
        if not path.exists() or not path.is_file():
            continue
        path.unlink()
        deleted.append(str(path))
    return deleted


def _document_scope(state: CDDState) -> tuple[str | None, str | None]:
    """Resolve the company/jurisdiction S3 folder from enriched state."""
    static = (
        state.get("cdd", {})
        .get("company_business_profile", {})
        .get("customer_static", {})
    )
    customer = state.get("metadata", {}).get("customer", {})
    return (
        static.get("name") or customer.get("name"),
        static.get("jurisdiction") or customer.get("jurisdiction"),
    )


def _find_document(
    documents: list[dict[str, Any]],
    expected_name: str | None,
) -> dict[str, Any] | None:
    if not expected_name:
        return None
    return next(
        (document for document in documents if document.get("name") == expected_name),
        None,
    )


def _reused_artifact(
    document: dict[str, Any],
    *,
    document_type: str,
    source: str,
    person_name: str | None = None,
) -> dict[str, Any]:
    """Turn an S3 listing result into the artifact shape consumed by extract nodes."""
    return {
        "document_type": document_type,
        "source": source,
        "person_name": person_name,
        "pdf_path": download_document_from_s3(document),
        "generated_at": str(
            document.get("last_modified") or datetime.now(UTC).isoformat()
        ),
        "s3_url": document["url"],
        "storage": document["storage"],
        "reused_from_s3": True,
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
            "document_url": artifact.get("s3_url"),
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
