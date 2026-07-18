"""CDD LangGraph assembly and CLI runner."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv
from langgraph.graph import END, StateGraph

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from src.agents.nodes import (  # noqa: E402
    build_company_business_profile,
    build_ownership_and_control,
    collect_required_inputs,
    create_or_reuse_case,
    enrich_cdd_from_registry_document,
    establish_idv_requirements,
    evaluate_risk_flags,
    extract_idv_documents,
    extract_registry_document,
    fetch_customer_static,
    fetch_members,
    fetch_org_chart,
    finalize_cdd,
    generate_idv_documents_node,
    generate_registry_document_node,
    has_required_inputs,
)
from src.agents.state import CDDState, new_cdd_state  # noqa: E402
from src.utils.langgraph_debug import maybe_debug_node  # noqa: E402
from src.utils.kyc_cache import get_cache_value  # noqa: E402
from src.utils.pdf import render_cdd_pdf  # noqa: E402


load_dotenv()


PIPELINE_NODE_LABELS = {
    "collect_required_inputs": "Setting up",
    "create_or_reuse_case": "Setting up",
    "fetch_customer_static": "Fetching customer static information from KYC API",
    "fetch_org_chart": "Fetching org chart information from KYC API",
    "fetch_members": "Fetching members from KYC API",
    "build_company_business_profile": "Populating CDD — About the Customer",
    "generate_registry_document": "Generating registry documents",
    "extract_registry_document": "Extracting from registry document",
    "enrich_cdd_from_registry_document": "Populating CDD from registry document",
    "build_ownership_and_control": "Populating CDD — Ownership & Control",
    "establish_idv_requirements": "Establishing ID&V requirements",
    "generate_idv_documents": "Generating ID&V documents",
    "extract_idv_documents": "Extracting from ID&V documents",
    "evaluate_risk_flags": "Evaluating red flags",
    "finalize_cdd": "Completing CDD",
}


def _case_id_from_state(state: dict[str, Any]) -> int | str | None:
    return (state.get("metadata") or {}).get("kyc_case", {}).get("case_id")


def _cache_used_by_node(node_name: str, state: dict[str, Any]) -> bool:
    """Return whether the current fetch node will read an already-cached API result."""
    cache_names = {
        "fetch_customer_static": "company-detail",
        "fetch_org_chart": "company-org-chart",
        "fetch_members": "company-members",
    }
    cache_name = cache_names.get(node_name)
    case_id = _case_id_from_state(state)
    return bool(cache_name and case_id is not None and get_cache_value(cache_name, [case_id]) is not None)


def _progress_node(
    node_name: str,
    func: Callable[[dict[str, Any]], dict[str, Any]],
    progress_callback: Callable[[dict[str, Any]], None] | None,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Wrap a node to make its live execution state available to the UI."""
    if progress_callback is None:
        return func

    node_number = list(PIPELINE_NODE_LABELS).index(node_name) + 1
    minimum_seconds = max(0.0, float(os.getenv("CDD_PIPELINE_NODE_MIN_SECONDS", "3")))

    def wrapped(state: dict[str, Any]) -> dict[str, Any]:
        started = time.monotonic()
        using_cache = _cache_used_by_node(node_name, state)
        progress_callback(
            {
                "node": node_name,
                "node_number": node_number,
                "total_nodes": len(PIPELINE_NODE_LABELS),
                "message": PIPELINE_NODE_LABELS[node_name],
                "using_cache": using_cache,
                "status": "running",
                "started_at": datetime.now(UTC).isoformat(),
            }
        )
        try:
            return func(state)
        except Exception as exc:
            progress_callback(
                {
                    "node": node_name,
                    "node_number": node_number,
                    "total_nodes": len(PIPELINE_NODE_LABELS),
                    "message": PIPELINE_NODE_LABELS[node_name],
                    "using_cache": using_cache,
                    "status": "error",
                    "error": str(exc),
                }
            )
            raise
        finally:
            remaining = minimum_seconds - (time.monotonic() - started)
            if remaining > 0:
                time.sleep(remaining)

    wrapped.__name__ = getattr(func, "__name__", node_name)
    return wrapped


def build_cdd_graph(
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
):
    graph = StateGraph(CDDState)
    def add_node(node_name: str, func: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
        graph.add_node(
            node_name,
            _progress_node(node_name, maybe_debug_node(node_name, func), progress_callback),
        )

    add_node("collect_required_inputs", collect_required_inputs)
    add_node("create_or_reuse_case", create_or_reuse_case)
    add_node("fetch_customer_static", fetch_customer_static)
    add_node("fetch_org_chart", fetch_org_chart)
    add_node("fetch_members", fetch_members)
    add_node("build_company_business_profile", build_company_business_profile)
    add_node("generate_registry_document", generate_registry_document_node)
    add_node("extract_registry_document", extract_registry_document)
    add_node("enrich_cdd_from_registry_document", enrich_cdd_from_registry_document)
    add_node("build_ownership_and_control", build_ownership_and_control)
    add_node("establish_idv_requirements", establish_idv_requirements)
    add_node("generate_idv_documents", generate_idv_documents_node)
    add_node("extract_idv_documents", extract_idv_documents)
    add_node("evaluate_risk_flags", evaluate_risk_flags)
    add_node("finalize_cdd", finalize_cdd)

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
    graph.add_edge("build_ownership_and_control", "establish_idv_requirements")
    graph.add_edge("establish_idv_requirements", "generate_idv_documents")
    graph.add_edge("generate_idv_documents", "extract_idv_documents")
    graph.add_edge("extract_idv_documents", "evaluate_risk_flags")
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
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Run the CDD graph and return the full final LangGraph state."""
    app = build_cdd_graph(progress_callback=progress_callback)
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
        help='Generate a PDF report in outputs/cdd/. Use "--generate-pdf" or "--generate-pdf true".',
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
