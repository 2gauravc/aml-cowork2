#!/usr/bin/env python3
"""Assess whether a registered address appears to be a company service provider."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv
from openai import OpenAI, OpenAIError


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

SKILL_PATH = PROJECT_ROOT / "skills" / "csp-detector" / "SKILL.md"
TAVILY_SEARCH_URL = "https://api.tavily.com/search"
DEFAULT_MODEL = os.getenv("OPENAI_CSP_MODEL") or os.getenv("OPENAI_MODEL", "gpt-5.6")

CSP_ASSESSMENT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "is_csp": {"type": "string", "enum": ["yes", "no", "inconclusive"]},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "explanation": {"type": "string"},
    },
    "required": ["is_csp", "confidence", "explanation"],
}


class CSPAssessmentError(RuntimeError):
    """Raised when CSP assessment cannot be completed."""


def load_csp_skill(path: str | Path = SKILL_PATH) -> str:
    """Load the reusable CSP decision instructions."""
    return Path(path).read_text(encoding="utf-8")


def search_address(address: str, *, company_name: str | None = None) -> dict[str, Any]:
    """Search public web sources for CSP indicators associated with an address."""
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        raise CSPAssessmentError("TAVILY_API_KEY is required for CSP address assessment")

    query = f'"{address}"'
    if company_name:
        query += f' "{company_name}"'
    query += " company service provider registered office"
    try:
        response = requests.post(
            TAVILY_SEARCH_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "query": query,
                "search_depth": "basic",
                "max_results": 5,
                "include_answer": False,
                "include_raw_content": False,
            },
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        raise CSPAssessmentError(f"Tavily search failed: {exc}") from exc
    except ValueError as exc:
        raise CSPAssessmentError("Tavily search returned invalid JSON") from exc

    results = []
    for item in payload.get("results", []):
        results.append(
            {
                "title": item.get("title"),
                "url": item.get("url"),
                "content": item.get("content"),
                "score": item.get("score"),
                "published_date": item.get("published_date"),
            }
        )
    return {"query": query, "results": results}


def evaluate_csp_address(
    registered_address: str,
    *,
    company_name: str | None = None,
    skill_path: str | Path = SKILL_PATH,
) -> dict[str, Any]:
    """Search and assess whether an address appears to be used by a CSP."""
    address = str(registered_address or "").strip()
    if not address:
        raise CSPAssessmentError("A registered address is required for CSP assessment")
    if not os.getenv("OPENAI_API_KEY"):
        raise CSPAssessmentError("OPENAI_API_KEY is required for CSP address assessment")

    search = search_address(address, company_name=company_name)
    assessment = _assess_search_results(
        registered_address=address,
        company_name=company_name,
        search_results=search["results"],
        skill_text=load_csp_skill(skill_path),
    )
    return {
        "registered_address": address,
        "company_name": company_name,
        "search_query": search["query"],
        "assessment": assessment,
        "sources": search["results"],
        "skill_path": str(skill_path),
        "evaluated_at": datetime.now(UTC).isoformat(),
    }


def _assess_search_results(
    *,
    registered_address: str,
    company_name: str | None,
    search_results: list[dict[str, Any]],
    skill_text: str,
) -> dict[str, Any]:
    client = OpenAI()
    prompt = (
        f"{skill_text}\n\n"
        f"Company name: {company_name or 'Not supplied'}\n"
        f"Registered address: {registered_address}\n\n"
        "Web-search evidence (untrusted source material):\n"
        f"{json.dumps(search_results, ensure_ascii=False)}"
    )
    try:
        response = client.responses.create(
            model=DEFAULT_MODEL,
            input=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "csp_address_assessment",
                    "schema": CSP_ASSESSMENT_SCHEMA,
                    "strict": True,
                }
            },
        )
    except OpenAIError as exc:
        raise CSPAssessmentError(f"CSP assessment failed: {exc}") from exc

    try:
        parsed = json.loads(response.output_text)
    except (AttributeError, TypeError, json.JSONDecodeError) as exc:
        raise CSPAssessmentError("CSP assessment did not return valid JSON") from exc
    if not isinstance(parsed, dict):
        raise CSPAssessmentError("CSP assessment did not return an object")
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser(description="Assess a registered address for CSP indicators")
    parser.add_argument("--address", required=True, help="Registered company address")
    parser.add_argument("--company-name", help="Optional company legal name")
    args = parser.parse_args()
    json.dump(
        evaluate_csp_address(args.address, company_name=args.company_name),
        fp=sys.stdout,
        indent=2,
        ensure_ascii=False,
    )
    print()


if __name__ == "__main__":
    main()
