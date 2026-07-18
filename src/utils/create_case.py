#!/usr/bin/env python3
"""
Search a company by name and jurisdiction, then create a KYC company case.

This module is intended as an internal helper for LLM-facing tools.

For local testing:
    python src/utils/create_case.py "Ubizense Limited" HK
    python src/utils/create_case.py "Ubizense Limited" HK --no-wait
"""

import argparse
import json
import os
import sys
import threading
import time
from typing import Any

import requests
from dotenv import load_dotenv

from src.utils.kyc_cache import get_cache_value, set_cache_value


load_dotenv()

BASE_URL = os.getenv("KYCBASEURL", "https://api.knowyourcustomer.dev")
CLIENT_ID = os.getenv("KYCCLIENTID")
CLIENT_SECRET = os.getenv("KYCCLIENTSECRET")

READY_STATUS_ID = 3
FAILED_STATUS_ID = 8
TOKEN_SCOPE = "PublicApi"
TOKEN_REFRESH_BUFFER_SECONDS = 30

_TOKEN_CACHE_LOCK = threading.Lock()
_TOKEN_CACHE: dict[tuple[str, str, str], tuple[str, float]] = {}


class KycClient:
    """Minimal client with a process-local token cache and refresh-on-401."""

    def __init__(self, base_url: str, client_id: str, client_secret: str):
        self.base_url = base_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret

    def _token_value(self, *, force_refresh: bool = False) -> str:
        cache_key = (self.base_url, self.client_id, TOKEN_SCOPE)

        with _TOKEN_CACHE_LOCK:
            cached = _TOKEN_CACHE.get(cache_key)
            if not force_refresh and cached is not None:
                token, expires_at = cached
                if time.time() < expires_at - TOKEN_REFRESH_BUFFER_SECONDS:
                    return token

            resp = requests.post(
                f"{self.base_url}/connect/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "scope": TOKEN_SCOPE,
                },
                timeout=30,
            )
            resp.raise_for_status()

            body = resp.json()
            token = body["access_token"]
            expires_at = time.time() + int(body.get("expires_in", 600))
            _TOKEN_CACHE[cache_key] = (token, expires_at)
            return token

    def request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        url = f"{self.base_url}{path}"
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self._token_value()}"

        resp = requests.request(method, url, headers=headers, timeout=120, **kwargs)
        if resp.status_code == 401:
            headers["Authorization"] = f"Bearer {self._token_value(force_refresh=True)}"
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

    cached_result = get_cache_value("company-case", [jurisdiction, company_name])
    if cached_result is not None:
        return cached_result

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

    result = _drop_empty(result)
    return set_cache_value("company-case", [jurisdiction, company_name], result)


def search_companies(
    company_name: str,
    jurisdiction: str,
    *,
    client: KycClient,
) -> list[dict[str, Any]]:
    """Search the registry for possible company matches."""
    cached_body = get_cache_value("company-search", [jurisdiction, company_name])
    if cached_body is not None:
        return cached_body.get("companySearch", {}).get("results", [])

    resp = client.request(
        "POST",
        "/v2/Companies/search",
        json={"codeiso31662": jurisdiction, "query": company_name},
    )
    resp.raise_for_status()
    body = resp.json()
    set_cache_value("company-search", [jurisdiction, company_name], body)
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
        body = get_company_detail(case_id, client=client)
        status_id = _status_id(body)
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


def get_company_detail(case_id: int | str, *, client: KycClient) -> dict[str, Any]:
    """Return raw company detail JSON, reading the persistent cache first."""
    cached_body = get_cache_value("company-detail", [case_id])
    if cached_body is not None:
        return cached_body

    resp = client.request("GET", f"/v2/Companies/{case_id}")
    resp.raise_for_status()
    body = resp.json()
    if _status_id(body) == READY_STATUS_ID:
        set_cache_value("company-detail", [case_id], body)
    return body


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
