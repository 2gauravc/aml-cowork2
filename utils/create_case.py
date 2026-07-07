#!/usr/bin/env python3
"""
Search a company by name and jurisdiction, then create a KYC company case.

This module is intended as an internal helper for LLM-facing tools.

For local testing:
    python utils/create_case.py "Ubizense Limited" HK
    python utils/create_case.py "Ubizense Limited" HK --no-wait
"""

import argparse
import json
import os
import sys
import time
from typing import Any

import requests
from dotenv import load_dotenv


load_dotenv()

BASE_URL = os.getenv("KYCBASEURL", "https://api.knowyourcustomer.dev")
CLIENT_ID = os.getenv("KYCCLIENTID")
CLIENT_SECRET = os.getenv("KYCCLIENTSECRET")

READY_STATUS_ID = 3
FAILED_STATUS_ID = 8


class KycClient:
    """Minimal client with an in-memory token cache and refresh-on-401."""

    def __init__(self, base_url: str, client_id: str, client_secret: str):
        self.base_url = base_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self._token = None
        self._expires_at = 0.0

    def _token_value(self) -> str:
        if self._token and time.time() < self._expires_at - 30:
            return self._token

        resp = requests.post(
            f"{self.base_url}/connect/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": "PublicApi",
            },
            timeout=30,
        )
        resp.raise_for_status()

        body = resp.json()
        self._token = body["access_token"]
        self._expires_at = time.time() + int(body.get("expires_in", 600))
        return self._token

    def request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        url = f"{self.base_url}{path}"
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self._token_value()}"

        resp = requests.request(method, url, headers=headers, timeout=120, **kwargs)
        if resp.status_code == 401:
            self._token = None
            headers["Authorization"] = f"Bearer {self._token_value()}"
            resp = requests.request(method, url, headers=headers, timeout=120, **kwargs)
        return resp


def create_company_case(
    company_name: str,
    jurisdiction: str,
    *,
    wait_until_ready: bool = True,
    poll_attempts: int = 60,
    poll_interval_seconds: int = 5,
    client: KycClient | None = None,
    base_url: str = BASE_URL,
    client_id: str | None = CLIENT_ID,
    client_secret: str | None = CLIENT_SECRET,
) -> dict[str, Any]:
    """
    Search the registry and create a company case.

    Args:
        company_name: The company name known by the user.
        jurisdiction: ISO 3166-2 jurisdiction code expected by the API, e.g. "HK".
        wait_until_ready: Poll the created case until statusId 3 before returning.

    Returns:
        Compact JSON containing the new case_id and selected registry match.
    """
    company_name = company_name.strip()
    jurisdiction = jurisdiction.strip().upper()
    if not company_name:
        raise ValueError("company_name is required")
    if not jurisdiction:
        raise ValueError("jurisdiction is required")

    if client is None:
        if not client_id or not client_secret:
            raise ValueError("KYCCLIENTID and KYCCLIENTSECRET are required")
        client = KycClient(base_url, client_id, client_secret)

    matches = search_companies(company_name, jurisdiction, client=client)
    if not matches:
        raise ValueError(
            f"No registry results found for {company_name!r} in {jurisdiction}"
        )

    selected_match = matches[0]
    raw_name = selected_match.get("rawname")
    if not raw_name:
        raise ValueError("Top registry result did not include rawname")

    create_resp = client.request(
        "POST",
        "/v2/Companies",
        json={"rawname": raw_name, "codeiso31662": jurisdiction},
    )
    create_resp.raise_for_status()
    created = create_resp.json()
    case_id = _case_id(created)
    if case_id is None:
        raise ValueError("Create case response did not include caseCommonId")

    result = {
        "case_id": case_id,
        "status_id": _status_id(created),
        "jurisdiction": jurisdiction,
        "searched_company_name": company_name,
        "wait": {
            "wait_until_ready": wait_until_ready,
            "poll_attempts": poll_attempts,
            "poll_interval_seconds": poll_interval_seconds,
            "max_wait_seconds": poll_attempts * poll_interval_seconds
            if wait_until_ready
            else 0,
        },
        "selected_registry_match": _clean_search_result(selected_match),
        "additional_registry_matches": [
            _clean_search_result(match) for match in matches[1:5]
        ],
    }

    if wait_until_ready:
        polling = _poll_until_ready(
            client,
            case_id,
            attempts=poll_attempts,
            interval_seconds=poll_interval_seconds,
        )
        result["status_id"] = polling["status_id"]
        result["polling"] = polling
        result["ready"] = result["status_id"] == READY_STATUS_ID

    return _drop_empty(result)


def search_companies(
    company_name: str,
    jurisdiction: str,
    *,
    client: KycClient,
) -> list[dict[str, Any]]:
    """Search the registry for possible company matches."""
    resp = client.request(
        "POST",
        "/v2/Companies/search",
        json={"codeiso31662": jurisdiction, "query": company_name},
    )
    resp.raise_for_status()
    body = resp.json()
    return body.get("companySearch", {}).get("results", [])


def _poll_until_ready(
    client: KycClient,
    case_id: int | str,
    *,
    attempts: int,
    interval_seconds: int,
) -> dict[str, Any]:
    started_at = time.monotonic()
    status_id = None
    polls_completed = 0

    for poll_number in range(1, attempts + 1):
        resp = client.request("GET", f"/v2/Companies/{case_id}")
        resp.raise_for_status()
        status_id = _status_id(resp.json())
        polls_completed = poll_number

        if status_id == READY_STATUS_ID:
            return {
                "status_id": status_id,
                "polls_completed": polls_completed,
                "elapsed_seconds": round(time.monotonic() - started_at, 2),
            }
        if status_id == FAILED_STATUS_ID:
            raise ValueError(f"Company case {case_id} failed or expired")

        time.sleep(interval_seconds)

    return {
        "status_id": status_id,
        "polls_completed": polls_completed,
        "elapsed_seconds": round(time.monotonic() - started_at, 2),
    }


def _case_id(response: dict[str, Any]) -> int | str | None:
    return (
        response.get("caseDetail", {})
        .get("details", {})
        .get("common", {})
        .get("caseCommonId")
    )


def _status_id(response: dict[str, Any]) -> int | None:
    return (
        response.get("caseDetail", {})
        .get("details", {})
        .get("common", {})
        .get("statusId")
    )


def _clean_search_result(result: dict[str, Any]) -> dict[str, Any]:
    keep_keys = (
        "rawname",
        "name",
        "registrationNumber",
        "companyNumber",
        "status",
        "type",
        "jurisdiction",
        "codeiso31662",
    )
    cleaned = {key: result.get(key) for key in keep_keys if key in result}

    if not cleaned:
        cleaned = {"rawname": result.get("rawname")}
    return _drop_empty(cleaned)


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


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a company KYC case")
    parser.add_argument("company_name", help="Company name to search")
    parser.add_argument("jurisdiction", help='Jurisdiction code, e.g. "HK"')
    parser.add_argument(
        "--no-wait",
        action="store_true",
        help="Return immediately after case creation without polling for Ready",
    )
    parser.add_argument(
        "--poll-attempts",
        type=int,
        default=60,
        help="Number of status polling attempts when waiting for Ready",
    )
    parser.add_argument(
        "--poll-interval-seconds",
        type=int,
        default=5,
        help="Seconds between status polling attempts",
    )
    args = parser.parse_args()

    result = create_company_case(
        args.company_name,
        args.jurisdiction,
        wait_until_ready=not args.no_wait,
        poll_attempts=args.poll_attempts,
        poll_interval_seconds=args.poll_interval_seconds,
    )
    json.dump(result, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
