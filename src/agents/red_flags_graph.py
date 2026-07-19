"""Focused LangGraph subgraph for CDD red-flag indicators."""

from __future__ import annotations

from datetime import UTC, datetime
from operator import add
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, StateGraph

from src.tools.csp_detector import CSPAssessmentError, evaluate_csp_address


class RedFlagState(TypedDict, total=False):
    customer_static: dict[str, Any]
    ownership_and_control: dict[str, Any]
    evidence: Annotated[list[dict[str, Any]], add]
    risk_flags: Annotated[list[dict[str, Any]], add]


def build_red_flags_graph():
    """Build the independent red-flags assessment subgraph."""
    graph = StateGraph(RedFlagState)
    graph.add_node("check_ownership_gap", check_ownership_gap)
    graph.add_node("check_member_aml", check_member_aml)
    graph.add_node("check_csp_address", check_csp_address)
    graph.set_entry_point("check_ownership_gap")
    graph.add_edge("check_ownership_gap", "check_member_aml")
    graph.add_edge("check_member_aml", "check_csp_address")
    graph.add_edge("check_csp_address", END)
    return graph.compile()


def run_red_flags_graph(
    *, customer_static: dict[str, Any], ownership_and_control: dict[str, Any]
) -> dict[str, Any]:
    """Run indicators against a snapshot of completed CDD fields."""
    return build_red_flags_graph().invoke(
        {
            "customer_static": customer_static,
            "ownership_and_control": ownership_and_control,
            "evidence": [],
            "risk_flags": [],
        }
    )


def check_ownership_gap(state: RedFlagState) -> dict[str, Any]:
    ubos = state.get("ownership_and_control", {}).get("ubos") or []
    if not ubos:
        return {
            "risk_flags": [
                _flag(
                    "ownership",
                    "medium",
                    "Ownership: Evaluation: Yes. No individual UBO above 25% was identified.",
                    "org_chart",
                )
            ]
        }
    names = ", ".join(str(ubo.get("name")) for ubo in ubos if ubo.get("name"))
    return {
        "risk_flags": [
            _flag(
                "ownership",
                "low",
                f"Ownership: Evaluation: No. Individual UBOs above 25% were identified: {names or 'available in ownership data'}.",
                "org_chart",
                status="cleared",
            )
        ]
    }


def check_member_aml(state: RedFlagState) -> dict[str, Any]:
    flags = []
    members = state.get("ownership_and_control", {}).get("members", {}).get("controlling_members", [])
    for member in members:
        if (member.get("kyc") or {}).get("is_aml_positive"):
            flags.append(
                _flag(
                    "aml",
                    "high",
                    f"AML: Evaluation: Yes. AML review flag for {member.get('name')}.",
                    "members",
                )
            )
    if flags:
        return {"risk_flags": flags}
    return {
        "risk_flags": [
            _flag(
                "aml",
                "low",
                "AML: Evaluation: No. No controlling member has an AML-positive result.",
                "members",
                status="cleared",
            )
        ]
    }


def check_csp_address(state: RedFlagState) -> dict[str, Any]:
    customer = state.get("customer_static", {})
    address = (customer.get("registered_address") or {}).get("full_address")
    company_name = customer.get("name")
    if not address:
        return {"evidence": [_evidence("Skipped CSP address assessment because no registered address is available.", {"status": "skipped", "reason": "registered_address_missing"})]}
    try:
        result = evaluate_csp_address(address, company_name=company_name)
    except CSPAssessmentError as exc:
        return {"evidence": [_evidence("CSP address assessment could not be completed.", {"status": "unavailable", "registered_address": address, "reason": str(exc)})]}

    assessment = result.get("assessment") or {}
    outcome = str(assessment.get("is_csp") or "inconclusive").casefold()
    explanation = str(assessment.get("explanation") or "").strip()
    status = "open" if outcome in {"yes", "inconclusive"} else "cleared"
    severity = "medium" if outcome in {"yes", "inconclusive"} else "low"
    outcome_label = outcome.title()
    return {
        "evidence": [_evidence("Assessed registered address for company service provider indicators.", result)],
        # Keep a completed No assessment in risk_flags with a cleared status so
        # the UI can show that the check ran without affecting recommendation.
        "risk_flags": [
            _flag(
                "csp_address",
                severity,
                f"CSP: Evaluation: {outcome_label}. {explanation}".strip(),
                "csp_address_assessment",
                evidence_tool="csp_address_assessment",
                evidence=result,
            ) | {"status": status}
        ],
    }


def _flag(category: str, severity: str, description: str, source: str, **extra: Any) -> dict[str, Any]:
    return {"category": category, "severity": severity, "description": description, "source": source, "status": "open", **extra}


def _evidence(description: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": "CDD" if data.get("status") == "skipped" else "Tavily/OpenAI",
        "tool": "csp_address_assessment",
        "description": description,
        "relevance_tags": ["risk_flag", "csp_address", "registered_address"],
        "data": data,
        "collected_at": datetime.now(UTC).isoformat(),
    }
