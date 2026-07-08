"""LLM intent router for open-ended CDD chatbot messages."""

from __future__ import annotations

import json
import os
from typing import Any, Literal, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from openai import OpenAIError


Action = Literal[
    "find_test_cases",
    "get_customer_static_by_name",
    "get_company_members_by_name",
    "get_company_org_chart_by_name",
    "run_full_cdd_pipeline",
    "answer_from_context",
    "generate_pdf",
    "ask_missing_inputs",
]


class RouteDecision(TypedDict, total=False):
    action: Action
    arguments: dict[str, Any]
    response: str
    reason: str


TOOLS_DESCRIPTION = """
Available actions:
- find_test_cases: list or search available sandbox/test entities. Args: query, jurisdiction, country, origin, limit.
- get_customer_static_by_name: fetch static company profile only. Args: company_name, jurisdiction.
- get_company_members_by_name: fetch direct members/directors/shareholders only. Args: company_name, jurisdiction.
- get_company_org_chart_by_name: fetch recursive ownership/org chart only. Args: company_name, jurisdiction.
- run_full_cdd_pipeline: run the deterministic full CDD graph. Args: company_name, jurisdiction, case_id.
- answer_from_context: answer using existing session CDD/evidence/tool results.
- generate_pdf: generate a PDF from current CDD.
- ask_missing_inputs: ask user for missing fields needed for the requested action.
"""


def route_user_message(
    *,
    message: str,
    session_context: dict[str, Any],
) -> RouteDecision:
    """Ask the LLM to route a user message to a tool, pipeline, or context answer."""
    if not os.getenv("OPENAI_API_KEY"):
        return {
            "action": "ask_missing_inputs",
            "response": "OpenAI API key is required for open-ended tool routing.",
            "reason": "OPENAI_API_KEY is not configured.",
        }

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
                        "You route CDD chatbot requests. Return only valid JSON. "
                        "Do not answer the user directly unless action is "
                        "ask_missing_inputs. Choose the smallest action that satisfies "
                        "the user. If the user asks to list available/sample/test "
                        "entities, use find_test_cases. If the user asks for a partial "
                        "data pull, choose the specific tool, not the full pipeline. "
                        "Use run_full_cdd_pipeline only when the user explicitly asks "
                        "to run/onboard/complete full CDD."
                    )
                ),
                HumanMessage(
                    content=(
                        f"{TOOLS_DESCRIPTION}\n\n"
                        f"Current session context:\n{json.dumps(session_context, default=str)}\n\n"
                        f"User message:\n{message}\n\n"
                        "Return JSON with keys: action, arguments, reason, response. "
                        "Use null for unknown optional arguments."
                    )
                ),
            ]
        )
    except OpenAIError as exc:
        return _openai_unavailable_decision(exc)
    return _parse_route(str(response.content))


def _openai_unavailable_decision(exc: Exception) -> RouteDecision:
    reason = str(exc)
    return {
        "action": "answer_from_context",
        "arguments": {},
        "response": (
            "OpenAI is currently unavailable for chat routing. "
            "If you need full CDD, use the deterministic pipeline panel on the right. "
            "If you already ran CDD, I can still answer some standard ownership, "
            "shareholder, related-party, and risk questions from the stored CDD."
        ),
        "reason": reason,
    }


def _parse_route(content: str) -> RouteDecision:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:].strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {
            "action": "answer_from_context",
            "arguments": {},
            "reason": "Router returned non-JSON output.",
        }

    action = data.get("action")
    valid_actions = set(Action.__args__)  # type: ignore[attr-defined]
    if action not in valid_actions:
        action = "answer_from_context"

    return {
        "action": action,
        "arguments": data.get("arguments") or {},
        "response": data.get("response") or "",
        "reason": data.get("reason") or "",
    }
