"""LangGraph chatbot agent with LLM tool calling and message state."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any, TypedDict

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
    messages_from_dict,
    messages_to_dict,
)
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from openai import OpenAIError
from pydantic import BaseModel, Field

from src.agents.graph import run_cdd_agent_state
from src.agents.qa import answer_cdd_question
from src.tools.case_finder import find_test_cases
from src.tools.customer_static import get_customer_static_by_name
from src.tools.members import get_company_members_by_name
from src.tools.orgchart import get_company_org_chart_by_name
from src.utils.pdf import render_cdd_pdf


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CASES_PATH = PROJECT_ROOT / "registry_list_of_mock_cases" / "kyc-sandbox-test-cases.json"


class ChatGraphState(TypedDict, total=False):
    messages: list[BaseMessage]
    session: dict[str, Any]
    user_message: str
    status: str
    error: str | None


class ListJurisdictionsArgs(BaseModel):
    query: str | None = Field(
        default=None,
        description="Optional country, place, jurisdiction code, or partial name to match.",
    )


class FindTestCasesArgs(BaseModel):
    query: str | None = Field(default=None, description="Company/entity name search text.")
    jurisdiction: str | None = Field(default=None, description="Jurisdiction code such as HK or GB.")
    country: str | None = Field(default=None, description="Natural country/place name.")
    origin: str | None = Field(default=None, description="Case source such as golden or synthetic.")
    limit: int = Field(default=10, ge=1, le=25)
    view: str | None = Field(
        default=None,
        description='Use "jurisdiction_counts" for counts by jurisdiction; otherwise return entities.',
    )


class NamedCompanyArgs(BaseModel):
    company_name: str = Field(description="Company/customer legal name.")
    jurisdiction: str = Field(description="Jurisdiction code such as HK or GB.")


class FullCddArgs(BaseModel):
    customer_name: str = Field(description="Company/customer legal name.")
    jurisdiction: str = Field(description="Jurisdiction code such as HK or GB.")
    case_id: str | None = Field(default=None, description="Optional sandbox case id.")


class GeneratePdfArgs(BaseModel):
    pass


class AnswerContextArgs(BaseModel):
    question: str = Field(description="Question to answer from the current CDD/evidence context.")


SYSTEM_PROMPT = """
You are a CDD onboarding assistant with tools.

Use tools instead of guessing facts. Keep track of the conversation through the
message history. If a prior tool call failed because a required parameter was
missing, treat the user's next short answer as the missing value when sensible.

Available workflows:
- Use list_jurisdictions to inspect valid jurisdiction codes or normalize place
  names before calling a jurisdiction-specific tool.
- Use find_test_cases for sandbox/test entity lookup and jurisdiction counts.
- Use get_customer_static_by_name for customer static/profile information.
- Use get_company_members_by_name for directors/shareholders/members.
- Use get_company_org_chart_by_name for ownership/org chart information.
- Use run_full_cdd_pipeline for a full CDD run.
- Use generate_pdf only after a CDD exists.
- Use answer_from_context for questions about the current CDD/evidence.

Rules:
- Do not list sandbox cases when the user is trying to complete missing inputs
  for customer static, members, org chart, or full CDD.
- If a required company name or jurisdiction is missing, ask a short follow-up.
- Prefer jurisdiction codes in tool calls. For example, Hong Kong -> HK,
  England/UK/United Kingdom -> GB when list_jurisdictions confirms GB exists.
- After tool results, provide a concise final answer and do not invent facts.
"""


def run_chat_graph(
    *,
    session: dict[str, Any],
    user_message: str,
    generate_pdf: bool = False,
) -> dict[str, Any]:
    """Run the chatbot graph and return merged session/status fields."""
    working_session = deepcopy(session)
    if generate_pdf:
        working_session["generate_pdf"] = True

    if not os.getenv("OPENAI_API_KEY"):
        return _run_fallback_chat(session=working_session, user_message=user_message)

    graph = _build_chat_graph()
    state: ChatGraphState = {
        "messages": _messages_from_session(working_session),
        "session": working_session,
        "user_message": user_message,
    }
    result = graph.invoke(state)
    final_session = result.get("session", working_session)
    final_session["agent_messages"] = messages_to_dict(result.get("messages", []))
    return {
        "session": final_session,
        "status": result.get("status", "answered"),
        "error": result.get("error"),
    }


def _build_chat_graph():
    graph = StateGraph(ChatGraphState)
    graph.add_node("agent", _agent_node)
    graph.add_node("tools", _tools_node)

    graph.set_entry_point("agent")
    graph.add_conditional_edges(
        "agent",
        _route_after_agent,
        {
            "tools": "tools",
            "end": END,
        },
    )
    graph.add_edge("tools", "agent")
    return graph.compile()


def _agent_node(state: ChatGraphState) -> dict[str, Any]:
    messages = state.get("messages", [])
    llm = ChatOpenAI(
        model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        temperature=0,
        timeout=30,
    ).bind_tools(_tool_specs())
    try:
        response = llm.invoke(messages)
    except OpenAIError as exc:
        session = deepcopy(state.get("session", {}))
        content = f"Request failed: {exc}"
        session.setdefault("messages", []).append({"role": "assistant", "content": content})
        return {
            "messages": [*messages, AIMessage(content=content)],
            "session": session,
            "status": "error",
            "error": str(exc),
        }

    next_messages = [*messages, response]
    if not getattr(response, "tool_calls", None):
        session = deepcopy(state.get("session", {}))
        content = str(response.content or "")
        if content:
            session.setdefault("messages", []).append({"role": "assistant", "content": content})
        return {"messages": next_messages, "session": session, "status": "answered"}
    return {"messages": next_messages}


def _route_after_agent(state: ChatGraphState) -> str:
    last = state.get("messages", [])[-1] if state.get("messages") else None
    if isinstance(last, AIMessage) and last.tool_calls:
        return "tools"
    return "end"


def _tools_node(state: ChatGraphState) -> dict[str, Any]:
    messages = state.get("messages", [])
    session = deepcopy(state.get("session", {}))
    last = messages[-1] if messages else None
    tool_messages: list[ToolMessage] = []

    if not isinstance(last, AIMessage):
        return {"messages": messages, "session": session}

    for call in last.tool_calls:
        name = call.get("name", "")
        args = dict(call.get("args") or {})
        result = _execute_tool_call(name, args, session)
        _record_tool_result(session, name, result)
        tool_messages.append(
            ToolMessage(
                content=json.dumps(result, default=str),
                tool_call_id=call.get("id") or name,
                name=name,
                status="error" if result.get("error") else "success",
            )
        )

    return {
        "messages": [*messages, *tool_messages],
        "session": session,
        "status": "tool_complete",
    }


def _execute_tool_call(name: str, args: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
    try:
        if name == "list_jurisdictions":
            return _list_jurisdictions(query=args.get("query"))
        if name == "find_test_cases":
            return find_test_cases(
                query=args.get("query"),
                jurisdiction=args.get("jurisdiction"),
                country=args.get("country"),
                origin=args.get("origin"),
                view=args.get("view"),
                limit=int(args.get("limit") or 10),
            )
        if name == "get_customer_static_by_name":
            return _run_named_company_tool(
                get_customer_static_by_name,
                args=args,
                session=session,
            )
        if name == "get_company_members_by_name":
            return _run_named_company_tool(
                get_company_members_by_name,
                args=args,
                session=session,
            )
        if name == "get_company_org_chart_by_name":
            return _run_named_company_tool(
                get_company_org_chart_by_name,
                args=args,
                session=session,
            )
        if name == "run_full_cdd_pipeline":
            return _run_full_cdd_tool(args=args, session=session)
        if name == "generate_pdf":
            return _generate_pdf_tool(session=session)
        if name == "answer_from_context":
            return {
                "answer": answer_cdd_question(
                    question=args.get("question") or "",
                    cdd=session.get("cdd", {}),
                    evidence=session.get("evidence", []),
                    risk_flags=session.get("risk_flags", []),
                )
            }
        return {"error": {"message": f"Unknown tool: {name}"}}
    except Exception as exc:
        return {"error": {"type": exc.__class__.__name__, "message": str(exc)}}


def _tool_specs() -> list[StructuredTool]:
    return [
        StructuredTool.from_function(
            name="list_jurisdictions",
            description="List valid sandbox jurisdiction codes, optionally filtered by place/name/code.",
            func=lambda query=None: _list_jurisdictions(query=query),
            args_schema=ListJurisdictionsArgs,
        ),
        StructuredTool.from_function(
            name="find_test_cases",
            description="Find sandbox/test cases or aggregate counts by jurisdiction.",
            func=lambda **kwargs: kwargs,
            args_schema=FindTestCasesArgs,
        ),
        StructuredTool.from_function(
            name="get_customer_static_by_name",
            description="Fetch static/company profile information for a named company in a jurisdiction.",
            func=lambda **kwargs: kwargs,
            args_schema=NamedCompanyArgs,
        ),
        StructuredTool.from_function(
            name="get_company_members_by_name",
            description="Fetch company members, directors, shareholders, or related members.",
            func=lambda **kwargs: kwargs,
            args_schema=NamedCompanyArgs,
        ),
        StructuredTool.from_function(
            name="get_company_org_chart_by_name",
            description="Fetch ownership and organization chart information for a company.",
            func=lambda **kwargs: kwargs,
            args_schema=NamedCompanyArgs,
        ),
        StructuredTool.from_function(
            name="run_full_cdd_pipeline",
            description="Run the full CDD pipeline for a company and jurisdiction.",
            func=lambda **kwargs: kwargs,
            args_schema=FullCddArgs,
        ),
        StructuredTool.from_function(
            name="generate_pdf",
            description="Generate a PDF for the current completed CDD.",
            func=lambda: {},
            args_schema=GeneratePdfArgs,
        ),
        StructuredTool.from_function(
            name="answer_from_context",
            description="Answer a question from the current CDD/evidence already in session.",
            func=lambda **kwargs: kwargs,
            args_schema=AnswerContextArgs,
        ),
    ]


def _list_jurisdictions(query: str | None = None) -> dict[str, Any]:
    try:
        cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"error": {"type": exc.__class__.__name__, "message": str(exc)}}

    rows_by_code: dict[str, dict[str, Any]] = {}
    for case in cases:
        code = str(case.get("jurisdiction") or "").strip().upper()
        if not code:
            continue
        country = case.get("country_name") or case.get("country") or ""
        row = rows_by_code.setdefault(
            code,
            {"jurisdiction": code, "countries": set(), "case_count": 0},
        )
        row["case_count"] += 1
        if country:
            row["countries"].add(str(country))

    rows = []
    normalized_query = str(query or "").strip().casefold()
    aliases = {
        "england": "GB",
        "great britain": "GB",
        "scotland": "GB",
        "uk": "GB",
        "united kingdom": "GB",
        "wales": "GB",
        "hong kong": "HK",
    }
    alias_code = aliases.get(normalized_query)
    for row in rows_by_code.values():
        countries = sorted(row["countries"])
        haystack = " ".join([row["jurisdiction"], *countries]).casefold()
        if normalized_query and normalized_query not in haystack and alias_code != row["jurisdiction"]:
            continue
        rows.append(
            {
                "jurisdiction": row["jurisdiction"],
                "countries": countries,
                "case_count": row["case_count"],
            }
        )

    rows.sort(key=lambda item: item["jurisdiction"])
    return {
        "query": query,
        "jurisdictions": rows,
        "count": len(rows),
    }


def _run_named_company_tool(tool_func, *, args: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
    company_name = args.get("company_name") or args.get("customer_name") or session.get("customer_name")
    jurisdiction = args.get("jurisdiction") or session.get("jurisdiction")
    missing = []
    if not company_name:
        missing.append("company_name")
    if not jurisdiction:
        missing.append("jurisdiction")
    if missing:
        return {
            "error": {
                "message": "Missing required input: " + ", ".join(missing),
                "missing": missing,
            }
        }

    session["customer_name"] = company_name
    session["jurisdiction"] = str(jurisdiction).strip().upper()
    return tool_func(company_name, session["jurisdiction"])


def _run_full_cdd_tool(*, args: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
    customer_name = args.get("customer_name") or args.get("company_name") or session.get("customer_name")
    jurisdiction = args.get("jurisdiction") or session.get("jurisdiction")
    case_id = args.get("case_id") or session.get("case_id")
    missing = []
    if not customer_name:
        missing.append("customer_name")
    if not jurisdiction:
        missing.append("jurisdiction")
    if missing:
        return {
            "error": {
                "message": "Missing required input: " + ", ".join(missing),
                "missing": missing,
            }
        }

    graph_state = run_cdd_agent_state(
        customer_name=customer_name,
        jurisdiction=str(jurisdiction).strip().upper(),
        case_id=case_id,
    )
    cdd = graph_state.get("cdd", {})
    session["customer_name"] = customer_name
    session["jurisdiction"] = str(jurisdiction).strip().upper()
    if case_id:
        session["case_id"] = case_id
    session["cdd"] = cdd
    session["graph_state"] = graph_state
    session["evidence"] = graph_state.get("evidence", [])
    session["risk_flags"] = graph_state.get("risk_flags", [])
    session["final_recommendation"] = graph_state.get("final_recommendation")
    return {
        "cdd": cdd,
        "evidence_count": len(session["evidence"]),
        "risk_flags": session["risk_flags"],
        "final_recommendation": session["final_recommendation"],
    }


def _generate_pdf_tool(*, session: dict[str, Any]) -> dict[str, Any]:
    if not session.get("cdd"):
        return {"error": {"message": "Run the full CDD pipeline before generating a PDF."}}
    pdf_path = render_cdd_pdf(session["cdd"])
    session["pdf_path"] = str(pdf_path)
    return {"pdf_path": str(pdf_path), "message": "PDF generated and ready to download."}


def _record_tool_result(session: dict[str, Any], tool_name: str, result: dict[str, Any]) -> None:
    session.setdefault("tool_results", []).append({"tool": tool_name, "data": result})
    if tool_name == "list_jurisdictions":
        return
    session.setdefault("evidence", []).append(
        {
            "source": "tool",
            "tool": tool_name,
            "description": f"Result from {tool_name}",
            "relevance_tags": [tool_name],
            "data": result,
        }
    )


def _messages_from_session(session: dict[str, Any]) -> list[BaseMessage]:
    if session.get("agent_messages"):
        try:
            messages = messages_from_dict(session["agent_messages"])
        except Exception:
            messages = []
    else:
        messages = []

    if not messages or not isinstance(messages[0], SystemMessage):
        messages = [SystemMessage(content=SYSTEM_PROMPT), *messages]

    user_message = session.get("messages", [])[-1] if session.get("messages") else {}
    if user_message.get("role") == "user":
        content = user_message.get("content", "")
        if not _last_human_message_matches(messages, content):
            messages.append(HumanMessage(content=content))
    return messages


def _last_human_message_matches(messages: list[BaseMessage], content: str) -> bool:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return str(message.content) == content
    return False


def _run_fallback_chat(*, session: dict[str, Any], user_message: str) -> dict[str, Any]:
    content = (
        "The tool-calling chatbot requires OPENAI_API_KEY. "
        "Please set it to use the LangGraph LLM-with-tools flow."
    )
    session.setdefault("messages", []).append({"role": "assistant", "content": content})
    return {"session": session, "status": "llm_unavailable", "error": None}
