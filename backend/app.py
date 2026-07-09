"""FastAPI app that exposes the CDD LangGraph as a chatbot backend."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agents.graph import run_cdd_agent_state
from agents.qa import answer_cdd_question
from agents.router import route_user_message
from tools.case_finder import find_test_cases
from tools.customer_static import get_customer_static_by_name
from tools.members import get_company_members_by_name
from tools.orgchart import get_company_org_chart_by_name
from utils.pdf import render_cdd_pdf


load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = PROJECT_ROOT / "frontend"
OUTPUT_DIR = PROJECT_ROOT / "outputs"

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


@app.post("/api/chat")
async def chat(
    request: ChatRequest,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    session = _session(request.session_id)
    if request.message:
        session["messages"].append({"role": "user", "content": request.message})

    decision = route_user_message(
        message=request.message,
        session_context=_session_context(session),
    )
    action = decision.get("action", "answer_from_context")
    args = _merge_session_args(decision.get("arguments", {}), session)

    try:
        if action == "generate_pdf":
            return await _generate_pdf_for_session(session)
        if action == "run_full_cdd_pipeline":
            return await _run_pipeline_for_session(
                session,
                customer_name=args.get("company_name") or args.get("customer_name"),
                jurisdiction=args.get("jurisdiction"),
                case_id=args.get("case_id"),
                generate_pdf=request.generate_pdf,
                background_tasks=background_tasks,
            )
        if action == "find_test_cases":
            return await _run_tool_for_session(
                session,
                tool_name="find_test_cases",
                result=find_test_cases(
                    query=args.get("query"),
                    jurisdiction=args.get("jurisdiction"),
                    country=args.get("country"),
                    origin=args.get("origin"),
                    limit=int(args.get("limit") or 10),
                ),
            )
        if action == "get_customer_static_by_name":
            return await _run_named_company_tool(
                session,
                tool_name="get_customer_static_by_name",
                tool_func=get_customer_static_by_name,
                args=args,
            )
        if action == "get_company_members_by_name":
            return await _run_named_company_tool(
                session,
                tool_name="get_company_members_by_name",
                tool_func=get_company_members_by_name,
                args=args,
            )
        if action == "get_company_org_chart_by_name":
            return await _run_named_company_tool(
                session,
                tool_name="get_company_org_chart_by_name",
                tool_func=get_company_org_chart_by_name,
                args=args,
            )
        if action == "ask_missing_inputs":
            content = decision.get("response") or "What company name and jurisdiction should I use?"
            session["messages"].append({"role": "assistant", "content": content})
            return _response(session, status="needs_input")
        if action == "answer_from_context" and decision.get("response") and not session.get("cdd"):
            content = decision["response"]
            session["messages"].append({"role": "assistant", "content": content})
            return _response(session, status="llm_unavailable")

        answer = answer_cdd_question(
            question=request.message,
            cdd=session.get("cdd", {}),
            evidence=session.get("evidence", []),
            risk_flags=session.get("risk_flags", []),
        )
        session["messages"].append({"role": "assistant", "content": answer})
        return _response(session, status="answered")
    except Exception as exc:
        content = f"Request failed: {exc}"
        session["messages"].append({"role": "assistant", "content": content})
        return _response(session, status="error", error=str(exc))


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
        "risk_flags": session.get("risk_flags", []),
        "final_recommendation": session.get("final_recommendation"),
        "tool_results": session.get("tool_results", []),
        "pdf_url": pdf_url,
        "error": error,
        "pipeline_status": session.get("pipeline_status"),
    }


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
    if case_id:
        session["case_id"] = case_id

    session["messages"].append(
        {
            "role": "assistant",
            "content": f"Running full CDD pipeline for {customer_name} ({jurisdiction}).",
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


async def _complete_pipeline_for_session(
    session: dict[str, Any],
    *,
    customer_name: str,
    jurisdiction: str | None,
    case_id: str | None = None,
    generate_pdf: bool = False,
) -> None:
    try:
        graph_state = await asyncio.to_thread(
            run_cdd_agent_state,
            customer_name=customer_name,
            jurisdiction=jurisdiction,
            case_id=case_id,
        )
        cdd = graph_state.get("cdd", {})
        session["cdd"] = cdd
        session["graph_state"] = graph_state
        session["evidence"] = graph_state.get("evidence", [])
        session["risk_flags"] = graph_state.get("risk_flags", [])
        session["final_recommendation"] = graph_state.get("final_recommendation")
        session["messages"].append({"role": "assistant", "content": _summary(cdd)})

        if generate_pdf:
            pdf_path = render_cdd_pdf(cdd)
            session["pdf_path"] = str(pdf_path)

        session["pipeline_status"] = "complete"
    except Exception as exc:
        session["pipeline_status"] = "error"
        session["pipeline_error"] = str(exc)
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
        cases = result.get("returned_cases", [])
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
