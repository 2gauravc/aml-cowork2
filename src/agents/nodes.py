"""LangGraph node functions for the CDD agent."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage
from langgraph.types import Overwrite, interrupt

from src.agents.businesslogic import build_ownership_tables
from src.agents.state import CDDState, classify_evidence_item
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
    unavailable_case_review,
)
from src.tools.csp_assessment import assess_csp_address as build_csp_assessment
from src.tools.adverse_news import AdverseNewsError, load_finding_schema, screen_adverse_news
from src.tools.digital_footprint import DigitalFootprintError, evaluate_digital_footprint
from src.tools.cdd_completeness import CDDCompletenessError, evaluate_cdd_completeness
from src.tools.evidence_quality import EvidenceQualityError, evaluate_evidence_quality
from src.tools.other_risk_factors import OtherRiskFactorsError, evaluate_other_risk_factors
from src.tools.shell_company_risk import ShellCompanyRiskError, evaluate_shell_company_risk
from src.tools.risk_rating import RiskRatingError, evaluate_risk_rating
from src.tools.members import _fetch_company_members
from src.tools.orgchart import _fetch_company_org_chart
from src.utils.create_case import BASE_URL, CLIENT_ID, CLIENT_SECRET, KycClient, create_company_case
from src.utils.document_pipeline import REGISTRY_SOURCE_LABEL, generate_registry_document
from src.utils.idv_document_pipeline import IDV_SOURCE_LABELS, generate_idv_documents
from src.utils.s3_documents import (
    download_document_from_s3,
    find_documents_in_s3,
    reusable_document_name,
    s3_upload_skip_reason,
    upload_document_to_s3,
)
from src.utils.kyc_cache import CacheSubject, company_cache_subject


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
    result = _fetch_customer_static(
        case_id,
        client=_client(),
        cache_subject=_cache_subject_from_state(state),
    )
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
    result = _fetch_company_org_chart(
        case_id,
        client=_client(),
        cache_subject=_cache_subject_from_state(state),
    )
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
    result = _fetch_company_members(
        case_id,
        client=_client(),
        cache_subject=_cache_subject_from_state(state),
    )
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
    # Older generated registry documents have no retained synthetic provenance
    # and may contain the retired generic activity default. Regenerate those
    # once so they receive the current activity-inference format.
    if document and document.get("provenance") != "synthetic_demo":
        document = None
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
            source_type=artifact.get("source_type"),
            provenance=artifact.get("provenance"),
            synthetic=artifact.get("synthetic"),
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
    update["documents"] = [_document_record(
        document_id="document:registry",
        purpose="company_profile",
        document_type="registry_document",
        subject={"name": "Registry document"},
        requirement={"required": True, "reason": ["Company business profile"]},
        status="located" if artifact.get("pdf_path") else "unavailable",
        gap={
            "status": "resolved" if artifact.get("pdf_path") else "outstanding",
            "reason": "" if artifact.get("pdf_path") else "Registry document could not be obtained.",
        },
        artifact=artifact,
    )]
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
    return {
        "cdd": cdd,
        "documents": [{
            "document_id": "document:registry",
            "status": "processed",
            "gap": {"status": "resolved", "reason": ""},
            "processing": {
                "classification": classification,
                "extract": extract,
                "applied_fields": applied_fields,
                "missing_fields_before": missing_before,
                "processed_at": datetime.now(UTC).isoformat(),
            },
        }],
    }


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
    """Create canonical ID&V document requirements and locate reusable files."""
    cdd = state.get("cdd", {})
    individuals = cdd.get("individual_identity_verification", {}).get("required_individuals", [])
    company_name, jurisdiction = _document_scope(state)
    available = find_documents_in_s3(company_name=company_name, jurisdiction=jurisdiction)
    by_name = {item.get("name"): item for item in available}
    documents = []
    for index, individual in enumerate(individuals):
        document_type = individual.get("selected_document_type") or "passport"
        expected_name = reusable_document_name(
            document_type=document_type,
            company_name=company_name or "Company",
            person_name=individual.get("name"),
        )
        cached = by_name.get(expected_name)
        documents.append(_document_record(
            document_id=f"document:idv:{individual.get('case_common_id') or index}:1",
            purpose="identity_verification",
            document_type=document_type,
            subject={"name": individual.get("name"), "case_common_id": individual.get("case_common_id")},
            requirement={
                "policy": "identity_verification",
                "reason": individual.get("reasons", []),
                "accepted_types": individual.get("required_documents", []),
                "minimum_required": 1,
            },
            status="located" if cached else "required",
            gap={
                "status": "resolved" if cached else "outstanding",
                "reason": "" if cached else "No acceptable identity document is available.",
            },
            artifact=_cached_artifact(cached, document_type, individual) if cached else {},
        ))
    return {"documents": documents}


def await_documents(state: CDDState) -> dict[str, Any]:
    """Pause the graph until every officer document requirement is available."""
    outstanding = [
        document for document in state.get("documents", [])
        if document.get("purpose") == "identity_verification"
        and (document.get("gap") or {}).get("status") == "outstanding"
    ]
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
            source_type=artifact.get("source_type"),
            provenance=artifact.get("provenance"),
            synthetic=artifact.get("synthetic"),
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
        document["source_type"] = artifact.get("source_type")
        document["provenance"] = artifact.get("provenance")
        document["synthetic"] = artifact.get("synthetic")
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
    document_updates = []
    for item in extracts:
        artifact = item.get("artifact", {})
        identity = _identity_key({
            "name": artifact.get("person_name") or item.get("extract", {}).get("full_name"),
            "case_common_id": artifact.get("case_common_id"),
        })
        for document in state.get("documents", []):
            if document.get("purpose") != "identity_verification":
                continue
            if _identity_key(document.get("subject") or {}) != identity:
                continue
            document_updates.append({
                "document_id": document["document_id"],
                "status": "processed",
                "gap": {"status": "resolved", "reason": ""},
                "storage": artifact.get("storage") or document.get("storage") or {},
                "url": artifact.get("s3_url") or document.get("url"),
                "acquisition": {"source": artifact.get("source"), "artifact": artifact},
                "processing": {
                    "classification": item.get("classification"),
                    "extract": item.get("extract"),
                    "validation": _idv_validation(document, item),
                    "processed_at": datetime.now(UTC).isoformat(),
                },
            })
    idv["required_individuals"] = individuals
    idv["missing_items"] = [
        row.get("name") for row in individuals if row.get("status") != "verified"
    ]
    idv["status"] = "complete" if not idv["missing_items"] else "incomplete"
    cdd["individual_identity_verification"] = idv
    update = {
        "cdd": cdd,
        "documents": document_updates,
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
    return update


def adverse_news_screening(state: CDDState) -> dict[str, Any]:
    """Screen final CDD identities and add only new evidence/findings."""
    try:
        result = screen_adverse_news(state.get("cdd", {}))
        run_id = f"run:adverse-news:{uuid4().hex}"
        source_evidence = []
        source_ids: dict[str, str] = {}
        for item in result["sources"]:
            evidence_id = item.get("evidence_id") or f"evidence:adverse-news:{uuid4().hex}"
            source_ids[evidence_id] = evidence_id
            source_evidence.append(
                {
                    "evidence_id": evidence_id,
                    "source": "Brave Search",
                    "tool": "adverse_news_screening",
                    "description": item.get("title") or "Adverse-news web search result",
                    "relevance_tags": ["adverse_news", "web_search"],
                    "data": item,
                    "source_url": item.get("url"),
                    "published_at": item.get("published_date"),
                    "collected_at": result["evaluated_at"],
                }
            )
        entities = {entity["key"]: entity for entity in result["entities"]}
        queries_by_entity = {item["entity_key"]: item["query"] for item in result["queries"]}
        assessment = _assemble_adverse_news_assessment(
            result["assessment"], result["entities"], result["queries"], list(source_ids.values()),
            run_id, result["evaluated_at"], bool(result["drafts"]),
        )
        findings = [_assemble_adverse_news_finding(draft, entities, source_ids, run_id, result["definition"]["overlay"], queries_by_entity, assessment) for draft in result["drafts"]]
        assessment["definition"] = {
            "skill_path": result["definition"]["path"],
            "definition_version": result["definition"].get("definition_version"),
            "contract_path": result["definition"].get("contract_path"),
            "contract_version": result["definition"].get("contract_version"),
            "presentation_path": result["definition"].get("presentation_path"),
            "presentation_version": result["definition"].get("presentation_version"),
        }
        return {"evidence": [classify_evidence_item(item) for item in source_evidence], "findings": findings, "assessments": [assessment]}
    except AdverseNewsError as exc:
        evaluated_at = datetime.now(UTC).isoformat()
        return {
            "evidence": [
                _evidence(
                    tool="adverse_news_screening",
                    description="Adverse-news screening could not be completed.",
                    source="Adverse News Screening",
                    data={"reason": str(exc)},
                    relevance_tags=["adverse_news"],
                )
            ],
            "findings": [],
            "assessments": [{
                "assessment_id": f"assessment:adverse-news:{uuid4().hex}",
                "assessment_type": "adverse_news",
                "schema_version": "adverse_news_assessment/v1",
                "tool": "adverse_news_screening",
                "run_id": None,
                "created_at": evaluated_at,
                "outcome": "unavailable",
                "summary": "Adverse-news screening could not be completed.",
                "limitations": [str(exc)],
                "screened_entities": [],
                "queries": [],
                "source_evidence_ids": [],
                "entity_outcomes": [],
            }],
        }


def digital_footprint_assessment(state: CDDState) -> dict[str, Any]:
    """Run the standalone digital-footprint tool and normalize its shared outputs."""
    try:
        inputs = _digital_footprint_inputs(state)
        result = evaluate_digital_footprint(**inputs)
        run_id = f"run:digital-footprint:{uuid4().hex}"
        evidence, ids = [], {}
        for source in result["sources"]:
            evidence_id = source["evidence_id"]; ids[evidence_id] = evidence_id
            evidence.append({"evidence_id": evidence_id, "source": "Tavily", "tool": "digital_footprint_assessment", "description": source.get("title") or "Digital-footprint web search result", "relevance_tags": ["digital_footprint", "web_search"], "data": {**source, "web_search_evidence": {"schema_version": "web_search_evidence/v1", "evidence_id": evidence_id}}, "source_url": source.get("url"), "published_at": source.get("published_date"), "collected_at": result["evaluated_at"]})
        assessment = {"assessment_id": result["assessment"]["assessment_id"], "assessment_type": "digital_footprint", "schema_version": result["definition"]["assessment_definition"]["schema_version"], "definition": {**result["definition"]["assessment_definition"], "contract_path": result["definition"].get("contract_path"), "contract_version": result["definition"].get("contract_version"), "presentation_path": result["definition"].get("presentation_path"), "presentation_version": result["definition"].get("presentation_version")}, "tool": "digital_footprint_assessment", "run_id": run_id, "created_at": result["evaluated_at"], "company_inputs": result["company_inputs"], "queries": result["queries"], **result["assessment"]}
        findings=[]
        for draft in result["findings"]:
            refs=draft.get("relevant_evidence_ids") or []; unknown=set(refs)-set(ids)
            if unknown: raise DigitalFootprintError(f"Digital-footprint assessment cited unknown sources: {', '.join(sorted(unknown))}")
            if draft.get("assessment_id") != assessment["assessment_id"] or not set(refs).issubset(set(assessment["source_evidence_ids"])): raise DigitalFootprintError("Digital-footprint finding must link to its producing assessment and selected evidence")
            overlay=draft.get("digital_footprint") or {}; overlay["screening_coverage"]={**overlay.get("screening_coverage",{}),"queries":result["queries"],"source_evidence_ids":refs,"limitations":assessment["limitations"]}
            finding={key:draft.get(key) for key in ("title","summary","confidence","severity","potential_impact_risk","recommended_action_rfi")}
            finding.update({"finding_id":f"finding:digital-footprint:{uuid4().hex}","schema_version":"finding/v1","category":"digital_footprint","assessment_id":assessment["assessment_id"],"subject":{"entity_id":result["company_inputs"].get("registration_number"),"entity_type":"company","name":result["company_inputs"]["company_name"]},"source":{"producer_type":"tool","producer_name":"digital_footprint_assessment","run_id":run_id,"created_at":result["evaluated_at"]},"relevant_evidence_ids":refs,"digital_footprint":overlay})
            _validate_finding(finding)
            findings.append(finding)
        assessment["outcome"] = "completed_with_findings" if findings else assessment["outcome"]
        return {"evidence":[classify_evidence_item(item) for item in evidence],"assessments":[assessment],"findings":findings}
    except Exception as exc:
        return {"evidence": [_evidence(tool="digital_footprint_assessment",description="Digital-footprint assessment could not be completed.",source="Digital Footprint",data={"reason":str(exc)},relevance_tags=["digital_footprint"])], "assessments":[{"assessment_id":f"assessment:digital-footprint:{uuid4().hex}","assessment_type":"digital_footprint","schema_version":"digital_footprint_assessment/v1","tool":"digital_footprint_assessment","run_id":None,"created_at":datetime.now(UTC).isoformat(),"outcome":"unavailable","limitations":[str(exc)],"company_inputs":{},"queries":[],"source_evidence_ids":[]}], "findings":[]}


def _digital_footprint_inputs(state: CDDState) -> dict[str, Any]:
    """Use explicit standalone inputs when present, otherwise derive company identity from CDD."""
    explicit = state.get("digital_footprint_inputs") or {}
    if explicit.get("company_name"):
        return {key: explicit.get(key) for key in ("company_name", "jurisdiction", "registration_number", "known_domain", "registered_address")}
    static = ((state.get("cdd") or {}).get("company_business_profile") or {}).get("customer_static") or {}
    registered_address = static.get("registered_address") or static.get("registeredAddress")
    if isinstance(registered_address, dict):
        registered_address = (
            registered_address.get("full_address")
            or registered_address.get("raw_address")
            or ", ".join(
                str(registered_address[key]).strip()
                for key in ("address_line_1", "address_line_2", "city", "postcode", "country")
                if registered_address.get(key)
            )
        )
    return {
        "company_name": static.get("name"),
        "jurisdiction": static.get("jurisdiction"),
        "registration_number": static.get("registration_number") or static.get("registrationNumber"),
        "known_domain": static.get("website") or static.get("website_url") or static.get("domain"),
        "registered_address": registered_address,
    }


def _assemble_adverse_news_assessment(
    draft: dict[str, Any], entities: list[dict[str, Any]], queries: list[dict[str, str]],
    source_evidence_ids: list[str], run_id: str, evaluated_at: str, has_findings: bool,
) -> dict[str, Any]:
    outcomes = draft.get("entity_outcomes")
    entity_keys = {entity["key"] for entity in entities}
    if not isinstance(outcomes, list) or len(outcomes) != len(entities) or {item.get("entity_key") for item in outcomes if isinstance(item, dict)} != entity_keys:
        raise AdverseNewsError("Adverse-news assessment must provide one entity outcome for every screened entity")
    outcome = draft.get("outcome")
    if outcome not in {"completed_no_material_findings", "completed_inconclusive"} or not isinstance(draft.get("summary"), str) or not isinstance(draft.get("limitations"), list):
        raise AdverseNewsError("Adverse-news assessment returned an incomplete assessment")
    return {
        "assessment_id": draft.get("assessment_id") or f"assessment:adverse-news:{uuid4().hex}",
        "assessment_type": "adverse_news",
        "schema_version": "adverse_news_assessment/v1",
        "tool": "adverse_news_screening",
        "run_id": run_id,
        "created_at": evaluated_at,
        "outcome": "completed_with_findings" if has_findings else outcome,
        "summary": draft["summary"],
        "limitations": draft["limitations"],
        "screened_entities": entities,
        "queries": queries,
        "source_evidence_ids": draft.get("source_evidence_ids") or source_evidence_ids,
        "entity_outcomes": outcomes,
    }


def _assemble_adverse_news_finding(
    draft: dict[str, Any],
    entities: dict[str, dict[str, Any]],
    source_ids: dict[str, str],
    run_id: str,
    overlay_definition: dict[str, Any],
    queries_by_entity: dict[str, str],
    assessment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    entity = entities.get(str(draft.get("entity_key")))
    if not entity:
        raise AdverseNewsError("Adverse-news assessment returned an unknown entity")
    refs = draft.get("relevant_evidence_ids") or draft.get("source_refs")
    if not isinstance(refs, list) or not refs:
        raise AdverseNewsError("Adverse-news finding must cite retained source references")
    unknown = {str(reference) for reference in refs} - set(source_ids)
    if unknown:
        raise AdverseNewsError(f"Adverse-news assessment cited unknown sources: {', '.join(sorted(unknown))}")
    if assessment is not None:
        if draft.get("assessment_id") != assessment["assessment_id"]:
            raise AdverseNewsError("Adverse-news finding must link to its producing assessment")
        if not set(refs).issubset(set(assessment["source_evidence_ids"])):
            raise AdverseNewsError("Adverse-news finding evidence must be selected by its linked assessment")
    overlay = draft.get("adverse_news")
    required_overlay = overlay_definition.get("required") or []
    if not isinstance(overlay, dict) or any(field not in overlay for field in required_overlay):
        raise AdverseNewsError("Adverse-news assessment returned an incomplete adverse_news/v1 overlay")
    overlay = deepcopy(overlay)
    available_disambiguators = entity.get("disambiguators", {})
    used_disambiguators = overlay.get("screened_entity", {}).get("disambiguators_used")
    if not isinstance(used_disambiguators, list) or any(
        not isinstance(name, str) or name not in available_disambiguators
        for name in used_disambiguators
    ):
        raise AdverseNewsError(
            "Adverse-news finding must identify only available CDD disambiguators used for identity resolution"
        )
    overlay["screened_entity"] = {
        "entity_type": entity["entity_type"],
        "name_used": entity["name"],
        "disambiguators_available": available_disambiguators,
        "disambiguators_used": used_disambiguators,
    }
    overlay["screening_coverage"] = {
        **(overlay.get("screening_coverage") or {}),
        "queries": [queries_by_entity.get(str(draft.get("entity_key")), "")],
        "source_evidence_ids": [source_ids[str(reference)] for reference in refs],
        "limitations": (overlay.get("screening_coverage") or {}).get("limitations", []),
    }
    _validate_overlay(overlay, overlay_definition)
    finding = {
        key: draft.get(key)
        for key in ("title", "summary", "confidence", "severity", "potential_impact_risk", "recommended_action_rfi")
    }
    finding.update(
        {
            "finding_id": f"finding:adverse-news:{entity['key']}:{uuid4().hex}",
            "schema_version": "finding/v1",
            "category": "adverse_news",
            "assessment_id": (assessment or {}).get("assessment_id") or draft.get("assessment_id") or f"assessment:adverse-news:{uuid4().hex}",
            "subject": {"entity_id": entity.get("entity_id"), "entity_type": entity["entity_type"], "name": entity["name"]},
            "source": {"producer_type": "tool", "producer_name": "adverse_news_screening", "run_id": run_id, "created_at": datetime.now(UTC).isoformat()},
            "relevant_evidence_ids": [source_ids[str(reference)] for reference in refs],
            "adverse_news": overlay,
        }
    )
    _validate_adverse_news_consistency(finding)
    _validate_finding(finding)
    return finding


def _validate_finding(finding: dict[str, Any]) -> None:
    try:
        from jsonschema import Draft202012Validator

        errors = list(Draft202012Validator(load_finding_schema()).iter_errors(finding))
    except ImportError as exc:
        raise AdverseNewsError("jsonschema is required to validate CDD findings") from exc
    if errors:
        raise AdverseNewsError(f"Invalid finding/v1 record: {errors[0].message}")


def _validate_overlay(value: dict[str, Any], definition: dict[str, Any]) -> None:
    required = definition.get("required") or []
    if any(field not in value for field in required):
        raise AdverseNewsError("Adverse-news assessment returned an incomplete adverse_news/v1 overlay")
    for name, child in (definition.get("properties") or {}).items():
        if isinstance(value.get(name), dict) and isinstance(child, dict):
            _validate_overlay(value[name], child)


def _validate_adverse_news_consistency(finding: dict[str, Any]) -> None:
    """Enforce the identity-attribution floor for an adverse-news confidence rating."""
    adverse_news = finding.get("adverse_news") or {}
    identity_match = adverse_news.get("identity_match") or {}
    confidence = finding.get("confidence") or {}
    if confidence.get("level") != "high":
        return
    if identity_match.get("status") != "matched" or identity_match.get("confidence") != "high":
        raise AdverseNewsError(
            "High adverse-news finding confidence requires a matched identity with high identity-match confidence"
        )


def _document_requirement_artifacts(state: CDDState) -> list[dict[str, Any]]:
    """Materialize canonical document records for graph extraction."""
    artifacts = []
    for document in state.get("documents", []):
        if document.get("purpose") != "identity_verification":
            continue
        if document.get("status") not in {"located", "received", "processing"}:
            continue
        artifact = deepcopy(document.get("acquisition", {}).get("artifact") or {})
        if not artifact.get("pdf_path") and document.get("storage"):
            artifact = {
                "pdf_path": download_document_from_s3({
                    "url": document.get("url"), "storage": document.get("storage"),
                }),
                "s3_url": document.get("url"),
                "storage": document.get("storage"),
                "source": "S3 document cache",
                "source_type": document.get("source_type"),
                "provenance": document.get("provenance"),
                "synthetic": document.get("synthetic"),
            }
        if not artifact.get("pdf_path"):
            continue
        artifact.setdefault("document_type", document.get("document_type"))
        artifact.setdefault("person_name", (document.get("subject") or {}).get("name"))
        artifact.setdefault("case_common_id", (document.get("subject") or {}).get("case_common_id"))
        if not artifact.get("s3_url"):
            company_name, jurisdiction = _document_scope(state)
            document = upload_document_to_s3(
                artifact["pdf_path"],
                category=artifact.get("document_type") or "passport",
                person_name=artifact.get("person_name"),
                source=artifact.get("source"),
                source_type=artifact.get("source_type"),
                provenance=artifact.get("provenance"),
                synthetic=artifact.get("synthetic"),
                company_name=company_name,
                jurisdiction=jurisdiction,
                object_name=reusable_document_name(
                    document_type=artifact.get("document_type") or "passport",
                    company_name=company_name or "Company",
                    person_name=artifact.get("person_name"),
                ),
            )
            if document:
                artifact["s3_url"] = document["url"]
                artifact["storage"] = document["storage"]
        artifacts.append(artifact)
    return artifacts


def _cached_artifact(
    cached: dict[str, Any] | None, document_type: str, individual: dict[str, Any]
) -> dict[str, Any]:
    if not cached:
        return {}
    return {
        "name": cached.get("name"),
        "document_type": document_type,
        "person_name": individual.get("name"),
        "case_common_id": individual.get("case_common_id"),
        "source": "S3 document cache",
        "source_type": cached.get("source_type"),
        "provenance": cached.get("provenance"),
        "synthetic": cached.get("synthetic"),
        "s3_url": cached.get("url"),
        "storage": cached.get("storage"),
    }


def _document_record(
    *,
    document_id: str,
    purpose: str,
    document_type: str,
    subject: dict[str, Any],
    requirement: dict[str, Any],
    status: str,
    gap: dict[str, Any],
    artifact: dict[str, Any],
) -> dict[str, Any]:
    return {
        "document_id": document_id,
        "purpose": purpose,
        "document_type": document_type,
        "subject": _drop_empty(subject),
        "requirement": requirement,
        "status": status,
        "gap": gap,
        "acquisition": {"source": artifact.get("source"), "artifact": artifact} if artifact else {},
        "storage": artifact.get("storage") or {},
        "url": artifact.get("s3_url"),
        "name": artifact.get("name") or Path(str(artifact.get("pdf_path") or "")).name or None,
        "source": artifact.get("source"),
        "source_type": artifact.get("source_type"),
        "provenance": artifact.get("provenance"),
        "synthetic": artifact.get("synthetic"),
        "collected_at": artifact.get("generated_at"),
    }


def _idv_validation(document: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    extract = item.get("extract") or {}
    subject = document.get("subject") or {}
    accepted = (document.get("requirement") or {}).get("accepted_types") or []
    document_type = extract.get("document_type") or (item.get("classification") or {}).get("document_type")
    return {
        "accepted_type": document_type in accepted if accepted else True,
        "name_match": _normalise_name(extract.get("full_name") or "") == _normalise_name(subject.get("name") or ""),
        "expiry_date": extract.get("expiry_date"),
    }


def assess_csp_address(state: CDDState) -> dict[str, Any]:
    """Replace only previous canonical CSP records with a new CDD assessment."""
    records = build_csp_assessment(state)
    assessments = [item for item in state.get("assessments", []) if item.get("assessment_type") != "csp_address"] + records["assessments"]
    findings = [item for item in state.get("findings", []) if item.get("category") != "csp_address"] + records["findings"]
    return {"evidence": records["evidence"], "assessments": Overwrite(assessments), "findings": Overwrite(findings)}


def assess_cdd_completeness(state: CDDState) -> dict[str, Any]:
    """Run all SKILL-configured completeness checks and raise findings only for gaps."""
    evaluated_at = datetime.now(UTC).isoformat()
    run_id = f"run:cdd-completeness:{uuid4().hex}"
    try:
        result = evaluate_cdd_completeness(state)
        evidence_id = f"evidence:cdd-completeness:{uuid4().hex}"
        evidence = _evidence(
            tool="cdd_completeness",
            description="Evaluated configured CDD completeness checks",
            source="CDD Completeness",
            data={"checks": result["assessments"], "skill_path": result["definition"]["path"], "definition_version": result["definition"].get("definition_version")},
            relevance_tags=["cdd_completeness", "policy"],
        )
        evidence["evidence_id"] = evidence_id
        assessments, findings = [], []
        profile = ((state.get("cdd") or {}).get("company_business_profile") or {}).get("customer_static") or {}
        for check in result["assessments"]:
            assessment_id = f"assessment:cdd-completeness:{check['check_id']}:{uuid4().hex}"
            assessment = {
                "assessment_id": assessment_id,
                "assessment_type": "cdd_completeness",
                "schema_version": result["definition"]["assessment"]["schema"],
                "tool": "cdd_completeness",
                "run_id": run_id,
                "created_at": evaluated_at,
                "definition": {"skill_path": result["definition"]["path"], "definition_version": result["definition"].get("definition_version"), "check_id": check["check_id"], "display_order": check["display_order"]},
                **check,
                "source_evidence_ids": [evidence_id],
            }
            assessments.append(assessment)
            if check["outcome"] == "not_triggered":
                continue
            finding = {
                "finding_id": f"finding:cdd-completeness:{check['check_id']}:{uuid4().hex}",
                "schema_version": "finding/v1",
                "category": "cdd_completeness",
                "check_id": check["check_id"],
                "assessment_id": assessment_id,
                "title": check["title"],
                "summary": check["summary"],
                "subject": {"entity_id": str(profile.get("registration_number") or "") or None, "entity_type": "company", "name": profile.get("name") or "Customer"},
                "confidence": {"level": "high", "rationale": "Derived from retained CDD state.", "limitations": []},
                "severity": {"level": check["gap_severity"], "rationale": "Configured by the CDD Completeness skill."},
                "potential_impact_risk": "CDD may be incomplete until the identified gap is resolved.",
                "recommended_action_rfi": {"internal_actions": [check["action"]], "rfi": []},
                "source": {"producer_type": "tool", "producer_name": "cdd_completeness", "run_id": run_id, "created_at": evaluated_at},
                "relevant_evidence_ids": [evidence_id],
            }
            _validate_finding(finding)
            findings.append(finding)
        return {"evidence": [evidence], "assessments": assessments, "findings": findings}
    except CDDCompletenessError as exc:
        return {"evidence": [], "findings": [], "assessments": [{"assessment_id": f"assessment:cdd-completeness:{uuid4().hex}", "assessment_type": "cdd_completeness", "schema_version": "cdd_completeness_assessment/v1", "tool": "cdd_completeness", "run_id": run_id, "created_at": evaluated_at, "outcome": "unavailable", "summary": "CDD Completeness assessment could not be completed.", "limitations": [str(exc)]}]}


def assess_evidence_quality(state: CDDState) -> dict[str, Any]:
    """Evaluate SKILL-defined CDD claims against deterministically selected evidence."""
    evaluated_at = datetime.now(UTC).isoformat()
    run_id = f"run:evidence-quality:{uuid4().hex}"
    try:
        result = evaluate_evidence_quality(state)
        evidence_id = f"evidence:evidence-quality:{uuid4().hex}"
        evidence = _evidence(
            tool="evidence_quality",
            description="Evaluated configured CDD claims for source reliability, evidence sufficiency, consistency, and plausibility",
            source="Evidence Quality",
            data={"claims": result["assessments"], "skill_path": result["definition"]["path"], "definition_version": result["definition"].get("definition_version")},
            relevance_tags=["evidence_quality", "policy"],
        )
        evidence["evidence_id"] = evidence_id
        assessments, findings = [], []
        for check in result["assessments"]:
            assessment_id = f"assessment:evidence-quality:{check['claim_id']}:{uuid4().hex}"
            assessment = {
                "assessment_id": assessment_id,
                "assessment_type": "evidence_quality",
                "schema_version": result["definition"]["assessment"]["schema"],
                "tool": "evidence_quality",
                "run_id": run_id,
                "created_at": evaluated_at,
                "definition": {"skill_path": result["definition"]["path"], "definition_version": result["definition"].get("definition_version"), "claim_id": check["claim_id"], "display_order": check["display_order"], "cdd_section": check["cdd_section"], "dimensions": result["definition"]["dimensions"]},
                "source_evidence_ids": [evidence_id, *[item["evidence_id"] for item in check["selected_evidence"]]],
                **check,
            }
            assessments.append(assessment)
            if check["outcome"] in {"not_triggered", "not_applicable"}:
                continue
            subject = check["claim"]["subject"]
            relevant_ids = [evidence_id, *[item["evidence_id"] for item in check["selected_evidence"]]]
            finding = {
                "finding_id": f"finding:evidence-quality:{check['claim_id']}:{uuid4().hex}",
                "schema_version": "finding/v1",
                "category": "evidence_quality",
                "assessment_id": assessment_id,
                "title": check["title"],
                "summary": check["summary"],
                "subject": subject,
                "confidence": {"level": "high", "rationale": "Derived from the configured deterministic evidence selection rules.", "limitations": [dimension["rationale"] for dimension in check["dimensions"].values()]},
                "severity": {"level": check["severity"], "rationale": "Configured by the Evidence Quality skill."},
                "potential_impact_risk": "The CDD claim may not be sufficiently supported until the identified evidence-quality concern is resolved.",
                "recommended_action_rfi": {"internal_actions": [check["action"]], "rfi": []},
                "source": {"producer_type": "tool", "producer_name": "evidence_quality", "run_id": run_id, "created_at": evaluated_at},
                "relevant_evidence_ids": relevant_ids,
                "evidence_quality": {"claim_id": check["claim_id"], "cdd_section": check["cdd_section"], "dimensions": check["dimensions"], "excluded_evidence": check["excluded_evidence"]},
            }
            _validate_finding(finding)
            findings.append(finding)
        return {"evidence": [evidence], "assessments": assessments, "findings": findings}
    except EvidenceQualityError as exc:
        return {"evidence": [], "findings": [], "assessments": [{"assessment_id": f"assessment:evidence-quality:{uuid4().hex}", "assessment_type": "evidence_quality", "schema_version": "evidence_quality_assessment/v1", "tool": "evidence_quality", "run_id": run_id, "created_at": evaluated_at, "outcome": "unavailable", "summary": "Evidence Quality assessment could not be completed.", "limitations": [str(exc)]}]}


def assess_other_risk_factors(state: CDDState) -> dict[str, Any]:
    """Evaluate SKILL-defined other AML/CFT risk factors without duplicating upstream tools."""
    evaluated_at = datetime.now(UTC).isoformat()
    run_id = f"run:other-risk-factors:{uuid4().hex}"
    try:
        result = evaluate_other_risk_factors(state)
        evidence_id = f"evidence:other-risk-factors:{uuid4().hex}"
        evidence = _evidence(tool="other_risk_factors", description="Evaluated configured Other Risk Factors", source="Other Risk Factors", data={"factors": result["assessments"], "skill_path": result["definition"]["path"], "definition_version": result["definition"].get("definition_version")}, relevance_tags=["other_risk_factors", "policy"])
        evidence["evidence_id"] = evidence_id
        profile = (((state.get("cdd") or {}).get("company_business_profile") or {}).get("customer_static") or {})
        subject = {"entity_id": str(profile.get("registration_number") or "") or None, "entity_type": "company", "name": profile.get("name") or (state.get("metadata") or {}).get("customer", {}).get("name") or "Customer"}
        assessments, findings = [], []
        for factor in result["assessments"]:
            assessment_id = f"assessment:other-risk-factors:{factor['factor_id']}:{uuid4().hex}"
            assessment = {"assessment_id": assessment_id, "assessment_type": "other_risk_factors", "schema_version": result["definition"]["assessment"]["schema"], "tool": "other_risk_factors", "run_id": run_id, "created_at": evaluated_at, "definition": {"skill_path": result["definition"]["path"], "definition_version": result["definition"].get("definition_version"), "factor_id": factor["factor_id"], "cdd_section": factor["cdd_section"], "method": factor["method"], "display_order": factor["display_order"]}, "source_evidence_ids": [evidence_id, *[item["evidence_id"] for item in factor["selected_evidence"]]], "upstream_assessment_ids": factor["upstream_assessment_ids"], "upstream_finding_ids": factor["upstream_finding_ids"], **factor}
            assessments.append(assessment)
            if factor["outcome"] not in {"triggered", "inconclusive"}:
                continue
            finding = {"finding_id": f"finding:other-risk-factors:{factor['factor_id']}:{uuid4().hex}", "schema_version": "finding/v1", "category": "other_risk_factors", "assessment_id": assessment_id, "check_id": factor["factor_id"], "title": factor["title"], "summary": factor["summary"], "subject": subject, "confidence": {"level": "high", "rationale": "Derived from retained CDD records and the configured Other Risk Factors skill.", "limitations": ["This assessment does not replace entity-specific adverse-news or digital-footprint screening."]}, "severity": {"level": factor["severity"], "rationale": "Configured by the Other Risk Factors skill."}, "potential_impact_risk": "The identified factor may require further review or enhanced due diligence before a case decision.", "recommended_action_rfi": {"internal_actions": [factor["action"]], "rfi": []}, "source": {"producer_type": "tool", "producer_name": "other_risk_factors", "run_id": run_id, "created_at": evaluated_at}, "relevant_evidence_ids": assessment["source_evidence_ids"], "other_risk_factors": {"factor_id": factor["factor_id"], "cdd_section": factor["cdd_section"], "detail": factor["detail"], "upstream_assessment_ids": factor["upstream_assessment_ids"], "upstream_finding_ids": factor["upstream_finding_ids"]}}
            _validate_finding(finding)
            findings.append(finding)
        return {"evidence": [evidence], "assessments": assessments, "findings": findings}
    except OtherRiskFactorsError as exc:
        return {"evidence": [], "findings": [], "assessments": [{"assessment_id": f"assessment:other-risk-factors:{uuid4().hex}", "assessment_type": "other_risk_factors", "schema_version": "other_risk_factors_assessment/v1", "tool": "other_risk_factors", "run_id": run_id, "created_at": evaluated_at, "outcome": "unavailable", "summary": "Other Risk Factors assessment could not be completed.", "limitations": [str(exc)]}]}


def assess_shell_company_risk(state: CDDState) -> dict[str, Any]:
    """Assess configured shell-company indicators; CSP remains an upstream record."""
    evaluated_at = datetime.now(UTC).isoformat(); run_id = f"run:shell-company-risk:{uuid4().hex}"
    try:
        result = evaluate_shell_company_risk(state)
        evidence_id = f"evidence:shell-company-risk:{uuid4().hex}"
        evidence = _evidence(tool="shell_company_risk", description="Evaluated configured Shell Company Risk factors", source="Shell Company Risk", data={"factors": result["assessments"], "skill_path": result["definition"]["path"], "definition_version": result["definition"].get("definition_version")}, relevance_tags=["shell_company_risk", "policy"]); evidence["evidence_id"] = evidence_id
        profile = (((state.get("cdd") or {}).get("company_business_profile") or {}).get("customer_static") or {}); subject = {"entity_id": str(profile.get("registration_number") or "") or None, "entity_type": "company", "name": profile.get("name") or (state.get("metadata") or {}).get("customer", {}).get("name") or "Customer"}
        assessments, findings = [], []
        for factor in result["assessments"]:
            assessment_id = f"assessment:shell-company-risk:{factor['factor_id']}:{uuid4().hex}"
            record = {"assessment_id": assessment_id, "assessment_type": "shell_company_risk", "schema_version": result["definition"]["assessment"]["schema"], "tool": "shell_company_risk", "run_id": run_id, "created_at": evaluated_at, "definition": {"skill_path": result["definition"]["path"], "definition_version": result["definition"].get("definition_version"), "factor_id": factor["factor_id"], "cdd_section": factor["cdd_section"], "method": factor["method"], "display_order": factor["display_order"]}, "source_evidence_ids": [evidence_id, *[item["evidence_id"] for item in factor["selected_evidence"]]], **factor}
            assessments.append(record)
            if factor["outcome"] not in {"triggered", "inconclusive"}: continue
            finding = {"finding_id": f"finding:shell-company-risk:{factor['factor_id']}:{uuid4().hex}", "schema_version": "finding/v1", "category": "shell_company_risk", "assessment_id": assessment_id, "check_id": factor["factor_id"], "title": factor["title"], "summary": factor["summary"], "subject": subject, "confidence": {"level": "medium", "rationale": "Derived from retained CDD facts and the configured Shell Company Risk skill.", "limitations": ["This is an indicator assessment, not a shell-company determination."]}, "severity": {"level": factor["severity"], "rationale": "Configured by the Shell Company Risk skill."}, "potential_impact_risk": "The identified indicator may require further review or enhanced due diligence before a case decision.", "recommended_action_rfi": {"internal_actions": [factor["action"]], "rfi": []}, "source": {"producer_type": "tool", "producer_name": "shell_company_risk", "run_id": run_id, "created_at": evaluated_at}, "relevant_evidence_ids": record["source_evidence_ids"], "shell_company_risk": {"factor_id": factor["factor_id"], "cdd_section": factor["cdd_section"], "detail": factor["detail"]}}
            _validate_finding(finding); findings.append(finding)
        return {"evidence": [evidence], "assessments": assessments, "findings": findings}
    except ShellCompanyRiskError as exc:
        return {"evidence": [], "findings": [], "assessments": [{"assessment_id": f"assessment:shell-company-risk:{uuid4().hex}", "assessment_type": "shell_company_risk", "schema_version": "shell_company_risk_assessment/v1", "tool": "shell_company_risk", "run_id": run_id, "created_at": evaluated_at, "outcome": "unavailable", "summary": "Shell Company Risk assessment could not be completed.", "limitations": [str(exc)]}]}


def assess_risk_rating(state: CDDState) -> dict[str, Any]:
    """Create the top-level risk-rating assessment without producing another finding."""
    evaluated_at = datetime.now(UTC).isoformat(); run_id = f"run:risk-rating:{uuid4().hex}"
    try:
        result = evaluate_risk_rating(state); assessment_id = f"assessment:risk-rating:{uuid4().hex}"
        evidence_ids = [item["evidence_id"] for item in result["inputs"]["evidence"]]
        assessment = {"assessment_id": assessment_id, "assessment_type": "risk_rating", "schema_version": result["definition"]["assessment"]["schema"], "tool": "risk_rating", "run_id": run_id, "created_at": evaluated_at, "definition": {"skill_path": result["definition"]["path"], "definition_version": result["definition"].get("definition_version"), "ratings": result["definition"]["ratings"], "factor_scores": result["definition"]["factor_scores"], "thresholds": result["definition"]["thresholds"]}, "rating": result["result"]["rating"], "total_score": result["result"]["total_score"], "contributing_factors": result["result"]["contributing_factors"], "summary": result["result"]["rationale"], "rationale": result["result"]["rationale"], "rule_explanation": result["result"]["rule_explanation"], "matched_criteria": result["result"]["matched_criteria"], "limitations": result["result"]["limitations"], "monitoring_posture": result["result"]["monitoring_posture"], "selected_finding_ids": [item["finding_id"] for item in result["inputs"]["findings"]], "selected_assessment_ids": [item["assessment_id"] for item in result["inputs"]["assessments"]], "selected_evidence_ids": evidence_ids, "source_evidence_ids": evidence_ids, "provenance": {"method": "deterministic_rule_based"}}
        return {"assessments": [assessment], "findings": [], "evidence": []}
    except RiskRatingError as exc:
        return {"assessments": [{"assessment_id": f"assessment:risk-rating:{uuid4().hex}", "assessment_type": "risk_rating", "schema_version": "risk_rating_assessment/v1", "tool": "risk_rating", "run_id": run_id, "created_at": evaluated_at, "rating": "inconclusive", "summary": "Risk Rating assessment could not be completed.", "limitations": [str(exc)], "selected_finding_ids": [], "selected_assessment_ids": [], "selected_evidence_ids": []}], "findings": [], "evidence": []}


def finalize_cdd(state: CDDState) -> dict[str, Any]:
    """Record the completion time after every CDD assessment and reviewer brief is built."""
    cdd = deepcopy(state.get("cdd", {}))
    cdd["completed_at"] = datetime.now(UTC).isoformat()
    return {"cdd": cdd}


def generate_case_review(state: CDDState) -> dict[str, Any]:
    """Create a reviewer brief from completed CDD data without changing its outcome."""
    try:
        summary = generate_case_review_summary(
            cdd=state.get("cdd", {}),
            case_status=state.get("case_status", {}),
            findings=state.get("findings", []),
            evidence=state.get("evidence", []),
        )
    except CaseReviewError as exc:
        summary = unavailable_case_review(str(exc))
    return {
        "case_assessment_summary": summary,
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


def _cache_subject_from_state(state: CDDState) -> CacheSubject | None:
    customer = state.get("metadata", {}).get("customer", {})
    kyc_case = state.get("metadata", {}).get("kyc_case", {})
    name = customer.get("name")
    jurisdiction = customer.get("jurisdiction")
    selected_match = kyc_case.get("selected_registry_match") or {}
    resolved_name = selected_match.get("rawname") or name
    if not isinstance(resolved_name, str) or not isinstance(jurisdiction, str):
        return None
    return company_cache_subject(jurisdiction, resolved_name)


def _evidence(
    *,
    tool: str,
    description: str,
    data: dict[str, Any],
    relevance_tags: list[str],
    source: str = "KYC API",
) -> dict[str, Any]:
    return {
        "evidence_id": f"evidence:{uuid4().hex}",
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
        "name": document.get("name"),
        "document_type": document_type,
        "source": source,
        "source_type": document.get("source_type"),
        "provenance": document.get("provenance"),
        "synthetic": document.get("synthetic"),
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
        accepted_types = individual.get("required_documents") or []
        type_valid = not accepted_types or extract.get("document_type") in accepted_types
        name_valid = _normalise_name(extract.get("full_name") or "") == _normalise_name(individual.get("name") or "")
        individual["status"] = "verified" if type_valid and name_valid else "invalid"


def _identity_key(row: dict[str, Any]) -> tuple[str, str]:
    case_common_id = row.get("case_common_id")
    if case_common_id not in (None, ""):
        return ("id", str(case_common_id))
    return ("name", " ".join(str(row.get("name") or "").casefold().split()))


def _normalise_name(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _drop_empty(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if value not in (None, "", [], {})}


def _section_status(data: dict[str, Any], *, required: tuple[str, ...]) -> str:
    return "complete" if not _missing(data, required) else "incomplete"


def _missing(data: dict[str, Any], required: tuple[str, ...]) -> list[str]:
    return [field for field in required if data.get(field) in (None, "", [], {})]
