"""FastAPI app that exposes the CDD LangGraph as a chatbot backend."""

from __future__ import annotations

import asyncio
import json
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

from src.agents.chat_graph import run_chat_graph
from src.agents.graph import resume_cdd_agent_state, run_cdd_agent_state
from src.agents.qa import answer_cdd_question
from src.tools.case_finder import find_test_cases
from src.tools.case_review import CaseReviewError, generate_case_review_summary, unavailable_case_review
from src.tools.csp_detector import CSPAssessmentError, evaluate_csp_address, load_csp_skill
from src.tools.customer_static import get_customer_static_by_name
from src.tools.document_extraction import classify_document, extract_document
from src.tools.members import get_company_members_by_name
from src.tools.orgchart import get_company_org_chart_by_name
from src.utils.kyc_cache import get_cache_value
from src.utils.pdf import render_cdd_pdf
from src.utils.idv_document_pipeline import generate_idv_document
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
SANDBOX_CASES_PATH = PROJECT_ROOT / "registry_list_of_mock_cases" / "kyc-sandbox-test-cases.json"

app = FastAPI(title="WBL Bank CDD Chatbot")
SESSIONS: dict[str, dict[str, Any]] = {}


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


class CaseReviewDecisionRequest(BaseModel):
    session_id: str
    decision: Literal["approve", "request_information", "escalate"]
    note: str = Field(default="", max_length=4_000)


class CaseReviewRefreshRequest(BaseModel):
    session_id: str


@app.post("/api/chat")
async def chat(
    request: ChatRequest,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    session = _session(request.session_id)
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


@app.post("/api/csp/assess")
async def assess_csp(request: CSPAssessmentRequest) -> dict[str, Any]:
    """Run an isolated CSP assessment that does not change an active CDD case."""
    try:
        return await asyncio.to_thread(
            evaluate_csp_address,
            request.registered_address,
            company_name=request.company_name,
        )
    except CSPAssessmentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/case-review/refresh")
async def refresh_case_review(request: CaseReviewRefreshRequest) -> dict[str, Any]:
    session = SESSIONS.get(request.session_id)
    if not session or not session.get("cdd"):
        raise HTTPException(status_code=404, detail="No CDD result for this session")
    try:
        summary = await asyncio.to_thread(
            generate_case_review_summary,
            cdd=session["cdd"],
            risk_flags=session.get("risk_flags", []),
            evidence=session.get("evidence", []),
            final_recommendation=session.get("final_recommendation"),
        )
    except CaseReviewError as exc:
        summary = unavailable_case_review(session.get("final_recommendation"), str(exc))
    session["case_review_summary"] = summary
    return _response(session, status="case_review_refreshed")


@app.post("/api/case-review/decision")
async def record_case_review_decision(request: CaseReviewDecisionRequest) -> dict[str, Any]:
    session = SESSIONS.get(request.session_id)
    if not session or not session.get("cdd"):
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
    return await _run_pipeline_for_session(
        session,
        customer_name=request.customer_name,
        jurisdiction=request.jurisdiction,
        case_id=request.case_id,
        generate_pdf=request.generate_pdf,
        background_tasks=background_tasks,
    )


@app.post("/api/pdf")
async def generate_pdf(request: PdfRequest) -> dict[str, Any]:
    session = SESSIONS.get(request.session_id)
    if not session or not session.get("cdd"):
        raise HTTPException(status_code=404, detail="No CDD result for this session")

    pdf_path = render_cdd_pdf(session["cdd"])
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
    if not session or not session.get("document_requirements"):
        raise HTTPException(status_code=404, detail="Document requirements not found")
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

    requirement = _match_requirement(session["document_requirements"], classification, preview)
    if not requirement:
        path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail="No open document requirement matched this upload")
    requirement.update(
        {
            "status": "provided",
            "source": "customer_upload",
            "artifact": {**artifact, "document_type": classification.get("document_type")},
            "classification": classification,
            "match": _match_summary(requirement, classification, preview),
        }
    )
    await _resume_if_ready(session)
    return _response(session, status=session.get("pipeline_status", "awaiting_documents"))


@app.post("/api/documents/generate")
async def generate_missing_documents(request: DocumentActionRequest) -> dict[str, Any]:
    """Generate selected unavailable documents locally; processing is still explicit."""
    session = SESSIONS.get(request.session_id)
    if not session or not session.get("document_requirements"):
        raise HTTPException(status_code=404, detail="Document requirements not found")
    selected = set(request.requirement_ids or [])
    for requirement in session["document_requirements"]:
        if selected and requirement["id"] not in selected:
            continue
        if requirement.get("status") != "not_found":
            continue
        artifact = await asyncio.to_thread(
            generate_idv_document,
            {**requirement["individual"], "selected_document_type": requirement["document_type"]},
            output_dir=DOCUMENT_STAGING_DIR / request.session_id,
        )
        requirement.update({"status": "received", "source": "generated", "artifact": artifact})
    await _resume_if_ready(session)
    return _response(session, status=session.get("pipeline_status", "awaiting_documents"))


@app.post("/api/documents/process")
async def process_case_documents(request: DocumentActionRequest) -> dict[str, Any]:
    session = SESSIONS.get(request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="CDD session not found")
    await _resume_if_ready(session)
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
        "messages": [
            {
                "role": "assistant",
                "content": "Which company would you like to onboard?",
            }
        ],
    }
    SESSIONS[session_id] = session
    return session


def _response(
    session: dict[str, Any],
    *,
    status: str,
    error: str | None = None,
) -> dict[str, Any]:
    pdf_url = f"/api/pdf/{session['session_id']}" if session.get("pdf_path") else None
    return {
        "session_id": session["session_id"],
        "status": status,
        "messages": session["messages"],
        "customer_name": session.get("customer_name"),
        "jurisdiction": session.get("jurisdiction"),
        "case_id": session.get("case_id"),
        "cdd": session.get("cdd"),
        "documents": session.get("documents", []),
        "document_requirements": session.get("document_requirements", []),
        "risk_flags": session.get("risk_flags", []),
        "final_recommendation": session.get("final_recommendation"),
        "case_review_summary": session.get("case_review_summary"),
        "case_review_decision": session.get("case_review_decision"),
        "tool_results": session.get("tool_results", []),
        "pdf_url": pdf_url,
        "error": error,
        "pipeline_status": session.get("pipeline_status"),
        "pipeline_progress": session.get("pipeline_progress"),
    }


def _build_document_requirements(session: dict[str, Any]) -> list[dict[str, Any]]:
    cdd = session.get("cdd") or {}
    individuals = cdd.get("individual_identity_verification", {}).get("required_individuals", [])
    available = find_documents_in_s3(
        company_name=session.get("customer_name"),
        jurisdiction=session.get("jurisdiction"),
    )
    by_name = {document.get("name"): document for document in available}
    requirements = []
    for index, individual in enumerate(individuals):
        document_type = individual.get("selected_document_type") or "passport"
        expected_name = reusable_document_name(
            document_type=document_type,
            company_name=session["customer_name"],
            person_name=individual.get("name"),
        )
        cached = by_name.get(expected_name)
        requirements.append(
            {
                "id": f"idv-{index}-{document_type}",
                "entity_name": individual.get("name"),
                "document_type": document_type,
                "individual": individual,
                "status": "cache_found" if cached else "not_found",
                "cache_document": cached,
                "match": None,
            }
        )
    return requirements


def _artifact_for_processing(
    requirement: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if requirement.get("status") == "cache_found":
        document = requirement.get("cache_document")
        if not document:
            return None, None
        return (
            {
                "pdf_path": download_document_from_s3(document),
                "document_type": requirement["document_type"],
                "person_name": requirement["entity_name"],
                "case_common_id": requirement["individual"].get("case_common_id"),
                "source": "S3 document cache",
                "s3_url": document["url"],
                "storage": document["storage"],
            },
            document,
        )
    return requirement.get("artifact"), None


def _match_requirement(
    requirements: list[dict[str, Any]],
    classification: dict[str, Any],
    extract: dict[str, Any],
) -> dict[str, Any] | None:
    document_type = classification.get("document_type")
    extracted_name = _normalise_name(extract.get("full_name") or extract.get("name") or "")
    candidates = []
    for requirement in requirements:
        if requirement.get("status") not in {"not_found", "cache_found"}:
            continue
        if requirement.get("document_type") != document_type:
            continue
        score = 0.65
        if extracted_name and extracted_name == _normalise_name(requirement.get("entity_name") or ""):
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
    exact_name = extracted_name == _normalise_name(requirement.get("entity_name") or "")
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
    requirements = session.get("document_requirements", [])
    if any(row.get("status") == "not_found" for row in requirements):
        session["pipeline_status"] = "awaiting_documents"
        return
    thread_id = session.get("graph_thread_id")
    if not thread_id:
        return
    session["pipeline_status"] = "running"
    def publish_progress(progress: dict[str, Any]) -> None:
        session["pipeline_progress"] = progress
    result = await asyncio.to_thread(
        resume_cdd_agent_state,
        thread_id=thread_id,
        document_requirements=requirements,
        progress_callback=publish_progress,
    )
    _apply_graph_result(session, result)
    session["pipeline_status"] = "complete"


def _session_document_by_key(
    session: dict[str, Any],
    document_key: str,
) -> dict[str, Any] | None:
    for document in session.get("documents", []):
        storage = document.get("storage") or {}
        if storage.get("key") == document_key:
            return document
    for requirement in session.get("document_requirements", []):
        document = requirement.get("cache_document") or {}
        storage = document.get("storage") or {}
        if storage.get("key") == document_key:
            return document
    return None


def _summary(cdd: dict[str, Any]) -> str:
    profile = cdd.get("company_business_profile", {}).get("customer_static", {})
    ownership = cdd.get("ownership_and_control", {})
    ubos = len(ownership.get("ubos", []))
    shareholders = len(ownership.get("shareholders_over_10_percent", []))
    related = len(ownership.get("related_parties", []))
    status = cdd.get("status", "unknown")
    name = profile.get("name") or "the customer"
    return (
        f"CDD generated for {name}. Status: {status}. "
        f"UBOs: {ubos}; shareholders >10%: {shareholders}; "
        f"related parties: {related}."
    )


def _clean_jurisdiction(value: str | None) -> str | None:
    if not value:
        return None
    return value.strip().upper()


async def _generate_pdf_for_session(session: dict[str, Any]) -> dict[str, Any]:
    if not session.get("cdd"):
        session["messages"].append(
            {
                "role": "assistant",
                "content": "Run the full CDD pipeline before generating a PDF.",
            }
        )
        return _response(session, status="needs_input")
    pdf_path = render_cdd_pdf(session["cdd"])
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
    case_id: str | None = None,
    generate_pdf: bool = False,
    background_tasks: BackgroundTasks | None = None,
) -> dict[str, Any]:
    if not customer_name or not jurisdiction:
        session["messages"].append(
            {
                "role": "assistant",
                "content": "Please provide a company name and jurisdiction to run the full CDD pipeline.",
            }
        )
        return _response(session, status="needs_input")

    jurisdiction = _clean_jurisdiction(jurisdiction)
    if session.get("pipeline_status") == "running":
        return _response(session, status="running")

    session["customer_name"] = customer_name
    session["jurisdiction"] = jurisdiction
    session["pipeline_status"] = "running"
    session["pipeline_error"] = None
    session["pipeline_progress"] = {
        "node": "collect_required_inputs",
        "node_number": 1,
        "total_nodes": 15,
        "message": "Collecting Inputs",
        "using_cache": False,
        "status": "queued",
    }
    if case_id:
        session["case_id"] = case_id

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
        "case_id": case_id,
        "generate_pdf": generate_pdf,
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
    session["cdd"] = graph_state.get("cdd", {})
    session["graph_state"] = graph_state
    session["documents"] = graph_state.get("documents", [])
    session["evidence"] = graph_state.get("evidence", [])
    session["risk_flags"] = graph_state.get("risk_flags", [])
    session["final_recommendation"] = graph_state.get("final_recommendation")
    session["case_review_summary"] = graph_state.get("case_review_summary")
    session["document_requirements"] = graph_state.get("document_requirements", [])


async def _complete_pipeline_for_session(
    session: dict[str, Any],
    *,
    customer_name: str,
    jurisdiction: str | None,
    case_id: str | None = None,
    generate_pdf: bool = False,
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
            case_id=case_id,
            progress_callback=publish_progress,
            thread_id=session["session_id"],
        )
        session["graph_thread_id"] = session["session_id"]
        _apply_graph_result(session, graph_state)
        cdd = session["cdd"]
        session["document_results"] = cdd.get("documents", [])
        if any(row.get("status") == "not_found" for row in session["document_requirements"]):
            session["pipeline_status"] = "awaiting_documents"
            return
        for message in graph_state.get("messages", []):
            content = getattr(message, "content", None)
            if content:
                session["messages"].append({"role": "assistant", "content": str(content)})

        session["messages"].append({"role": "assistant", "content": _summary(cdd)})

        if generate_pdf:
            pdf_path = render_cdd_pdf(cdd)
            session["pdf_path"] = str(pdf_path)

        session["pipeline_status"] = "complete"
    except Exception as exc:
        session["pipeline_status"] = "error"
        session["pipeline_error"] = str(exc)
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
    session.setdefault("evidence", []).append(
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
        "has_cdd": bool(session.get("cdd")),
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


if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
