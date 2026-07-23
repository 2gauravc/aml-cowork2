"""Focused LangGraph subgraph for CDD red-flag indicators."""

from __future__ import annotations

from datetime import UTC, datetime
from operator import add
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, StateGraph

from src.tools.csp_detector import CSPAssessmentError, evaluate_csp_address
from src.tools.risk_severity_policy import apply_risk_severity_policy


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
    *,
    customer_static: dict[str, Any],
    ownership_and_control: dict[str, Any],
    severity_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run indicators against a snapshot of completed CDD fields."""
    result = build_red_flags_graph().invoke(
        {
            "customer_static": customer_static,
            "ownership_and_control": ownership_and_control,
            "evidence": [],
            "risk_flags": [],
        }
    )
    if severity_policy:
        result["risk_flags"] = apply_risk_severity_policy(result.get("risk_flags", []), severity_policy)
    return result


def check_ownership_gap(state: RedFlagState) -> dict[str, Any]:
    ownership = state.get("ownership_and_control", {})
    ubos = ownership.get("ubos") or []
    complete = ownership.get("status") == "complete" and (ownership.get("org_chart") or {}).get("status") == "complete"
    if not complete:
        return {"risk_flags": [_finding(
            "ownership", "inconclusive", "org_chart",
            "Ownership data is incomplete or unavailable; effective ownership cannot be determined.",
            evidence={"ownership_status": ownership.get("status"), "org_chart_status": (ownership.get("org_chart") or {}).get("status")},
        )]}
    if not ubos:
        return {"risk_flags": [_finding(
            "ownership", "yes", "org_chart", "No individual UBO above 25% was identified.",
            evidence={"ubos": []},
        )]}
    names = ", ".join(str(ubo.get("name")) for ubo in ubos if ubo.get("name"))
    return {"risk_flags": [_finding(
        "ownership", "no", "org_chart",
        f"Individual UBOs above 25% were identified: {names or 'available in ownership data'}.",
        evidence={"ubos": ubos},
    )]}


def check_member_aml(state: RedFlagState) -> dict[str, Any]:
    ownership = state.get("ownership_and_control", {})
    member_data = ownership.get("members") or {}
    members = member_data.get("controlling_members", [])
    if member_data.get("status") != "complete":
        return {"risk_flags": [_finding(
            "aml", "inconclusive", "members", "KYC member/AML data is unavailable or incomplete.",
            evidence={"members_status": member_data.get("status")},
        )]}
    flags = []
    for member in members:
        value = (member.get("kyc") or {}).get("is_aml_positive")
        evaluation = "yes" if value is True else "no" if value is False else "inconclusive"
        flags.append(_finding(
            "aml", evaluation, "members",
            f"KYC AML result for {member.get('name') or 'controlling member'}: {evaluation.title()}.",
            subject={"name": member.get("name"), "case_common_id": member.get("case_common_id")},
            evidence={"kyc": member.get("kyc") or {}},
        ))
    if flags:
        return {"risk_flags": flags}
    return {"risk_flags": [_finding("aml", "no", "members", "No controlling members require AML assessment.", evidence={"controlling_members": []})]}


def check_csp_address(state: RedFlagState) -> dict[str, Any]:
    customer = state.get("customer_static", {})
    address = (customer.get("registered_address") or {}).get("full_address")
    company_name = customer.get("name")
    if not address:
        result = {"status": "skipped", "reason": "registered_address_missing"}
        return {"evidence": [_evidence("Skipped CSP address assessment because no registered address is available.", result)], "risk_flags": [_finding("csp_address", "inconclusive", "csp_address_assessment", "No registered address was available for CSP assessment.", evidence=result)]}
    try:
        result = evaluate_csp_address(address, company_name=company_name)
    except CSPAssessmentError as exc:
        result = {"status": "unavailable", "registered_address": address, "reason": str(exc)}
        return {"evidence": [_evidence("CSP address assessment could not be completed.", result)], "risk_flags": [_finding("csp_address", "inconclusive", "csp_address_assessment", "CSP address assessment could not be completed.", evidence=result)]}

    assessment = result.get("assessment") or {}
    outcome = str(assessment.get("is_csp") or "inconclusive").casefold()
    explanation = str(assessment.get("explanation") or "").strip()
    return {
        "evidence": [_evidence("Assessed registered address for company service provider indicators.", result)],
        "risk_flags": [_finding("csp_address", outcome if outcome in {"yes", "no", "inconclusive"} else "inconclusive", "csp_address_assessment", explanation or "CSP assessment completed.", evidence=result)],
    }


def _finding(
    category: str,
    evaluation: str,
    source: str,
    description: str,
    *,
    subject: dict[str, Any] | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    subject = {key: value for key, value in (subject or {}).items() if value is not None}
    subject_key = subject.get("case_common_id") or subject.get("name") or "category"
    return {
        "finding_id": f"{category}:{subject_key}",
        "category": category,
        "evaluation": evaluation,
        "severity": "none",
        "description": description,
        "source": source,
        "subject": subject,
        "evidence": evidence or {},
    }


def _evidence(description: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": "CDD" if data.get("status") == "skipped" else "Tavily/OpenAI",
        "tool": "csp_address_assessment",
        "description": description,
        "relevance_tags": ["risk_flag", "csp_address", "registered_address"],
        "data": data,
        "collected_at": datetime.now(UTC).isoformat(),
    }
