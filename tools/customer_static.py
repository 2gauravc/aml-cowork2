#!/usr/bin/env python3
"""
Fetch and clean static customer/company profile data from the KYC Public API.

Use this tool for the company business profile basics: company name, company
type, registration number, status, registration/incorporation dates, total
shares, share capital, activity type, previous names, and registered address.
For ownership and control, use tools/orgchart.py or tools/members.py.

The main callable for future LLM tool binding is:
    get_customer_static_by_name(company_name, jurisdiction)

For local testing:
    python tools/customer_static.py --company-name "Ubizense Limited" --jurisdiction HK
    python tools/customer_static.py --from-file company-detail.json
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

FIELD_ALIASES = {
    "company_type": (
        "Company Type",
        "Company Category",
        "Entity Type",
        "Legal Form",
        "Legal Type",
        "Organisation Type",
        "Organization Type",
        "Type",
    ),
    "registration_number": (
        "Registration Number",
        "Registration number",
        "Company Number",
        "Company No",
        "Company No.",
        "Entity Number",
        "Business Registration Number",
        "Registry Number",
        "CR Number",
    ),
    "former_company_number": (
        "Former Company Number",
        "Previous Company Number",
        "Old Company Number",
    ),
    "company_status": (
        "Company Status",
        "Status",
        "Entity Status",
        "Current Status",
        "Registration Status",
    ),
    "activity_type": (
        "Activity Type",
        "Business Activity",
        "Principal Activity",
        "Nature of Business",
        "Industry",
        "SIC",
        "SIC Code",
    ),
    "total_shares": (
        "Total shares",
        "Total Shares",
        "Number of Shares",
        "Issued Shares",
        "Shares Issued",
        "Total Issued Shares",
    ),
    "share_capital": (
        "Share capital",
        "Share Capital",
        "Capital",
    ),
    "paid_up_capital": (
        "Paid Up Capital",
        "Paid-up Capital",
        "Paid up capital",
        "Paid-up share capital",
        "Paid Up Share Capital",
    ),
    "registration_date": (
        "Registration Date",
        "Registered On",
        "Date Registered",
        "Registration date",
    ),
    "incorporation_date": (
        "Incorporation Date",
        "Creation Date",
        "Date of Incorporation",
        "Incorporated On",
        "Formation Date",
        "Established Date",
    ),
    "creation_date": (
        "Creation Date",
        "Created Date",
        "Date Created",
    ),
    "previous_names": (
        "Previous names",
        "Previous Names",
        "Former Names",
        "Former Company Names",
        "Previous Company Names",
    ),
}

CAPITAL_FIELD_MAPPINGS = (
    {
        "canonical_type": "paid_up_capital",
        "display_label": "Paid-up Capital",
        "confidence": "exact",
        "aliases": (
            "Paid Up Capital",
            "Paid-up Capital",
            "Paid up capital",
            "Paid-up share capital",
            "Paid Up Share Capital",
        ),
    },
    {
        "canonical_type": "issued_share_capital",
        "display_label": "Issued Share Capital",
        "confidence": "exact",
        "aliases": (
            "Issued Share Capital",
            "Issued Capital",
            "Total Issued Share Capital",
        ),
    },
    {
        "canonical_type": "share_capital",
        "display_label": "Share Capital",
        "confidence": "source_label",
        "aliases": (
            "Share capital",
            "Share Capital",
            "Capital",
        ),
    },
)

CAPITAL_DISPLAY_PRIORITY = {
    "paid_up_capital": 0,
    "issued_share_capital": 1,
    "share_capital": 2,
}


def _fetch_customer_static(
    case_id: int | str,
    *,
    client: KycClient,
) -> dict[str, Any]:
    """Internal helper that fetches company detail after a case has been created."""
    try:
        resp = client.request("GET", f"/v2/Companies/{case_id}")
        resp.raise_for_status()
        return clean_customer_static_response(resp.json(), case_id=case_id)
    except Exception as exc:
        return _error_response(exc, stage="fetch_customer_static", case_id=case_id)


def get_customer_static_by_name(
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
    case to be ready, then returns static company profile data.

    Use this for the Company Business Profile section of CDD: legal name,
    company type, registration number, company status, registration or
    incorporation dates, total shares, share capital, activity type, previous
    names, and registered address. This does not return ownership/control
    tables; use get_company_org_chart_by_name for that.

    Args:
        company_name (str): The company name to search for in the registry.
        jurisdiction (str): The company jurisdiction code, for example "HK".
        wait_until_ready (bool): Whether to wait for the created case to become
            ready before fetching static data. Defaults to True.
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
        dict[str, Any]: Cleaned static company profile and case metadata. On
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

        static = _fetch_customer_static(case_result["case_id"], client=client)
        if static.get("error"):
            static["case"] = case_result
            return static

        static["case"] = case_result
        return static
    except Exception as exc:
        return _error_response(
            exc,
            stage="create_case_and_fetch_customer_static",
            company_name=company_name,
            jurisdiction=jurisdiction,
            wait=wait_config,
        )


def clean_customer_static_response(
    company_response: dict[str, Any],
    *,
    case_id: int | str | None = None,
) -> dict[str, Any]:
    """Reduce the raw company-detail payload to static customer profile fields."""
    details = company_response.get("caseDetail", {}).get("details", {})
    common = details.get("common") or {}
    company = details.get("company") or {}
    address = details.get("caseAddress") or {}
    properties = _clean_properties(company.get("properties"))
    capital_fields = _capital_fields(properties)

    cleaned = {
        "case_id": case_id or common.get("caseCommonId") or company.get("caseCommonId"),
        "customer_static": {
            "name": company.get("entityName"),
            "company_type": _first_value(
                company.get("type"),
                _property_value(properties, "company_type"),
            ),
            "registration_number": _property_value(properties, "registration_number"),
            "former_company_number": _property_value(
                properties, "former_company_number"
            ),
            "company_status": _first_value(
                _property_value(properties, "company_status"),
                common.get("statusName"),
                common.get("status"),
            ),
            "activity_type": _property_value(properties, "activity_type"),
            "total_shares": _property_value(properties, "total_shares"),
            "share_capital": _property_value(properties, "share_capital"),
            "paid_up_capital": _property_value(properties, "paid_up_capital"),
            "capital_fields": capital_fields,
            "display_capital": _display_capital(capital_fields),
            "registration_date": _property_value(properties, "registration_date"),
            "incorporation_date": _first_value(
                _property_value(properties, "incorporation_date"),
                _property_value(properties, "creation_date"),
            ),
            "creation_date": _property_value(properties, "creation_date"),
            "previous_names": _property_value(properties, "previous_names"),
            "jurisdiction": company.get("countryCodeISO31662")
            or address.get("countryCodeISO31662"),
            "registered_address": _address(address),
            "registry_properties": properties,
            "sources": _company_identity_sources(details.get("stepDataSource")),
        },
    }
    return _drop_empty(cleaned)


def _capital_fields(properties: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(properties, dict):
        return []

    fields = []
    seen = set()
    for mapping in CAPITAL_FIELD_MAPPINGS:
        for alias in mapping["aliases"]:
            value, source_label = _property_with_source(properties, alias)
            if value in (None, "", "-", [], {}):
                continue
            key = (mapping["canonical_type"], source_label, json.dumps(value, sort_keys=True, default=str))
            if key in seen:
                continue
            seen.add(key)
            fields.append(
                {
                    "canonical_type": mapping["canonical_type"],
                    "label": mapping["display_label"],
                    "source_label": source_label,
                    "value": value,
                    "confidence": mapping["confidence"],
                }
            )
    return fields


def _display_capital(capital_fields: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not capital_fields:
        return None

    selected = min(
        capital_fields,
        key=lambda item: CAPITAL_DISPLAY_PRIORITY.get(item.get("canonical_type"), 99),
    )
    return {
        "label": selected.get("label") or selected.get("source_label") or "Capital",
        "source_label": selected.get("source_label"),
        "value": selected.get("value"),
        "canonical_type": selected.get("canonical_type"),
        "confidence": selected.get("confidence"),
    }


def _property_value(properties: dict[str, Any] | None, field: str) -> Any:
    if not isinstance(properties, dict):
        return None

    aliases = FIELD_ALIASES.get(field, (field,))
    for alias in aliases:
        value = _property(properties, alias)
        if value not in (None, "", "-", [], {}):
            return value
    return None


def _property_with_source(properties: dict[str, Any], key: str) -> tuple[Any, str | None]:
    if key in properties:
        return properties[key], key

    normalized = _normalize_key(key)
    for existing_key, value in properties.items():
        if _normalize_key(existing_key) == normalized:
            return value, existing_key
    return None, None


def _property(properties: dict[str, Any], key: str) -> Any:
    if key in properties:
        return properties[key]

    normalized = _normalize_key(key)
    for existing_key, value in properties.items():
        if _normalize_key(existing_key) == normalized:
            return value
    return None


def _normalize_key(key: str) -> str:
    return "".join(char for char in key.casefold() if char.isalnum())


def _first_value(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", "-", [], {}):
            return value
    return None


def _address(address: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(address, dict):
        return None

    return _drop_empty(
        {
            "full_address": address.get("address") or address.get("rawAddress"),
            "raw_address": address.get("rawAddress"),
            "address_line_1": address.get("addressLine1"),
            "address_line_2": address.get("addressLine2"),
            "city": address.get("city"),
            "state_province": address.get("stateProvince"),
            "postcode": address.get("postcode"),
            "country": address.get("country"),
            "country_code": address.get("countryCodeISO31662"),
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


def _company_identity_sources(
    step_data_sources: list[dict[str, Any]] | None,
) -> list[dict[str, Any]] | None:
    if not isinstance(step_data_sources, list):
        return None

    seen = set()
    sources = []
    for step in step_data_sources:
        if step.get("stepName") != "Company Identity":
            continue

        for item in step.get("dataSources") or []:
            if not isinstance(item, dict):
                continue

            key = (
                item.get("title"),
                item.get("source"),
                item.get("sourceDomain"),
                item.get("collectionDateTimestamp"),
            )
            if key in seen or not any(key):
                continue

            seen.add(key)
            sources.append(
                _drop_empty(
                    {
                        "field": item.get("title"),
                        "source": item.get("source"),
                        "domain": item.get("sourceDomain"),
                        "collected_at": item.get("collectionDateTimestamp"),
                    }
                )
            )
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
    parser = argparse.ArgumentParser(
        description="Fetch and clean static company/customer profile data"
    )
    parser.add_argument("--company-name", help="Company name to search and create")
    parser.add_argument("--jurisdiction", help='Jurisdiction code, e.g. "HK"')
    parser.add_argument(
        "--from-file",
        help="Clean an existing raw company detail JSON file instead of calling the API",
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
            result = clean_customer_static_response(json.load(fh))
    elif args.company_name or args.jurisdiction:
        if not args.company_name or not args.jurisdiction:
            parser.error("--company-name and --jurisdiction must be provided together")
        result = get_customer_static_by_name(
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
