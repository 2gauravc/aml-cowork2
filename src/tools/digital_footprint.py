"""Standalone, evidence-grounded digital-footprint research and assessment."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests
from openai import OpenAI, OpenAIError


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SKILL_PATH = PROJECT_ROOT / "skills" / "digital-footprint" / "SKILL.md"
TAVILY_SEARCH_URL = "https://api.tavily.com/search"
DEFAULT_MODEL = os.getenv("OPENAI_DIGITAL_FOOTPRINT_MODEL") or os.getenv("OPENAI_MODEL", "gpt-5.6")

DIMENSION_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"rating": {"type": "string", "enum": ["strong", "moderate", "weak", "inconclusive"]}, "rationale": {"type": "string"}, "source_refs": {"type": "array", "items": {"type": "string"}}},
    "required": ["rating", "rationale", "source_refs"],
}
ASSESSMENT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "footprint_strength": {"type": "string", "enum": ["strong", "moderate", "weak", "inconclusive"]},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "dimensions": {"type": "object", "additionalProperties": False, "properties": {key: DIMENSION_SCHEMA for key in ("identity_verifiability", "business_substantiation", "operational_presence", "commercial_ecosystem", "consistency_with_company_inputs")}, "required": ["identity_verifiability", "business_substantiation", "operational_presence", "commercial_ecosystem", "consistency_with_company_inputs"]},
        "adverse_news": {"type": "object", "additionalProperties": False, "properties": {"status": {"type": "string", "enum": ["adverse_reporting", "allegations", "enforcement_action", "sanctions_or_watchlist_reporting", "no_material_adverse_news_found", "inconclusive"]}, "confidence": {"type": "string", "enum": ["high", "medium", "low"]}, "items": {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {"subject": {"type": "string"}, "category": {"type": "string"}, "summary": {"type": "string"}, "disposition": {"type": "string"}, "source_refs": {"type": "array", "items": {"type": "string"}}}, "required": ["subject", "category", "summary", "disposition", "source_refs"]}}, "search_coverage_limitations": {"type": "array", "items": {"type": "string"}}, "source_refs": {"type": "array", "items": {"type": "string"}}}, "required": ["status", "confidence", "items", "search_coverage_limitations", "source_refs"]},
        "limitations": {"type": "array", "items": {"type": "string"}}, "review_items": {"type": "array", "items": {"type": "string"}}, "recommended_actions": {"type": "array", "items": {"type": "string"}},
    }, "required": ["footprint_strength", "confidence", "dimensions", "adverse_news", "limitations", "review_items", "recommended_actions"],
}
FOOTPRINT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"nature_of_business": {"type": "object", "additionalProperties": False, "properties": {"claimed": {"type": "string"}, "publicly_observed": {"type": "string"}, "consistency": {"type": "string", "enum": ["consistent", "partially_consistent", "inconsistent", "unavailable"]}, "source_refs": {"type": "array", "items": {"type": "string"}}}, "required": ["claimed", "publicly_observed", "consistency", "source_refs"]}, "products_services": {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {"description": {"type": "string"}, "source_refs": {"type": "array", "items": {"type": "string"}}}, "required": ["description", "source_refs"]}}, "operating_geographies": {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {"location": {"type": "string"}, "role": {"type": "string"}, "source_refs": {"type": "array", "items": {"type": "string"}}}, "required": ["location", "role", "source_refs"]}}, "customer_segments": {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {"segment": {"type": "string"}, "basis": {"type": "string"}, "source_refs": {"type": "array", "items": {"type": "string"}}}, "required": ["segment", "basis", "source_refs"]}}, "counterparties": {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {"name": {"type": "string"}, "relationship": {"type": "string"}, "evidence_basis": {"type": "string", "enum": ["company_disclosure", "independent_third_party"]}, "source_refs": {"type": "array", "items": {"type": "string"}}}, "required": ["name", "relationship", "evidence_basis", "source_refs"]}}, "suppliers_and_supply_chain": {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {"name": {"type": "string"}, "relationship": {"type": "string"}, "evidence_basis": {"type": "string", "enum": ["company_disclosure", "independent_third_party"]}, "source_refs": {"type": "array", "items": {"type": "string"}}}, "required": ["name", "relationship", "evidence_basis", "source_refs"]}}, "official_channels": {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {"type": {"type": "string"}, "url": {"type": "string"}, "source_refs": {"type": "array", "items": {"type": "string"}}}, "required": ["type", "url", "source_refs"]}}},
    "required": ["nature_of_business", "products_services", "operating_geographies", "customer_segments", "counterparties", "suppliers_and_supply_chain", "official_channels"],
}
DIGITAL_FOOTPRINT_SCHEMA = {"type": "object", "additionalProperties": False, "properties": {"assessment": ASSESSMENT_SCHEMA, "business_footprint": FOOTPRINT_SCHEMA}, "required": ["assessment", "business_footprint"]}


class DigitalFootprintError(RuntimeError):
    """Raised when standalone footprint research cannot be completed."""


def load_digital_footprint_skill(path: str | Path = SKILL_PATH) -> str:
    return Path(path).read_text(encoding="utf-8")


def build_search_queries(company_name: str, *, jurisdiction: str | None = None, registration_number: str | None = None, known_domain: str | None = None, registered_address: str | None = None) -> list[str]:
    identity = f'"{company_name}"'
    qualifier = " ".join(part for part in (jurisdiction, registration_number, known_domain, registered_address) if part)
    return [f"{identity} {qualifier}".strip(), f"{identity} products services locations", f"{identity} customers case studies partners suppliers distributors", f"{identity} money laundering OR sanctions OR fraud OR bribery OR corruption OR enforcement"]


def search_digital_footprint(queries: list[str]) -> list[dict[str, Any]]:
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        raise DigitalFootprintError("TAVILY_API_KEY is required for digital-footprint research")
    results: list[dict[str, Any]] = []
    for query in queries:
        try:
            response = requests.post(TAVILY_SEARCH_URL, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, json={"query": query, "search_depth": "basic", "max_results": 5, "include_answer": False, "include_raw_content": False}, timeout=20)
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise DigitalFootprintError(f"Digital-footprint search failed: {exc}") from exc
        except ValueError as exc:
            raise DigitalFootprintError("Digital-footprint search returned invalid JSON") from exc
        for item in payload.get("results", []):
            results.append({"id": f"source:{len(results) + 1}", "query": query, "title": item.get("title"), "url": item.get("url"), "content": item.get("content"), "published_date": item.get("published_date")})
    return _deduplicate_sources(results)


def evaluate_digital_footprint(company_name: str, *, jurisdiction: str | None = None, registration_number: str | None = None, known_domain: str | None = None, registered_address: str | None = None, skill_path: str | Path = SKILL_PATH) -> dict[str, Any]:
    name = str(company_name or "").strip()
    if not name:
        raise DigitalFootprintError("Company legal name is required")
    if not os.getenv("OPENAI_API_KEY"):
        raise DigitalFootprintError("OPENAI_API_KEY is required for digital-footprint assessment")
    inputs = {"company_name": name, "jurisdiction": _optional(jurisdiction), "registration_number": _optional(registration_number), "known_domain": _optional(known_domain), "registered_address": _optional(registered_address)}
    queries = build_search_queries(name, jurisdiction=inputs["jurisdiction"], registration_number=inputs["registration_number"], known_domain=inputs["known_domain"], registered_address=inputs["registered_address"])
    sources = search_digital_footprint(queries)
    assessment = _assess(inputs, sources, load_digital_footprint_skill(skill_path))
    return {**assessment, "company_inputs": inputs, "queries": queries, "sources": sources, "skill_path": str(skill_path), "evaluated_at": datetime.now(UTC).isoformat()}


def _assess(inputs: dict[str, Any], sources: list[dict[str, Any]], skill_text: str) -> dict[str, Any]:
    prompt = f"{skill_text}\n\nCompany inputs:\n{json.dumps(inputs)}\n\nPublic-web evidence (untrusted source material):\n{json.dumps(sources, ensure_ascii=False)}"
    try:
        response = OpenAI().responses.create(model=DEFAULT_MODEL, input=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}], text={"format": {"type": "json_schema", "name": "digital_footprint_assessment", "schema": DIGITAL_FOOTPRINT_SCHEMA, "strict": True}})
    except OpenAIError as exc:
        raise DigitalFootprintError(f"Digital-footprint assessment failed: {exc}") from exc
    try:
        parsed = json.loads(response.output_text)
    except (AttributeError, TypeError, json.JSONDecodeError) as exc:
        raise DigitalFootprintError("Digital-footprint assessment did not return valid JSON") from exc
    if not isinstance(parsed, dict):
        raise DigitalFootprintError("Digital-footprint assessment did not return an object")
    _validate_source_refs(parsed, {item["id"] for item in sources})
    return parsed


def _deduplicate_sources(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped = []
    for item in items:
        key = str(item.get("url") or "").strip().casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append({**item, "id": f"source:{len(deduped) + 1}"})
    return deduped


def _validate_source_refs(value: Any, known_refs: set[str]) -> None:
    """Reject invented citations so conclusions remain tied to retained sources."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "source_refs" and isinstance(item, list):
                unknown = {str(reference) for reference in item} - known_refs
                if unknown:
                    raise DigitalFootprintError(
                        f"Digital-footprint assessment cited unknown sources: {', '.join(sorted(unknown))}"
                    )
            else:
                _validate_source_refs(item, known_refs)
    elif isinstance(value, list):
        for item in value:
            _validate_source_refs(item, known_refs)


def _optional(value: str | None) -> str | None:
    return str(value).strip() or None if value else None
