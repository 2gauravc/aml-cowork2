"""Evidence-aware question answering for the CDD chatbot."""

from __future__ import annotations

import json
import os
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from openai import OpenAIError


def answer_cdd_question(
    *,
    question: str,
    cdd: dict[str, Any],
    evidence: list[dict[str, Any]],
    risk_flags: list[dict[str, Any]],
) -> str:
    """Answer a follow-up question using CDD first, then richer evidence."""
    deterministic = _deterministic_answer(question, cdd, evidence, risk_flags)
    if deterministic:
        return deterministic

    snippets = retrieve_evidence_snippets(question, cdd, evidence, risk_flags)
    if not _openai_qa_enabled():
        return _fallback_answer(question, snippets)

    llm = ChatOpenAI(
        model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        temperature=0,
        timeout=20,
    )
    try:
        response = llm.invoke(
            [
                SystemMessage(
                    content=(
                        "You are a CDD analyst assistant. Answer only from the CDD "
                        "JSON, risk flags, and evidence snippets provided. If the "
                        "answer is not present, say what is missing. Do not treat "
                        "AML flags as proof of wrongdoing; describe them as review "
                        "items."
                    )
                ),
                HumanMessage(
                    content=(
                        f"Question:\n{question}\n\n"
                        f"Relevant CDD/evidence snippets:\n{json.dumps(snippets, indent=2)}"
                    )
                ),
            ]
        )
        return str(response.content)
    except OpenAIError:
        return _fallback_answer(question, snippets)


def retrieve_evidence_snippets(
    question: str,
    cdd: dict[str, Any],
    evidence: list[dict[str, Any]],
    risk_flags: list[dict[str, Any]],
    *,
    limit: int = 6,
) -> list[dict[str, Any]]:
    """Return compact snippets likely to answer a user question."""
    tokens = _tokens(question)
    candidates = [
        {
            "source": "CDD",
            "description": "Final business-facing CDD object",
            "data": _trim(cdd),
        },
        {
            "source": "risk_flags",
            "description": "Risk flags from graph state",
            "data": _trim(risk_flags),
        },
    ]
    for item in evidence:
        candidates.append(
            {
                "source": item.get("source"),
                "tool": item.get("tool"),
                "description": item.get("description"),
                "relevance_tags": item.get("relevance_tags", []),
                "data": _trim(item.get("data")),
            }
        )

    scored = sorted(
        candidates,
        key=lambda candidate: _score(candidate, tokens),
        reverse=True,
    )
    return [candidate for candidate in scored[:limit] if _score(candidate, tokens) > 0] or scored[:2]


def _deterministic_answer(
    question: str,
    cdd: dict[str, Any],
    evidence: list[dict[str, Any]],
    risk_flags: list[dict[str, Any]],
) -> str | None:
    q = question.casefold()
    ownership = cdd.get("ownership_and_control", {})

    if "ubo" in q or "beneficial owner" in q:
        ubos = ownership.get("ubos", [])
        if not ubos:
            return "No individual UBO above 25% is identified in the current CDD output."
        rows = [
            f"{row.get('name')} ({row.get('effective_shareholding_percent')}%)"
            for row in ubos
        ]
        return "Identified UBOs: " + "; ".join(rows) + "."

    if "shareholder" in q or "own" in q:
        shareholders = ownership.get("shareholders_over_10_percent", [])
        if not shareholders:
            return "No shareholders above 10% are identified in the current CDD output."
        rows = [
            (
                f"{row.get('name')} - {row.get('type')}, "
                f"{row.get('effective_shareholding_percent')}%"
            )
            for row in shareholders
        ]
        return "Shareholders above 10%: " + "; ".join(rows) + "."

    if "related" in q or "director" in q or "officer" in q:
        parties = ownership.get("related_parties", [])
        if not parties:
            return "No related parties are identified in the current CDD output."
        rows = [
            f"{row.get('name')} ({row.get('role')} of {row.get('related_entity')})"
            for row in parties
        ]
        return "Related parties: " + "; ".join(rows) + "."

    if "risk" in q or "review" in q or "flag" in q or "why" in q:
        if not risk_flags:
            return "There are no open risk flags stored in the current graph state."
        rows = [
            f"{flag.get('severity', 'unknown').title()}: {flag.get('description')}"
            for flag in risk_flags
        ]
        return "Current review items: " + "; ".join(rows)

    name = _possible_person_name(question)
    if name and ("nationality" in q or "address" in q or "aml" in q):
        member = _find_member(name, evidence)
        if member:
            parts = [f"{member.get('name')} is listed as {member.get('role')}."]
            if "nationality" in q and member.get("nationality"):
                parts.append(f"Nationality: {member.get('nationality')}.")
            if "address" in q and member.get("address"):
                parts.append(f"Address: {member['address'].get('full_address')}.")
            if "aml" in q and member.get("kyc"):
                parts.append(f"AML details: {json.dumps(member.get('kyc'))}.")
            return " ".join(parts)

    return None


def _fallback_answer(question: str, snippets: list[dict[str, Any]]) -> str:
    if not snippets:
        return "I could not find relevant CDD or evidence for that question."
    return (
        "I found relevant evidence, but OpenAI Q&A is not enabled or available. "
        "Relevant sources: "
        + "; ".join(
            str(item.get("tool") or item.get("source") or item.get("description"))
            for item in snippets
        )
        + "."
    )


def _openai_qa_enabled() -> bool:
    flag = os.getenv("OPENAI_QA_ENABLED")
    if flag is not None and flag.strip().casefold() in {"0", "false", "no", "n", "off"}:
        return False
    return bool(os.getenv("OPENAI_API_KEY"))


def _find_member(name: str, evidence: list[dict[str, Any]]) -> dict[str, Any] | None:
    target = name.casefold()
    for item in evidence:
        data = item.get("data") or {}
        for field in ("controlling_members", "shareholders_and_beneficial_owners", "ultimate_beneficial_owners"):
            for member in data.get(field, []) if isinstance(data, dict) else []:
                if target in str(member.get("name", "")).casefold():
                    return member
    return None


def _possible_person_name(question: str) -> str | None:
    match = re.search(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,4})\b", question)
    return match.group(1) if match else None


def _tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", text.casefold()) if len(token) > 2}


def _score(candidate: dict[str, Any], tokens: set[str]) -> int:
    text = json.dumps(candidate, default=str).casefold()
    return sum(1 for token in tokens if token in text)


def _trim(value: Any, max_chars: int = 4000) -> Any:
    text = json.dumps(value, default=str)
    if len(text) <= max_chars:
        return value
    return text[:max_chars] + "...[truncated]"
