#!/usr/bin/env python3
"""
Fetch and clean company members from the KYC Public API.

The main callable for future LLM tool binding is:
    get_company_members_by_name(company_name, jurisdiction)

For local testing:
    python tools/members.py --company-name "Ubizense Limited" --jurisdiction HK
    python tools/members.py --from-file notebooks/members.json
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


def _fetch_company_members(
    case_id: int | str,
    *,
    client: KycClient,
) -> dict[str, Any]:
    """Internal helper that fetches members after a case has been created."""
    try:
        resp = client.request("GET", f"/v2/Companies/{case_id}/members")
        resp.raise_for_status()
        return clean_members_response(resp.json(), case_id=case_id)
    except Exception as exc:
        return _error_response(exc, stage="fetch_members", case_id=case_id)


def get_company_members_by_name(
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
    case to be ready, then returns the company's controlling members,
    shareholders / beneficial owners, and ultimate beneficial owners.

    Args:
        company_name (str): The company name to search for in the registry.
        jurisdiction (str): The company jurisdiction code, for example "HK".
        wait_until_ready (bool): Whether to wait for the created case to become
            ready before fetching members. Defaults to True.
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
        dict[str, Any]: Cleaned ownership information and case metadata. On
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

        members = _fetch_company_members(case_result["case_id"], client=client)
        if members.get("error"):
            members["case"] = case_result
            return members

        members["case"] = case_result
        return members
    except Exception as exc:
        return _error_response(
            exc,
            stage="create_case_and_fetch_members",
            company_name=company_name,
            jurisdiction=jurisdiction,
            wait=wait_config,
        )


def clean_members_response(
    members_response: dict[str, Any],
    *,
    case_id: int | str | None = None,
) -> dict[str, Any]:
    """Reduce the raw members payload to the fields a bot should reason over."""
    cleaned = {
        "case_id": case_id,
        "controlling_members": _clean_member_list(
            members_response.get("controllingEntitiesAndIndividuals", [])
        ),
        "shareholders_and_beneficial_owners": _clean_member_list(
            members_response.get("shareholdersAndBeneficialOwners", [])
        ),
        "ultimate_beneficial_owners": _clean_member_list(
            members_response.get("ultimateBeneficialOwners", [])
        ),
    }
    cleaned["counts"] = {
        "controlling_members": len(cleaned["controlling_members"]),
        "shareholders_and_beneficial_owners": len(
            cleaned["shareholders_and_beneficial_owners"]
        ),
        "ultimate_beneficial_owners": len(cleaned["ultimate_beneficial_owners"]),
    }
    return _drop_empty(cleaned)


def _clean_member_list(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_clean_member_entry(entry) for entry in entries if isinstance(entry, dict)]


def _clean_member_entry(entry: dict[str, Any]) -> dict[str, Any]:
    member = entry.get("member") or {}
    properties = _clean_properties(member.get("properties"))
    member_properties = _clean_properties(member.get("memberProperties"))

    cleaned = {
        "name": _name(member),
        "member_type": entry.get("memberType"),
        "role": entry.get("role"),
        "case_common_id": member.get("caseCommonId"),
        "jurisdiction": member.get("codeISO31662"),
        "nationality": member.get("nationality"),
        "ownership": {
            "percentage": entry.get("percentage"),
            "shares": entry.get("shares"),
        },
        "address": _address(member.get("address")),
        "registry_properties": properties,
        "member_properties": member_properties,
        "kyc": {
            "is_kyced": entry.get("isKYCed"),
            "is_aml_positive": entry.get("isCaseAMLPositive"),
            "aml_summary": _aml_summary(entry.get("caseAmlSummary")),
        },
        "sources": _sources(entry.get("dataSource")),
    }
    return _drop_empty(cleaned)


def _name(member: dict[str, Any]) -> str | None:
    raw_name = member.get("rawName") or member.get("name")
    if raw_name:
        return raw_name

    parts = [member.get("firstName"), member.get("lastName")]
    return " ".join(part for part in parts if part) or None


def _address(address: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(address, dict):
        return None

    return _drop_empty(
        {
            "full_address": address.get("address") or address.get("rawAddress"),
            "country": address.get("country"),
            "country_code": address.get("countryCodeISO31662"),
            "city": address.get("city"),
            "state_province": address.get("stateProvince"),
            "postcode": address.get("postcode"),
        }
    )


def _clean_properties(properties: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(properties, dict):
        return None

    cleaned = {}
    for key, value in properties.items():
        if value in (None, "", "-", [], {}):
            continue
        cleaned[key] = value
    return cleaned or None


def _aml_summary(summary: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(summary, dict):
        return None

    world_check = summary.get("worldCheckSummary") or {}
    lexis_nexis = summary.get("lexisNexisCheckSummary")
    flagged_world_checks = {
        key: value
        for key, value in world_check.items()
        if value not in (None, "", "NA", "NoMatches")
    }

    return _drop_empty(
        {
            "world_check": flagged_world_checks,
            "lexis_nexis": lexis_nexis,
        }
    )


def _sources(data_sources: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    if not isinstance(data_sources, list):
        return None

    seen = set()
    sources = []
    for item in data_sources:
        if not isinstance(item, dict):
            continue

        source = item.get("source")
        source_domain = item.get("sourceDomain")
        key = (source, source_domain)
        if key in seen or not any(key):
            continue

        seen.add(key)
        sources.append(_drop_empty({"source": source, "domain": source_domain}))
    return sources or None


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
    parser = argparse.ArgumentParser(description="Fetch and clean company members")
    parser.add_argument("--company-name", help="Company name to search and create")
    parser.add_argument("--jurisdiction", help='Jurisdiction code, e.g. "HK"')
    parser.add_argument(
        "--from-file",
        help="Clean an existing raw members JSON file instead of calling the API",
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
            result = clean_members_response(json.load(fh))
    elif args.company_name or args.jurisdiction:
        if not args.company_name or not args.jurisdiction:
            parser.error("--company-name and --jurisdiction must be provided together")
        result = get_company_members_by_name(
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
