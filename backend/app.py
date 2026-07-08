"""FastAPI app that exposes the CDD LangGraph as a chatbot backend."""

from __future__ import annotations

import asyncio
import re
import uuid
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agents.graph import run_cdd_agent
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


@app.post("/api/chat")
async def chat(request: ChatRequest) -> dict[str, Any]:
    session = _session(request.session_id)
    if request.message:
        session["messages"].append({"role": "user", "content": request.message})

    customer_name = request.customer_name or session.get("customer_name")
    jurisdiction = _clean_jurisdiction(request.jurisdiction or session.get("jurisdiction"))
    case_id = request.case_id or session.get("case_id")

    inferred = _infer_customer_and_jurisdiction(request.message)
    customer_name = customer_name or inferred.get("customer_name")
    jurisdiction = jurisdiction or inferred.get("jurisdiction")

    if not customer_name or not jurisdiction:
        missing = []
        if not customer_name:
            missing.append("company name")
        if not jurisdiction:
            missing.append("jurisdiction")
        content = (
            "I can start the CDD onboarding once I have the "
            f"{' and '.join(missing)}. For example: "
            '"CROPWELL BISHOP CREAMERY LIMITED, GB".'
        )
        session["messages"].append({"role": "assistant", "content": content})
        return _response(session, status="needs_input")

    session["customer_name"] = customer_name
    session["jurisdiction"] = jurisdiction
    if case_id:
        session["case_id"] = case_id

    session["messages"].append(
        {
            "role": "assistant",
            "content": f"Running CDD checks for {customer_name} ({jurisdiction}).",
        }
    )
    try:
        cdd = await asyncio.to_thread(
            run_cdd_agent,
            customer_name=customer_name,
            jurisdiction=jurisdiction,
            case_id=case_id,
        )
    except Exception as exc:
        content = f"CDD checks failed: {exc}"
        session["messages"].append({"role": "assistant", "content": content})
        return _response(session, status="error", error=str(exc))

    session["cdd"] = cdd
    session["messages"].append({"role": "assistant", "content": _summary(cdd)})

    if request.generate_pdf:
        pdf_path = await asyncio.to_thread(render_cdd_pdf, cdd)
        session["pdf_path"] = str(pdf_path)

    return _response(session, status="complete")


@app.post("/api/pdf")
async def generate_pdf(request: PdfRequest) -> dict[str, Any]:
    session = SESSIONS.get(request.session_id)
    if not session or not session.get("cdd"):
        raise HTTPException(status_code=404, detail="No CDD result for this session")

    pdf_path = await asyncio.to_thread(render_cdd_pdf, session["cdd"])
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
    return _response(session, status="ok")


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
        "pdf_url": pdf_url,
        "error": error,
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


def _infer_customer_and_jurisdiction(message: str) -> dict[str, str]:
    text = (message or "").strip()
    if not text:
        return {}

    match = re.search(r"\b([A-Z]{2})\b\s*$", text, flags=re.IGNORECASE)
    if not match:
        return {}

    jurisdiction = match.group(1).upper()
    name = text[: match.start()].strip(" ,.-")
    name = re.sub(r"^(onboard|start cdd for|run cdd for|company)\s+", "", name, flags=re.I)
    if not name:
        return {"jurisdiction": jurisdiction}
    return {"customer_name": name, "jurisdiction": jurisdiction}


if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
