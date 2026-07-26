"""FastAPI app that exposes the CDD LangGraph as a chatbot backend."""

from __future__ import annotations

import asyncio
from copy import deepcopy
import json
import os
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from src.agents.chat_graph import run_chat_graph
from src.agents.graph import PIPELINE_NODE_LABELS, resume_cdd_agent_state, run_cdd_agent_state
from src.agents.nodes import adverse_news_screening, assess_cdd_completeness, assess_evidence_quality, assess_other_risk_factors, digital_footprint_assessment
from src.agents.state import new_cdd_state
from src.agents.qa import answer_cdd_question
from src.tools.case_finder import find_test_cases
from src.tools.case_review import CaseReviewError, generate_case_review_summary, merge_case_review_assessments, unavailable_case_review
from src.tools.csp_detector import CSPAssessmentError, evaluate_csp_address, load_csp_skill
from src.tools.digital_footprint import load_digital_footprint_skill
from src.tools.customer_static import get_customer_static_by_name
from src.tools.document_extraction import classify_document, extract_document
from src.tools.members import get_company_members_by_name
from src.tools.orgchart import get_company_org_chart_by_name
from src.utils.kyc_cache import get_cache_value
from src.utils.pdf import render_cdd_pdf
from src.utils.idv_document_pipeline import generate_idv_document
from src.utils.case_status import sync_case_status
from src.utils.s3_documents import (
    download_document_from_s3,
    find_documents_in_s3,
    presign_document_url,
    reusable_document_name,
    upload_document_to_s3,
)


load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIR = PROJECT_ROOT / "src" / "frontend"
OUTPUT_DIR = PROJECT_ROOT / "outputs"
DOCUMENT_STAGING_DIR = OUTPUT_DIR / "document-staging"
DOCUMENT_EXTRACTION_STAGING_DIR = OUTPUT_DIR / "document-extraction-staging"
STANDALONE_IDV_DOCUMENT_DIR = OUTPUT_DIR / "standalone-idv-documents"
STANDALONE_DOCUMENT_CONTENT_TYPES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/gif",
}
SANDBOX_CASES_PATH = PROJECT_ROOT / "registry_list_of_mock_cases" / "kyc-sandbox-test-cases.json"
DEMO_CASE_PATH = PROJECT_ROOT / "demo_data" / "case_review_demo.json"

app = FastAPI(title="WBL Bank CDD Chatbot")
SESSIONS: dict[str, dict[str, Any]] = {}
STANDALONE_IDV_DOCUMENTS: dict[str, dict[str, Path]] = {}


class ChatRequest(BaseModel):
    message: str = Field(default="")
    session_id: str | None = None
    customer_name: str | None = None
    jurisdiction: str | None = None
    case_id: str | None = None
    generate_pdf: bool = False


class PdfRequest(BaseModel):
    session_id: str


class PipelineRequest(BaseModel):
    session_id: str | None = None
    customer_name: str
    jurisdiction: str
    account_location: Literal["SG", "HK", "GB"]
    case_id: str | None = None
    generate_pdf: bool = False


class DocumentPresignRequest(BaseModel):
    session_id: str
    document_key: str


class DocumentActionRequest(BaseModel):
    session_id: str
    requirement_ids: list[str] | None = None


class CSPAssessmentRequest(BaseModel):
    company_name: str | None = Field(default=None)
    registered_address: str = Field(min_length=1)


class DigitalFootprintRequest(BaseModel):
    company_name: str = Field(min_length=1, max_length=250)
    jurisdiction: str | None = Field(default=None, max_length=80)
    registration_number: str | None = Field(default=None, max_length=120)
    known_domain: str | None = Field(default=None, max_length=250)
    registered_address: str | None = Field(default=None, max_length=500)


class DigitalFootprintAttachRequest(BaseModel):
    session_id: str
    result: dict[str, Any]


class IndependentAdverseNewsRequest(BaseModel):
    entity_names: list[str] = Field(min_length=1, max_length=25)


class StandaloneIDVDocumentRequest(BaseModel):
    full_name: str = Field(min_length=1, max_length=150)
    document_type: Literal["passport", "national_id"]
    nationality: str | None = Field(default=None, max_length=80)
    issuing_country: str | None = Field(default=None, max_length=80)
    address: str | None = Field(default=None, max_length=300)
    case_common_id: str | None = Field(default=None, max_length=100)


class CaseReviewDecisionRequest(BaseModel):
    session_id: str
    decision: Literal["approve", "request_information", "escalate"]
    note: str = Field(default="", max_length=4_000)


class CaseReviewRefreshRequest(BaseModel):
    session_id: str


class CDDCompletenessRequest(BaseModel):
    session_id: str


class EvidenceQualityRequest(BaseModel):
    session_id: str


class OtherRiskFactorsRequest(BaseModel):
    session_id: str


class DemoLoadRequest(BaseModel):
    session_id: str | None = None


@app.post("/api/chat")
async def chat(
    request: ChatRequest,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    session = _session(request.session_id)
    if _demo_mode_enabled():
        if request.message:
            session["messages"].append({"role": "user", "content": request.message})
        session["messages"].append(
            {
                "role": "assistant",
                "content": "Demo Mode does not call external services. Load the demo case to explore the fixture-backed CDD and Case Assessment workflow.",
            }
        )
        return _response(session, status="demo_read_only")
    if request.message:
        session["messages"].append({"role": "user", "content": request.message})

    try:
        result = await asyncio.to_thread(
            run_chat_graph,
            session=session,
            user_message=request.message,
            generate_pdf=request.generate_pdf,
        )
        session.clear()
        session.update(result["session"])
        return _response(
            session,
            status=result.get("status", "answered"),
            error=result.get("error"),
        )
    except Exception as exc:
        content = f"Request failed: {exc}"
        session["messages"].append({"role": "assistant", "content": content})
        return _response(session, status="error", error=str(exc))


@app.get("/api/csp/skill")
async def get_csp_skill() -> dict[str, str]:
    """Return the current CSP assessment skill without reading session state."""
    return {"skill": load_csp_skill()}


@app.get("/api/digital-footprint/skill")
async def get_digital_footprint_skill() -> dict[str, str]:
    """Return the standalone digital-footprint skill without session state."""
    return {"skill": load_digital_footprint_skill()}


@app.get("/api/demo/status")
async def demo_status() -> dict[str, bool]:
    """Tell the frontend whether fixture-backed Demo Mode is enabled."""
    return {"demo_mode": _demo_mode_enabled()}


@app.post("/api/demo/load")
async def load_demo_case(request: DemoLoadRequest) -> dict[str, Any]:
    if not _demo_mode_enabled():
        raise HTTPException(status_code=404, detail="Demo Mode is disabled")
    return _load_demo_case(_session(request.session_id))


@app.post("/api/csp/assess")
async def assess_csp(request: CSPAssessmentRequest) -> dict[str, Any]:
    """Run an isolated CSP assessment that does not change an active CDD case."""
    if _demo_mode_enabled():
        raise HTTPException(status_code=400, detail="CSP assessment is disabled in Demo Mode; load the demo case to inspect fixture evidence.")
    try:
        return await asyncio.to_thread(
            evaluate_csp_address,
            request.registered_address,
            company_name=request.company_name,
        )
    except CSPAssessmentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/digital-footprint/assess")
async def assess_digital_footprint(request: DigitalFootprintRequest) -> dict[str, Any]:
    """Run standalone footprint research without reading or writing CDD session state."""
    if _demo_mode_enabled():
        raise HTTPException(status_code=400, detail="Digital-footprint assessment is disabled in Demo Mode.")
    try:
        return await asyncio.to_thread(digital_footprint_assessment, {"digital_footprint_inputs": request.model_dump()})
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/adverse-news/assess")
async def assess_independent_adverse_news(request: IndependentAdverseNewsRequest) -> dict[str, Any]:
    """Run adverse-news screening without reading or changing an active CDD session."""
    names = list(dict.fromkeys(name.strip() for name in request.entity_names if name.strip()))
    if not names:
        raise HTTPException(status_code=400, detail="Provide at least one entity name")
    state = {
        "cdd": {
            "company_business_profile": {"customer_static": {}},
            "ownership_and_control": {"members": {"controlling_members": []}, "ubos": [{"name": name} for name in names]},
        }
    }
    try:
        return await asyncio.to_thread(adverse_news_screening, state)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Independent adverse-news screening failed: {exc}") from exc


@app.post("/api/digital-footprint/attach")
async def attach_digital_footprint(request: DigitalFootprintAttachRequest) -> dict[str, Any]:
    """Explicitly attach a client-held standalone result as CDD evidence."""
    session = SESSIONS.get(request.session_id)
    state = _active_cdd_state(session)
    if not state or not state.get("cdd"):
        raise HTTPException(status_code=404, detail="No active CDD result for this session")
    if session.get("demo_mode"):
        raise HTTPException(status_code=400, detail="Digital-footprint attachment is disabled in Demo Mode.")
    result = request.result or {}
    _append_cdd_records(state, "evidence", result.get("evidence") or [], "evidence_id")
    _append_cdd_records(state, "assessments", result.get("assessments") or [], "assessment_id")
    _append_cdd_records(state, "findings", result.get("findings") or [], "finding_id")
    return _response(session, status="digital_footprint_attached")


@app.post("/api/document-extraction/extract")
async def extract_standalone_document(file: UploadFile = File(...)) -> dict[str, Any]:
    """Extract a PDF or image without reading from or writing to a CDD session."""
    if _demo_mode_enabled():
        raise HTTPException(
            status_code=400,
            detail="Document extraction is disabled in Demo Mode.",
        )
    if file.content_type not in STANDALONE_DOCUMENT_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Supported document formats are PDF, PNG, JPEG, WEBP, and GIF",
        )

    data = await file.read()
    if not data or len(data) > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Upload must be a document no larger than 20 MB")
    if not _is_supported_document_content(data, file.content_type):
        raise HTTPException(status_code=400, detail="Uploaded file does not match its declared document type")

    DOCUMENT_EXTRACTION_STAGING_DIR.mkdir(parents=True, exist_ok=True)
    suffix = {
        "application/pdf": ".pdf",
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }[file.content_type]
    path = DOCUMENT_EXTRACTION_STAGING_DIR / f"{uuid.uuid4()}-document{suffix}"
    path.write_bytes(data)
    artifact = {"pdf_path": str(path), "source": "Standalone document extraction"}
    try:
        classification = await asyncio.to_thread(classify_document, path)
        extraction = await asyncio.to_thread(
            extract_document,
            artifact,
            classification=classification,
        )
        return {"classification": classification, "extraction": extraction}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Document extraction failed: {exc}") from exc
    finally:
        path.unlink(missing_ok=True)


@app.post("/api/idv-document-generation/generate")
async def generate_standalone_idv_document(
    request: StandaloneIDVDocumentRequest,
) -> dict[str, Any]:
    """Generate a synthetic ID&V document without accessing a CDD session."""
    if _demo_mode_enabled():
        raise HTTPException(status_code=400, detail="ID&V document generation is disabled in Demo Mode.")

    individual = {
        "name": request.full_name.strip(),
        "selected_document_type": request.document_type,
        "nationality": _optional_text(request.nationality),
        "issuing_country": _optional_text(request.issuing_country),
        "address": _optional_text(request.address),
        "case_common_id": _optional_text(request.case_common_id),
    }
    if not individual["name"]:
        raise HTTPException(status_code=400, detail="Full name is required")

    try:
        artifact = await asyncio.to_thread(
            generate_idv_document,
            individual,
            output_dir=STANDALONE_IDV_DOCUMENT_DIR,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"ID&V document generation failed: {exc}") from exc

    pdf_path = Path(artifact["pdf_path"])
    if not pdf_path.exists():
        raise HTTPException(status_code=500, detail="Generated PDF is missing")
    artifact_id = str(uuid.uuid4())
    STANDALONE_IDV_DOCUMENTS[artifact_id] = {
        key: Path(artifact[key])
        for key in ("pdf_path", "html_path", "json_path")
        if artifact.get(key)
    }
    return {
        "artifact_id": artifact_id,
        "document_type": artifact["document_type"],
        "person_name": artifact["person_name"],
        "generated_at": artifact["generated_at"],
        "pdf_url": f"/api/idv-document-generation/{artifact_id}/pdf",
        "notice": "Synthetic demo document — not valid for identity verification.",
    }


@app.get("/api/idv-document-generation/{artifact_id}/pdf")
async def download_standalone_idv_document(artifact_id: str) -> FileResponse:
    """Return a generated synthetic PDF using its opaque artifact identifier."""
    artifact = STANDALONE_IDV_DOCUMENTS.get(artifact_id)
    pdf_path = artifact.get("pdf_path") if artifact else None
    if not pdf_path or not pdf_path.exists():
        raise HTTPException(status_code=404, detail="Generated document not found")
    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename=pdf_path.name,
        background=BackgroundTask(_delete_standalone_idv_artifact, artifact_id),
    )


@app.post("/api/case-review/refresh")
async def refresh_case_review(request: CaseReviewRefreshRequest) -> dict[str, Any]:
    session = SESSIONS.get(request.session_id)
    state = _active_cdd_state(session)
    if not state or not state.get("cdd"):
        raise HTTPException(status_code=404, detail="No CDD result for this session")
    if session.get("demo_mode"):
        return _response(session, status="demo_read_only")
    try:
        summary = await asyncio.to_thread(
            generate_case_review_summary,
            cdd=state["cdd"],
            case_status=state.get("case_status", {}),
            risk_flags=state.get("risk_flags", []),
            evidence=state.get("evidence", []),
        )
    except CaseReviewError as exc:
        summary = unavailable_case_review(str(exc))
    state["case_assessment_summary"] = summary
    state["risk_flags"] = merge_case_review_assessments(state.get("risk_flags", []), summary)
    sync_case_status(state)
    return _response(session, status="case_review_refreshed")


@app.post("/api/cdd-completeness/run")
async def run_cdd_completeness(request: CDDCompletenessRequest) -> dict[str, Any]:
    """Run Checker completeness checks against the already-retained CDD state."""
    session = SESSIONS.get(request.session_id)
    state = _active_cdd_state(session)
    if not state or not state.get("cdd"):
        raise HTTPException(status_code=404, detail="No CDD result for this session")
    if session.get("demo_mode"):
        return _response(session, status="demo_read_only")
    result = await asyncio.to_thread(assess_cdd_completeness, state)
    prior_assessment_ids = {
        item.get("assessment_id") for item in state.get("assessments", [])
        if item.get("assessment_type") == "cdd_completeness"
    }
    state["assessments"] = [item for item in state.get("assessments", []) if item.get("assessment_type") != "cdd_completeness"]
    state["findings"] = [item for item in state.get("findings", []) if item.get("assessment_id") not in prior_assessment_ids]
    _append_cdd_records(state, "evidence", result.get("evidence") or [], "evidence_id")
    _append_cdd_records(state, "assessments", result.get("assessments") or [], "assessment_id")
    _append_cdd_records(state, "findings", result.get("findings") or [], "finding_id")
    sync_case_status(state)
    return _response(session, status="cdd_completeness_completed")


@app.post("/api/evidence-quality/run")
async def run_evidence_quality(request: EvidenceQualityRequest) -> dict[str, Any]:
    """Run Checker evidence-quality checks against retained CDD state."""
    session = SESSIONS.get(request.session_id)
    state = _active_cdd_state(session)
    if not state or not state.get("cdd"):
        raise HTTPException(status_code=404, detail="No CDD result for this session")
    if session.get("demo_mode"):
        return _response(session, status="demo_read_only")
    result = await asyncio.to_thread(assess_evidence_quality, state)
    prior_ids = {item.get("assessment_id") for item in state.get("assessments", []) if item.get("assessment_type") == "evidence_quality"}
    state["assessments"] = [item for item in state.get("assessments", []) if item.get("assessment_type") != "evidence_quality"]
    state["findings"] = [item for item in state.get("findings", []) if item.get("assessment_id") not in prior_ids]
    _append_cdd_records(state, "evidence", result.get("evidence") or [], "evidence_id")
    _append_cdd_records(state, "assessments", result.get("assessments") or [], "assessment_id")
    _append_cdd_records(state, "findings", result.get("findings") or [], "finding_id")
    sync_case_status(state)
    return _response(session, status="evidence_quality_completed")


@app.post("/api/other-risk-factors/run")
async def run_other_risk_factors(request: OtherRiskFactorsRequest) -> dict[str, Any]:
    """Run Other Risk Factors checks against the retained CDD state."""
    session = SESSIONS.get(request.session_id)
    state = _active_cdd_state(session)
    if not state or not state.get("cdd"):
        raise HTTPException(status_code=404, detail="No CDD result for this session")
    if session.get("demo_mode"):
        return _response(session, status="demo_read_only")
    result = await asyncio.to_thread(assess_other_risk_factors, state)
    prior_ids = {item.get("assessment_id") for item in state.get("assessments", []) if item.get("assessment_type") == "other_risk_factors"}
    state["assessments"] = [item for item in state.get("assessments", []) if item.get("assessment_type") != "other_risk_factors"]
    state["findings"] = [item for item in state.get("findings", []) if item.get("assessment_id") not in prior_ids]
    _append_cdd_records(state, "evidence", result.get("evidence") or [], "evidence_id")
    _append_cdd_records(state, "assessments", result.get("assessments") or [], "assessment_id")
    _append_cdd_records(state, "findings", result.get("findings") or [], "finding_id")
    sync_case_status(state)
    return _response(session, status="other_risk_factors_completed")


@app.post("/api/case-review/decision")
async def record_case_review_decision(request: CaseReviewDecisionRequest) -> dict[str, Any]:
    session = SESSIONS.get(request.session_id)
    if not _active_cdd_state(session):
        raise HTTPException(status_code=404, detail="No CDD result for this session")
    session["case_review_decision"] = {
        "decision": request.decision,
        "note": request.note.strip(),
        "recorded_at": datetime.now(UTC).isoformat(),
    }
    return _response(session, status="case_review_decision_recorded")


@app.post("/api/pipeline/run")
async def run_pipeline(
    request: PipelineRequest,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    session = _session(request.session_id)
    if _demo_mode_enabled():
        return _load_demo_case(session)
    return await _run_pipeline_for_session(
        session,
        customer_name=request.customer_name,
        jurisdiction=request.jurisdiction,
        account_location=request.account_location,
        case_id=request.case_id,
        generate_pdf=request.generate_pdf,
        background_tasks=background_tasks,
    )


@app.post("/api/pdf")
async def generate_pdf(request: PdfRequest) -> dict[str, Any]:
    session = SESSIONS.get(request.session_id)
    state = _active_cdd_state(session)
    if not state or not state.get("cdd"):
        raise HTTPException(status_code=404, detail="No CDD result for this session")

    pdf_path = render_cdd_pdf(state["cdd"])
    session["pdf_path"] = str(pdf_path)
    return {"pdf_url": f"/api/pdf/{request.session_id}"}


@app.get("/api/pdf/{session_id}")
async def download_pdf(session_id: str) -> FileResponse:
    session = SESSIONS.get(session_id)
    if not session or not session.get("pdf_path"):
        raise HTTPException(status_code=404, detail="PDF not found")

    pdf_path = Path(session["pdf_path"])
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF file missing")
    return FileResponse(pdf_path, media_type="application/pdf", filename=pdf_path.name)


@app.get("/api/session/{session_id}")
async def get_session(session_id: str) -> dict[str, Any]:
    session = SESSIONS.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return _response(
        session,
        status=session.get("pipeline_status") or "ok",
        error=session.get("pipeline_error"),
    )


@app.post("/api/documents/presign")
async def presign_document(request: DocumentPresignRequest) -> dict[str, Any]:
    session = SESSIONS.get(request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    document = _session_document_by_key(session, request.document_key)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found in session")

    storage = document.get("storage") or {}
    bucket = storage.get("bucket")
    key = storage.get("key")
    if not bucket or not key:
        raise HTTPException(status_code=400, detail="Document is missing S3 storage metadata")

    expires_in_seconds = 15 * 60
    expires_at = datetime.now(UTC) + timedelta(seconds=expires_in_seconds)
    url = presign_document_url(
        bucket=bucket,
        key=key,
        expires_in_seconds=expires_in_seconds,
    )
    return {
        "document_key": key,
        "url": url,
        "expires_at": expires_at.isoformat(),
        "expires_in_seconds": expires_in_seconds,
    }


@app.post("/api/documents/upload")
async def upload_case_document(
    session_id: str = Form(...),
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """Stage an officer-provided PDF and intelligently match it to a requirement."""
    session = SESSIONS.get(session_id)
    state = _active_cdd_state(session)
    if not state or not _open_document_requirements(state):
        raise HTTPException(status_code=404, detail="Document requirements not found")
    if session.get("demo_mode"):
        return _response(session, status="demo_read_only")
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Only PDF uploads are supported")

    data = await file.read()
    if not data or len(data) > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Upload must be a PDF no larger than 20 MB")
    staging = DOCUMENT_STAGING_DIR / session_id
    staging.mkdir(parents=True, exist_ok=True)
    path = staging / f"{uuid.uuid4()}-{_safe_file_name(file.filename or 'document.pdf')}"
    path.write_bytes(data)
    artifact = {"pdf_path": str(path), "source": "Provided by customer"}
    try:
        classification = await asyncio.to_thread(classify_document, path)
        preview = await asyncio.to_thread(extract_document, artifact, classification=classification)
    except Exception as exc:
        path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Unable to identify document: {exc}") from exc

    requirement = _match_requirement(_open_document_requirements(state), classification, preview)
    if not requirement:
        path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail="No open document requirement matched this upload")
    requirement.update({
        "status": "received",
        "gap": {"status": "resolved", "reason": ""},
        "acquisition": {
            "source": "customer_upload",
            "artifact": {**artifact, "document_type": classification.get("document_type")},
        },
        "processing": {"classification": classification, "match": _match_summary(requirement, classification, preview)},
    })
    try:
        await _resume_if_ready(session)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Document was received, but processing could not continue: {session.get('pipeline_error') or exc}",
        ) from exc
    return _response(session, status=session.get("pipeline_status", "awaiting_documents"))


@app.post("/api/documents/generate")
async def generate_missing_documents(request: DocumentActionRequest) -> dict[str, Any]:
    """Generate selected unavailable documents locally; processing is still explicit."""
    session = SESSIONS.get(request.session_id)
    state = _active_cdd_state(session)
    if not state or not _open_document_requirements(state):
        raise HTTPException(status_code=404, detail="Document requirements not found")
    if session.get("demo_mode"):
        return _response(session, status="demo_read_only")
    selected = set(request.requirement_ids or [])
    for requirement in _open_document_requirements(state):
        if selected and requirement["document_id"] not in selected:
            continue
        if requirement.get("status") != "required":
            continue
        try:
            artifact = await asyncio.to_thread(
                generate_idv_document,
                {
                    **(requirement.get("subject") or {}),
                    "selected_document_type": requirement["document_type"],
                },
                output_dir=DOCUMENT_STAGING_DIR / request.session_id,
            )
        except Exception as exc:
            subject_name = (requirement.get("subject") or {}).get("name") or "the required individual"
            raise HTTPException(
                status_code=400,
                detail=f"Unable to generate {requirement['document_type']} for {subject_name}: {exc}",
            ) from exc
        requirement.update({
            "status": "received",
            "gap": {"status": "resolved", "reason": ""},
            "acquisition": {"source": "generated", "artifact": artifact},
        })
    try:
        await _resume_if_ready(session)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Document was generated, but processing could not continue: {session.get('pipeline_error') or exc}",
        ) from exc
    return _response(session, status=session.get("pipeline_status", "awaiting_documents"))


@app.post("/api/documents/process")
async def process_case_documents(request: DocumentActionRequest) -> dict[str, Any]:
    session = SESSIONS.get(request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="CDD session not found")
    if session.get("demo_mode"):
        return _response(session, status="demo_read_only")
    try:
        await _resume_if_ready(session)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Document processing could not continue: {session.get('pipeline_error') or exc}",
        ) from exc
    return _response(session, status=session.get("pipeline_status", "awaiting_documents"))


@app.get("/api/jurisdictions")
async def get_jurisdictions() -> dict[str, Any]:
    with SANDBOX_CASES_PATH.open(encoding="utf-8") as fh:
        cases = json.load(fh)

    jurisdictions = sorted(
        {
            str(case.get("jurisdiction")).strip().upper()
            for case in cases
            if isinstance(case, dict) and case.get("jurisdiction")
        }
    )
    return {"jurisdictions": jurisdictions}


def _session(session_id: str | None) -> dict[str, Any]:
    if session_id and session_id in SESSIONS:
        return SESSIONS[session_id]

    session_id = session_id or str(uuid.uuid4())
    session = {
        "session_id": session_id,
        "case_status": {"cdd_generation": "not_started"},
        "messages": [
            {
                "role": "assistant",
                "content": "Which company would you like to onboard?",
            }
        ],
    }
    SESSIONS[session_id] = session
    return session


def _clear_previous_cdd_run(session: dict[str, Any]) -> None:
    """Remove case-specific artefacts before accepting a new CDD run.

    Standalone Tools-menu results intentionally remain in the session.  Everything
    returned by the CDD workspace is reset so a new ``running`` response cannot
    expose data or links from the preceding case.
    """
    for key in (
        "graph_state",
        "graph_thread_id",
        "document_results",
        "case_review_summary",
        "case_review_decision",
        "pdf_path",
        "pipeline_error",
    ):
        session.pop(key, None)
    session["messages"] = [
        {"role": "assistant", "content": "Which company would you like to onboard?"}
    ]


def _demo_mode_enabled() -> bool:
    return os.getenv("DEMO_MODE", "").strip().casefold() in {"1", "true", "yes", "on"}


def _optional_text(value: str | None) -> str | None:
    return value.strip() or None if value else None


def _delete_standalone_idv_artifact(artifact_id: str) -> None:
    """Remove one-time synthetic document artifacts after their PDF is sent."""
    artifact = STANDALONE_IDV_DOCUMENTS.pop(artifact_id, None)
    if artifact:
        for path in artifact.values():
            path.unlink(missing_ok=True)


def _is_supported_document_content(data: bytes, content_type: str) -> bool:
    """Verify the upload signature before sending a document to the model."""
    signatures = {
        "application/pdf": lambda value: value.lstrip().startswith(b"%PDF-"),
        "image/png": lambda value: value.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/jpeg": lambda value: value.startswith(b"\xff\xd8\xff"),
        "image/webp": lambda value: value.startswith(b"RIFF") and value[8:12] == b"WEBP",
        "image/gif": lambda value: value.startswith((b"GIF87a", b"GIF89a")),
    }
    validator = signatures.get(content_type)
    return bool(validator and validator(data))


def _load_demo_case(session: dict[str, Any]) -> dict[str, Any]:
    """Populate a normal session with static data and never call external services."""
    try:
        fixture = json.loads(DEMO_CASE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"Demo fixture could not be loaded: {exc}") from exc
    session_id = session["session_id"]
    session.clear()
    session.update(deepcopy(fixture))
    session["graph_state"] = {
        key: session.pop(key)
        for key in (
            "cdd", "documents", "evidence", "findings", "assessments", "risk_flags",
            "case_status", "case_assessment_summary",
        )
        if key in session
    }
    legacy_requirements = session.pop("document_requirements", [])
    if legacy_requirements:
        state = session["graph_state"]
        state.setdefault("documents", []).extend(_migrate_legacy_document_requirements(legacy_requirements))
    session["session_id"] = session_id
    session["demo_mode"] = True
    state = session.get("graph_state")
    if isinstance(state, dict):
        state["risk_flags"] = merge_case_review_assessments(
            state.get("risk_flags", []), state.get("case_assessment_summary") or {},
        )
        sync_case_status(state, generation="completed")
    return _response(session, status="complete")


def _response(
    session: dict[str, Any],
    *,
    status: str,
    error: str | None = None,
) -> dict[str, Any]:
    state = _active_cdd_state(session) or {}
    pdf_url = f"/api/pdf/{session['session_id']}" if session.get("pdf_path") else None
    return {
        "session_id": session["session_id"],
        "status": status,
        "messages": session["messages"],
        "customer_name": session.get("customer_name"),
        "jurisdiction": session.get("jurisdiction"),
        "account_location": session.get("account_location"),
        "case_id": session.get("case_id"),
        "cdd": state.get("cdd"),
        "cdd_state": state,
        "case_status": state.get("case_status"),
        "documents": state.get("documents", []),
        "risk_flags": state.get("risk_flags", []),
        "findings": state.get("findings", []),
        "assessments": state.get("assessments", []),
        "case_assessment_summary": state.get("case_assessment_summary"),
        "case_review_decision": session.get("case_review_decision"),
        "demo_csp_result": session.get("demo_csp_result"),
        "tool_results": session.get("tool_results", []),
        "pdf_url": pdf_url,
        "error": error if error is not None else session.get("pipeline_error"),
        "pipeline_status": session.get("pipeline_status"),
        "pipeline_progress": session.get("pipeline_progress"),
        "demo_mode": bool(session.get("demo_mode")) or _demo_mode_enabled(),
    }


def _cdd_state_snapshot(session: dict[str, Any]) -> dict[str, Any]:
    """Return the complete CDD state for the JSON workspace view."""
    return _active_cdd_state(session) or {}


def _active_cdd_state(session: dict[str, Any] | None) -> dict[str, Any] | None:
    state = (session or {}).get("graph_state")
    if not isinstance(state, dict):
        return None
    _normalise_document_state(state)
    return state


def _append_cdd_records(state: dict[str, Any], key: str, records: list[dict[str, Any]], id_key: str) -> None:
    existing = state.setdefault(key, [])
    known_ids = {item.get(id_key) for item in existing if item.get(id_key)}
    existing.extend(item for item in records if not item.get(id_key) or item.get(id_key) not in known_ids)


def _open_document_requirements(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Return unresolved canonical document records eligible for officer action."""
    return [
        document for document in state.get("documents", [])
        if document.get("purpose") == "identity_verification"
        and document.get("status") in {"required", "located", "received"}
    ]


def _migrate_legacy_document_requirements(requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Read old persisted requirement records into the canonical document shape."""
    documents = []
    for index, requirement in enumerate(requirements):
        individual = requirement.get("individual") or {}
        cached = requirement.get("cache_document") or {}
        old_status = requirement.get("status")
        resolved = old_status in {"cache_found", "provided", "received", "processed"}
        documents.append({
            "document_id": f"legacy:{requirement.get('id') or index}",
            "purpose": "company_profile" if requirement.get("document_type") == "registry_document" else "identity_verification",
            "document_type": requirement.get("document_type"),
            "subject": {"name": requirement.get("entity_name"), "case_common_id": individual.get("case_common_id")},
            "requirement": {"accepted_types": individual.get("required_documents", [])},
            "status": "processed" if old_status == "processed" else ("located" if resolved else "required"),
            "gap": {"status": "resolved" if resolved else "outstanding", "reason": "" if resolved else "No acceptable document is available."},
            "acquisition": {"source": requirement.get("source") or ("S3 document cache" if cached else None)},
            "storage": cached.get("storage") or {},
            "url": cached.get("url"),
            "name": cached.get("name"),
            "demo_url": requirement.get("demo_url"),
        })
    return documents


def _normalise_document_state(state: dict[str, Any]) -> None:
    """Upgrade persisted pre-#72 document shapes in place on first read."""
    legacy_requirements = state.pop("document_requirements", [])
    documents = state.setdefault("documents", [])
    for index, document in enumerate(list(documents)):
        if document.get("document_id"):
            continue
        document_type = document.get("document_type") or document.get("category") or "unknown"
        documents[index] = {
            "document_id": f"legacy:stored:{index}:{document_type}",
            "purpose": "company_profile" if document_type == "registry_document" else "identity_verification",
            "document_type": document_type,
            "subject": {"name": document.get("person_name")},
            "status": "located",
            "gap": {"status": "resolved", "reason": ""},
            "acquisition": {"source": document.get("source")},
            "storage": document.get("storage") or {},
            "url": document.get("url"),
            "name": document.get("name"),
            "collected_at": document.get("collected_at"),
        }
    known_ids = {document.get("document_id") for document in documents if document.get("document_id")}
    for document in _migrate_legacy_document_requirements(legacy_requirements):
        if document["document_id"] not in known_ids:
            documents.append(document)
            known_ids.add(document["document_id"])

    # Earlier graph states kept extraction records below cdd.documents. Preserve
    # their classification/extract data while moving them into the same record.
    cdd = state.get("cdd") or {}
    legacy_extracts = cdd.pop("documents", [])
    for index, legacy in enumerate(legacy_extracts):
        artifact = legacy.get("artifact") or {}
        extract = legacy.get("extract") or {}
        document_type = (
            (legacy.get("classification") or {}).get("document_type")
            or artifact.get("document_type") or extract.get("document_type") or "unknown"
        )
        subject_name = artifact.get("person_name") or extract.get("full_name") or extract.get("name")
        document_id = (
            "document:registry" if document_type == "registry_document"
            else f"legacy:extract:{artifact.get('case_common_id') or index}:{document_type}"
        )
        update = {
            "document_id": document_id,
            "purpose": "company_profile" if document_type == "registry_document" else "identity_verification",
            "document_type": document_type,
            "subject": {"name": subject_name, "case_common_id": artifact.get("case_common_id")},
            "status": "processed",
            "gap": {"status": "resolved", "reason": ""},
            "acquisition": {"source": artifact.get("source"), "artifact": artifact},
            "storage": artifact.get("storage") or {},
            "url": artifact.get("s3_url"),
            "processing": {
                "classification": legacy.get("classification"),
                "extract": extract,
                "processed_at": legacy.get("processed_at"),
            },
        }
        existing = next((item for item in documents if item.get("document_id") == document_id), None)
        if existing is None:
            documents.append(update)
        else:
            existing.update({key: value for key, value in update.items() if value not in ({}, None)})


def _artifact_for_processing(
    requirement: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    artifact = (requirement.get("acquisition") or {}).get("artifact") or {}
    return artifact, None


def _match_requirement(
    requirements: list[dict[str, Any]],
    classification: dict[str, Any],
    extract: dict[str, Any],
) -> dict[str, Any] | None:
    document_type = classification.get("document_type")
    extracted_name = _normalise_name(extract.get("full_name") or extract.get("name") or "")
    candidates = []
    for requirement in requirements:
        if requirement.get("status") not in {"required", "located"}:
            continue
        if requirement.get("document_type") != document_type:
            continue
        score = 0.65
        if extracted_name and extracted_name == _normalise_name((requirement.get("subject") or {}).get("name") or ""):
            score += 0.35
        candidates.append((score, requirement))
    if not candidates:
        return None
    score, requirement = max(candidates, key=lambda item: item[0])
    return requirement if score >= 0.65 else None


def _match_summary(
    requirement: dict[str, Any],
    classification: dict[str, Any],
    extract: dict[str, Any],
) -> dict[str, Any]:
    extracted_name = _normalise_name(extract.get("full_name") or extract.get("name") or "")
    exact_name = extracted_name == _normalise_name((requirement.get("subject") or {}).get("name") or "")
    return {
        "confidence": 1.0 if exact_name else 0.65,
        "reason": "document type and extracted name match" if exact_name else "document type match",
        "classification": classification.get("document_type"),
    }


def _normalise_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _safe_file_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", Path(name).name) or "document.pdf"


async def _resume_if_ready(session: dict[str, Any]) -> None:
    documents = (_active_cdd_state(session) or {}).get("documents", [])
    if any((row.get("gap") or {}).get("status") == "outstanding" for row in documents):
        session["pipeline_status"] = "awaiting_documents"
        sync_case_status(session, generation="in_progress")
        return
    thread_id = session.get("graph_thread_id")
    if not thread_id:
        return
    session["pipeline_status"] = "running"
    session.pop("pipeline_error", None)
    sync_case_status(session, generation="in_progress")
    def publish_progress(progress: dict[str, Any]) -> None:
        session["pipeline_progress"] = progress
    try:
        result = await asyncio.to_thread(
            resume_cdd_agent_state,
            thread_id=thread_id,
            documents=documents,
            progress_callback=publish_progress,
        )
        _apply_graph_result(session, result)
        session["pipeline_status"] = "complete"
        sync_case_status(session)
    except Exception as exc:
        session["pipeline_status"] = "error"
        session["pipeline_error"] = str(exc)
        sync_case_status(session, generation="failed")
        raise


def _session_document_by_key(
    session: dict[str, Any],
    document_key: str,
) -> dict[str, Any] | None:
    state = _active_cdd_state(session) or {}
    for document in state.get("documents", []):
        storage = document.get("storage") or {}
        if storage.get("key") == document_key:
            return document
    return None


def _summary(cdd: dict[str, Any], case_status: dict[str, Any]) -> str:
    profile = cdd.get("company_business_profile", {}).get("customer_static", {})
    ownership = cdd.get("ownership_and_control", {})
    ubos = len(ownership.get("ubos", []))
    shareholders = len(ownership.get("shareholders_over_10_percent", []))
    related = len(ownership.get("related_parties", []))
    generation = str(case_status.get("cdd_generation", "not_started")).replace("_", " ")
    name = profile.get("name") or "the customer"
    return (
        f"CDD generation for {name}: {generation}. "
        f"UBOs: {ubos}; shareholders >10%: {shareholders}; "
        f"related parties: {related}."
    )


def _clean_jurisdiction(value: str | None) -> str | None:
    if not value:
        return None
    return value.strip().upper()


async def _generate_pdf_for_session(session: dict[str, Any]) -> dict[str, Any]:
    state = _active_cdd_state(session)
    if not state or not state.get("cdd"):
        session["messages"].append(
            {
                "role": "assistant",
                "content": "Run the full CDD pipeline before generating a PDF.",
            }
        )
        return _response(session, status="needs_input")
    pdf_path = render_cdd_pdf(state["cdd"])
    session["pdf_path"] = str(pdf_path)
    session["messages"].append(
        {"role": "assistant", "content": "PDF generated and ready to download."}
    )
    return _response(session, status="complete")


async def _run_pipeline_for_session(
    session: dict[str, Any],
    *,
    customer_name: str | None,
    jurisdiction: str | None,
    account_location: Literal["SG", "HK", "GB"] | None = None,
    case_id: str | None = None,
    generate_pdf: bool = False,
    background_tasks: BackgroundTasks | None = None,
) -> dict[str, Any]:
    if not customer_name or not jurisdiction or not account_location:
        session["messages"].append(
            {
                "role": "assistant",
                "content": "Please provide a company name, jurisdiction, and account opening location to run the full CDD pipeline.",
            }
        )
        return _response(session, status="needs_input")

    jurisdiction = _clean_jurisdiction(jurisdiction)
    if session.get("pipeline_status") == "running":
        return _response(session, status="running")

    _clear_previous_cdd_run(session)
    session["customer_name"] = customer_name
    session["jurisdiction"] = jurisdiction
    session["account_location"] = account_location
    if case_id:
        session["case_id"] = case_id
    else:
        session.pop("case_id", None)
    # The LangGraph memory checkpointer uses reducers that append evidence and
    # documents.  A fresh thread prevents a new case from inheriting the
    # previous case's checkpointed state; this ID is retained only to resume
    # this run after document collection.
    session["graph_thread_id"] = str(uuid.uuid4())
    session["graph_state"] = new_cdd_state(
        customer_name=customer_name,
        jurisdiction=jurisdiction,
        account_location=account_location,
        case_id=case_id,
    )
    session["pipeline_status"] = "running"
    sync_case_status(session["graph_state"], generation="in_progress")
    session["pipeline_progress"] = {
        "node": "collect_required_inputs",
        "node_number": 1,
        "total_nodes": len(PIPELINE_NODE_LABELS),
        "message": "Collecting Inputs",
        "using_cache": False,
        "status": "queued",
    }
    session["messages"].append(
        {
            "role": "assistant",
            "content": _registry_fetch_message(
                customer_name=customer_name,
                jurisdiction=jurisdiction,
                case_id=case_id,
            ),
        }
    )

    task_kwargs = {
        "customer_name": customer_name,
        "jurisdiction": jurisdiction,
        "account_location": account_location,
        "case_id": case_id,
        "generate_pdf": generate_pdf,
        "graph_thread_id": session["graph_thread_id"],
    }
    if background_tasks is not None:
        background_tasks.add_task(
            _complete_pipeline_for_session,
            session,
            **task_kwargs,
        )
    else:
        asyncio.create_task(
            _complete_pipeline_for_session(
                session,
                **task_kwargs,
            )
        )
    return _response(session, status="running")


def _registry_fetch_message(
    *,
    customer_name: str,
    jurisdiction: str | None,
    case_id: str | None = None,
) -> str:
    if case_id:
        source = (
            "reading from cache"
            if get_cache_value("company-detail", [case_id]) is not None
            else "calling API"
        )
    else:
        source = (
            "reading from cache"
            if jurisdiction
            and get_cache_value("company-case", [jurisdiction, customer_name]) is not None
            else "calling API"
        )
    return f"Fetching registry information... {source}"


def _apply_graph_result(session: dict[str, Any], graph_state: dict[str, Any]) -> None:
    session["graph_state"] = graph_state
    sync_case_status(graph_state)


async def _complete_pipeline_for_session(
    session: dict[str, Any],
    *,
    customer_name: str,
    jurisdiction: str | None,
    account_location: Literal["SG", "HK", "GB"],
    case_id: str | None = None,
    generate_pdf: bool = False,
    graph_thread_id: str,
) -> None:
    try:
        def publish_progress(progress: dict[str, Any]) -> None:
            # The graph runs in a worker thread; each update is a complete object so
            # polling clients never observe a partially-written progress payload.
            session["pipeline_progress"] = progress

        graph_state = await asyncio.to_thread(
            run_cdd_agent_state,
            customer_name=customer_name,
            jurisdiction=jurisdiction,
            account_location=account_location,
            case_id=case_id,
            progress_callback=publish_progress,
            thread_id=graph_thread_id,
        )
        _apply_graph_result(session, graph_state)
        cdd = graph_state.get("cdd", {})
        if any(
            (row.get("gap") or {}).get("status") == "outstanding"
            for row in graph_state.get("documents", [])
        ):
            session["pipeline_status"] = "awaiting_documents"
            sync_case_status(session, generation="in_progress")
            return
        for message in graph_state.get("messages", []):
            content = getattr(message, "content", None)
            if content:
                session["messages"].append({"role": "assistant", "content": str(content)})

        session["messages"].append(
            {"role": "assistant", "content": _summary(cdd, graph_state.get("case_status", {}))}
        )

        if generate_pdf:
            pdf_path = render_cdd_pdf(cdd)
            session["pdf_path"] = str(pdf_path)

        session["pipeline_status"] = "complete"
        sync_case_status(graph_state)
    except Exception as exc:
        session["pipeline_status"] = "error"
        session["pipeline_error"] = str(exc)
        state = _active_cdd_state(session)
        if state:
            sync_case_status(state, generation="failed")
        current_progress = session.get("pipeline_progress") or {}
        session["pipeline_progress"] = {
            **current_progress,
            "status": "error",
            "error": str(exc),
        }
        session["messages"].append(
            {"role": "assistant", "content": f"CDD pipeline failed: {exc}"}
        )


async def _run_named_company_tool(
    session: dict[str, Any],
    *,
    tool_name: str,
    tool_func,
    args: dict[str, Any],
) -> dict[str, Any]:
    company_name = args.get("company_name") or args.get("customer_name")
    jurisdiction = _clean_jurisdiction(args.get("jurisdiction"))
    if not company_name or not jurisdiction:
        session["messages"].append(
            {
                "role": "assistant",
                "content": f"I need company name and jurisdiction to run {tool_name}.",
            }
        )
        return _response(session, status="needs_input")

    result = tool_func(company_name, jurisdiction)
    session["customer_name"] = company_name
    session["jurisdiction"] = jurisdiction
    return await _run_tool_for_session(session, tool_name=tool_name, result=result)


async def _run_tool_for_session(
    session: dict[str, Any],
    *,
    tool_name: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    tool_result = {
        "tool": tool_name,
        "data": result,
    }
    session.setdefault("tool_results", []).append(tool_result)
    state = _active_cdd_state(session)
    if state is not None:
        state.setdefault("evidence", []).append(
        {
            "source": "tool",
            "tool": tool_name,
            "description": f"Result from {tool_name}",
            "relevance_tags": [tool_name],
            "data": result,
        }
        )
    session["messages"].append(
        {"role": "assistant", "content": _tool_summary(tool_name, result)}
    )
    return _response(session, status="tool_complete")


def _tool_summary(tool_name: str, result: dict[str, Any]) -> str:
    if result.get("error"):
        return f"{tool_name} failed: {result['error'].get('message')}"
    if tool_name == "find_test_cases":
        lines = []
        summary = result.get("summary", {}).get("summary_text")
        if summary:
            lines.append(summary)
        if result.get("view") == "jurisdiction_counts":
            rows = result.get("jurisdiction_counts", [])
            lines.append("")
            lines.append("Entities by jurisdiction:")
            lines.append("Jurisdiction | Count")
            lines.append("--- | ---")
            for row in rows:
                lines.append(f"{row.get('value')} | {row.get('count')}")
            return "\n".join(lines)
        cases = result.get("returned_cases", [])
        if not cases:
            filters = result.get("filters", {})
            filter_text = ", ".join(
                f"{key}: {value}" for key, value in filters.items()
            )
            lines.append(
                "No matching sandbox entities found"
                + (f" for {filter_text}." if filter_text else ".")
            )
            return "\n".join(lines)
        lines.append("Available entities:")
        for case in cases:
            parts = [
                case.get("name"),
                case.get("jurisdiction"),
                case.get("country_name"),
                case.get("registration_number"),
            ]
            lines.append(" - " + " | ".join(str(part) for part in parts if part))
        if result.get("note"):
            lines.append(result["note"])
        return "\n".join(lines)
    if tool_name == "get_customer_static_by_name":
        static = result.get("customer_static", {})
        return (
            f"Static profile fetched for {static.get('name', 'the company')}. "
            f"Status: {static.get('company_status', '-')}; "
            f"registration number: {static.get('registration_number', '-')}."
        )
    if tool_name == "get_company_members_by_name":
        counts = result.get("counts", {})
        return (
            "Members fetched. "
            f"Controlling members: {counts.get('controlling_members', 0)}; "
            f"shareholders/beneficial owners: {counts.get('shareholders_and_beneficial_owners', 0)}; "
            f"UBOs: {counts.get('ultimate_beneficial_owners', 0)}."
        )
    if tool_name == "get_company_org_chart_by_name":
        counts = result.get("counts", {})
        return (
            "Org chart fetched. "
            f"Nodes: {counts.get('nodes', 0)}; "
            f"shareholders: {counts.get('shareholders', 0)}; "
            f"officers: {counts.get('officers', 0)}."
        )
    return f"{tool_name} completed."


def _session_context(session: dict[str, Any]) -> dict[str, Any]:
    return {
        "customer_name": session.get("customer_name"),
        "jurisdiction": session.get("jurisdiction"),
        "case_id": session.get("case_id"),
        "case_status": (_active_cdd_state(session) or {}).get("case_status"),
        "has_cdd": bool((_active_cdd_state(session) or {}).get("cdd")),
        "has_pdf": bool(session.get("pdf_path")),
        "tool_results": [
            {"tool": item.get("tool")} for item in session.get("tool_results", [])[-5:]
        ],
    }


def _merge_session_args(args: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
    merged = dict(args or {})
    if not merged.get("company_name") and not merged.get("customer_name"):
        merged["company_name"] = session.get("customer_name")
    if not merged.get("jurisdiction"):
        merged["jurisdiction"] = session.get("jurisdiction")
    if not merged.get("case_id"):
        merged["case_id"] = session.get("case_id")
    return merged


if DEMO_CASE_PATH.parent.exists():
    app.mount("/demo-data", StaticFiles(directory=DEMO_CASE_PATH.parent), name="demo-data")

if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
