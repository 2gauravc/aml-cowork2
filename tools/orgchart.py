#!/usr/bin/env python3
"""
Fetch and clean a company org chart from the KYC Public API.

Use this tool for the detailed ownership-structure view: the company, its
officers, direct shareholders, corporate shareholders, and nested shareholders
or persons with significant control behind those entities. This is more detailed
than tools/members.py and may repeat the same person or company where they
appear in multiple roles or relationship paths.

The main callable for future LLM tool binding is:
    get_company_org_chart_by_name(company_name, jurisdiction)

For local testing:
    python tools/orgchart.py --company-name "Ubizense Limited" --jurisdiction HK
    python tools/orgchart.py --from-file notebooks/org-chart.json
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.create_case import (  # noqa: E402
    BASE_URL,
    CLIENT_ID,
    CLIENT_SECRET,
    KycClient,
    create_company_case,
)


def _fetch_company_org_chart(
    case_id: int | str,
    *,
    client: KycClient,
) -> dict[str, Any]:
    """Internal helper that fetches the org chart after a case has been created."""
    try:
        resp = client.request("GET", f"/v2/Companies/{case_id}/org-chart")
        resp.raise_for_status()
        return clean_org_chart_response(resp.json(), case_id=case_id)
    except Exception as exc:
        return _error_response(exc, stage="fetch_org_chart", case_id=case_id)


def get_company_org_chart_by_name(
    company_name: str,
    jurisdiction: str,
    *,
    wait_until_ready: bool = True,
    poll_attempts: int = 60,
    poll_interval_seconds: int = 5,
    base_url: str = BASE_URL,
    client_id: str | None = CLIENT_ID,
    client_secret: str | None = CLIENT_SECRET,
) -> dict[str, Any]:
    """
    Creates a company KYC case by company name and jurisdiction, waits for the
    case to be ready, then returns the company's recursive ownership org chart.

    Use this when the user needs to understand the ownership chain, such as who
    owns the direct shareholder, who has significant control behind a corporate
    owner, or how directors and shareholders relate across the structure. For a
    shorter compliance/member list with addresses, registry properties, and AML
    summary details, use get_company_members_by_name instead.

    Args:
        company_name (str): The company name to search for in the registry.
        jurisdiction (str): The company jurisdiction code, for example "HK".
        wait_until_ready (bool): Whether to wait for the created case to become
            ready before fetching the org chart. Defaults to True.
        poll_attempts (int): Number of readiness checks to perform. Defaults to 60.
        poll_interval_seconds (int): Seconds to wait between readiness checks.
            Defaults to 5.
        base_url (str): KYC API base URL. Defaults to KYCBASEURL from the
            environment, or the development API URL.
        client_id (str | None): KYC API client ID. Defaults to KYCCLIENTID from
            the environment.
        client_secret (str | None): KYC API client secret. Defaults to
            KYCCLIENTSECRET from the environment.

    Returns:
        dict[str, Any]: Cleaned recursive ownership tree and case metadata. On
            failure, returns a dict with an "error" object and context instead
            of raising an exception, so the LLM can explain or recover.
    """
    wait_config = {
        "wait_until_ready": wait_until_ready,
        "poll_attempts": poll_attempts,
        "poll_interval_seconds": poll_interval_seconds,
        "max_wait_seconds": poll_attempts * poll_interval_seconds
        if wait_until_ready
        else 0,
    }

    try:
        if not client_id or not client_secret:
            raise ValueError("KYCCLIENTID and KYCCLIENTSECRET are required")

        client = KycClient(base_url, client_id, client_secret)
        case_result = create_company_case(
            company_name,
            jurisdiction,
            wait_until_ready=wait_until_ready,
            poll_attempts=poll_attempts,
            poll_interval_seconds=poll_interval_seconds,
            client=client,
        )
        case_result["wait"] = wait_config

        if wait_until_ready and not case_result.get("ready"):
            return {
                "case": case_result,
                "message": (
                    "The company case was created but was not ready before the "
                    f"configured {wait_config['max_wait_seconds']} second polling "
                    "window ended. Increase poll_attempts / "
                    "poll_interval_seconds and try again."
                ),
            }

        org_chart = _fetch_company_org_chart(case_result["case_id"], client=client)
        if org_chart.get("error"):
            org_chart["case"] = case_result
            return org_chart

        org_chart["case"] = case_result
        return org_chart
    except Exception as exc:
        return _error_response(
            exc,
            stage="create_case_and_fetch_org_chart",
            company_name=company_name,
            jurisdiction=jurisdiction,
            wait=wait_config,
        )


def clean_org_chart_response(
    org_chart_response: dict[str, Any],
    *,
    case_id: int | str | None = None,
) -> dict[str, Any]:
    """Reduce the raw org-chart payload to a recursive ownership tree."""
    root = _clean_org_chart_node(org_chart_response)
    cleaned = {
        "case_id": case_id or root.get("case_common_id"),
        "org_chart": root,
        "counts": _count_relationships(root),
    }
    return _drop_empty(cleaned)


def _clean_org_chart_node(node: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(node, dict):
        return {}

    cleaned = {
        "name": node.get("name"),
        "role": node.get("role"),
        "case_common_id": node.get("caseCommonId"),
        "jurisdiction_id": node.get("jurisdictionId"),
        "nationality_id": node.get("nationalityId"),
        "ownership": {
            "effective_percentage": node.get("effectivePercentage"),
            "shares": node.get("shares"),
            "is_general_partner": node.get("isGeneralPartner"),
        },
        "kyc": {
            "is_unresolved_aml": node.get("isUnresolvedAML"),
            "is_updated_aml": node.get("isUpdatedAML"),
            "validation": node.get("validation"),
        },
        "officers": _clean_child_nodes(node.get("officers")),
        "shareholders": _clean_child_nodes(node.get("shareholders")),
        "others": _clean_child_nodes(node.get("others")),
        "joint_shareholder_members": _clean_child_nodes(
            node.get("jointShareholderMembers")
        ),
    }
    return _drop_empty(cleaned)


def _clean_child_nodes(value: Any) -> list[dict[str, Any]] | None:
    if not isinstance(value, list):
        return None

    nodes = [_clean_org_chart_node(item) for item in value if isinstance(item, dict)]
    return nodes or None


def _count_relationships(root: dict[str, Any]) -> dict[str, int]:
    counts = {
        "nodes": 0,
        "officers": 0,
        "shareholders": 0,
        "others": 0,
        "joint_shareholder_members": 0,
    }

    def visit(node: dict[str, Any]) -> None:
        counts["nodes"] += 1
        for field in (
            "officers",
            "shareholders",
            "others",
            "joint_shareholder_members",
        ):
            children = node.get(field) or []
            counts[field] += len(children)
            for child in children:
                visit(child)

    if root:
        visit(root)

    return counts


def _drop_empty(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            item = _drop_empty(item)
            if item in (None, "", [], {}):
                continue
            cleaned[key] = item
        return cleaned

    if isinstance(value, list):
        return [_drop_empty(item) for item in value if item not in (None, "", [], {})]

    return value


def _error_response(exc: Exception, **context: Any) -> dict[str, Any]:
    response = getattr(exc, "response", None)
    error = {
        "type": exc.__class__.__name__,
        "message": str(exc),
    }

    if response is not None:
        error["http_status"] = getattr(response, "status_code", None)
        try:
            error["response"] = response.json()
        except ValueError:
            error["response"] = getattr(response, "text", None)

    return _drop_empty({"error": error, "context": context})


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch and clean a company org chart")
    parser.add_argument("--company-name", help="Company name to search and create")
    parser.add_argument("--jurisdiction", help='Jurisdiction code, e.g. "HK"')
    parser.add_argument(
        "--from-file",
        help="Clean an existing raw org-chart JSON file instead of calling the API",
    )
    parser.add_argument(
        "--poll-attempts",
        type=int,
        default=60,
        help="Number of status polling attempts when creating a case",
    )
    parser.add_argument(
        "--poll-interval-seconds",
        type=int,
        default=5,
        help="Seconds between status polling attempts when creating a case",
    )
    args = parser.parse_args()

    if args.from_file:
        with open(args.from_file, encoding="utf-8") as fh:
            result = clean_org_chart_response(json.load(fh))
    elif args.company_name or args.jurisdiction:
        if not args.company_name or not args.jurisdiction:
            parser.error("--company-name and --jurisdiction must be provided together")
        result = get_company_org_chart_by_name(
            args.company_name,
            args.jurisdiction,
            poll_attempts=args.poll_attempts,
            poll_interval_seconds=args.poll_interval_seconds,
        )
    else:
        parser.error("--company-name and --jurisdiction are required unless --from-file is provided")

    json.dump(result, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    if result.get("error"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
