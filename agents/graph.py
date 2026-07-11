"""CDD LangGraph assembly and CLI runner."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langgraph.graph import END, StateGraph

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.nodes import (  # noqa: E402
    build_company_business_profile,
    build_ownership_and_control,
    collect_required_inputs,
    create_or_reuse_case,
    enrich_cdd_from_registry_document,
    evaluate_risk_flags,
    extract_registry_document,
    fetch_customer_static,
    fetch_members,
    fetch_org_chart,
    finalize_cdd,
    generate_registry_document_node,
    has_required_inputs,
)
from agents.state import CDDState, new_cdd_state  # noqa: E402
from utils.langgraph_debug import maybe_debug_node  # noqa: E402
from utils.pdf import render_cdd_pdf  # noqa: E402


load_dotenv()


def build_cdd_graph():
    graph = StateGraph(CDDState)
    graph.add_node(
        "collect_required_inputs",
        maybe_debug_node("collect_required_inputs", collect_required_inputs),
    )
    graph.add_node(
        "create_or_reuse_case",
        maybe_debug_node("create_or_reuse_case", create_or_reuse_case),
    )
    graph.add_node(
        "fetch_customer_static",
        maybe_debug_node("fetch_customer_static", fetch_customer_static),
    )
    graph.add_node("fetch_org_chart", maybe_debug_node("fetch_org_chart", fetch_org_chart))
    graph.add_node("fetch_members", maybe_debug_node("fetch_members", fetch_members))
    graph.add_node(
        "build_company_business_profile",
        maybe_debug_node("build_company_business_profile", build_company_business_profile),
    )
    graph.add_node(
        "generate_registry_document",
        maybe_debug_node("generate_registry_document", generate_registry_document_node),
    )
    graph.add_node(
        "extract_registry_document",
        maybe_debug_node("extract_registry_document", extract_registry_document),
    )
    graph.add_node(
        "enrich_cdd_from_registry_document",
        maybe_debug_node(
            "enrich_cdd_from_registry_document",
            enrich_cdd_from_registry_document,
        ),
    )
    graph.add_node(
        "build_ownership_and_control",
        maybe_debug_node("build_ownership_and_control", build_ownership_and_control),
    )
    graph.add_node(
        "evaluate_risk_flags",
        maybe_debug_node("evaluate_risk_flags", evaluate_risk_flags),
    )
    graph.add_node("finalize_cdd", maybe_debug_node("finalize_cdd", finalize_cdd))

    graph.set_entry_point("collect_required_inputs")
    graph.add_conditional_edges(
        "collect_required_inputs",
        has_required_inputs,
        {
            "ready": "create_or_reuse_case",
            "missing_inputs": END,
        },
    )
    graph.add_edge("create_or_reuse_case", "fetch_customer_static")
    graph.add_edge("fetch_customer_static", "fetch_org_chart")
    graph.add_edge("fetch_org_chart", "fetch_members")
    graph.add_edge("fetch_members", "build_company_business_profile")
    graph.add_edge("build_company_business_profile", "generate_registry_document")
    graph.add_edge("generate_registry_document", "extract_registry_document")
    graph.add_edge("extract_registry_document", "enrich_cdd_from_registry_document")
    graph.add_edge("enrich_cdd_from_registry_document", "build_ownership_and_control")
    graph.add_edge("build_ownership_and_control", "evaluate_risk_flags")
    graph.add_edge("evaluate_risk_flags", "finalize_cdd")
    graph.add_edge("finalize_cdd", END)
    return graph.compile()


def run_cdd_agent(
    *,
    customer_name: str | None = None,
    jurisdiction: str | None = None,
    case_id: int | str | None = None,
) -> dict[str, Any]:
    result = run_cdd_agent_state(
        customer_name=customer_name,
        jurisdiction=jurisdiction,
        case_id=case_id,
    )
    return result.get("cdd", {})


def run_cdd_agent_state(
    *,
    customer_name: str | None = None,
    jurisdiction: str | None = None,
    case_id: int | str | None = None,
) -> dict[str, Any]:
    """Run the CDD graph and return the full final LangGraph state."""
    app = build_cdd_graph()
    state = new_cdd_state(
        customer_name=customer_name,
        jurisdiction=jurisdiction,
        case_id=case_id,
    )
    return app.invoke(state)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the CDD LangGraph agent")
    parser.add_argument("--customer-name", help="Customer company name")
    parser.add_argument("--jurisdiction", help='Jurisdiction code, e.g. "HK" or "GB"')
    parser.add_argument("--case-id", help="Existing KYC case ID to reuse")
    parser.add_argument(
        "--generate-pdf",
        nargs="?",
        const="true",
        default="false",
        help='Generate a PDF report in outputs/. Use "--generate-pdf" or "--generate-pdf true".',
    )
    args = parser.parse_args()

    cdd = run_cdd_agent(
        customer_name=args.customer_name,
        jurisdiction=args.jurisdiction,
        case_id=args.case_id,
    )
    if _as_bool(args.generate_pdf):
        pdf_path = render_cdd_pdf(cdd)
        print(f"PDF saved to {pdf_path}", file=sys.stderr)

    json.dump(cdd, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


def _as_bool(value: str | bool | None) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().casefold() in {"1", "true", "yes", "y", "on"}


if __name__ == "__main__":
    main()
