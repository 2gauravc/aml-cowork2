"""SKILL-configured shell-company risk assessments."""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from openai import OpenAI, OpenAIError
from src.utils.langsmith_tracing import traced_openai_client

from src.utils.skill_definitions import SkillDefinitionError, load_skill_definition

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SKILL_PATH = PROJECT_ROOT / "skills" / "shell-company-risk" / "SKILL.md"
DEFAULT_MODEL = os.getenv("OPENAI_SHELL_COMPANY_RISK_MODEL") or os.getenv("OPENAI_MODEL", "gpt-5.6")
SECTIONS = {"customer_business_profile", "ownership_and_control", "identity_verification", "screening"}


class ShellCompanyRiskError(RuntimeError):
    pass


def load_shell_company_risk_definition(path: str | Path = SKILL_PATH) -> dict[str, Any]:
    try:
        metadata, definition_path, definition_version = load_skill_definition(path)
    except (OSError, SkillDefinitionError) as exc:
        raise ShellCompanyRiskError(f"Shell Company Risk skill could not be loaded: {exc}") from exc
    assessment = metadata.get("assessment") if isinstance(metadata, dict) else None
    factors = metadata.get("factors") if isinstance(metadata, dict) else None
    expected = {"low_paid_up_capital", "recent_incorporation", "foreign_controllers_outside_ao", "no_business_presence_in_ao"}
    if not isinstance(assessment, dict) or assessment.get("schema") != "shell_company_risk_assessment/v1":
        raise ShellCompanyRiskError("Shell Company Risk skill must declare assessment.schema")
    if not isinstance(factors, list) or {item.get("id") for item in factors if isinstance(item, dict)} != expected:
        raise ShellCompanyRiskError("Shell Company Risk skill must declare four configured factors")
    if any(item.get("cdd_section") not in SECTIONS for item in factors):
        raise ShellCompanyRiskError("Every Shell Company Risk factor must declare a CDD section")
    return {"assessment": assessment, "factors": sorted(factors, key=lambda item: item.get("order", 0)), "path": definition_path, "definition_version": definition_version}


def evaluate_shell_company_risk(state: dict[str, Any]) -> dict[str, Any]:
    definition = load_shell_company_risk_definition()
    inputs = _inputs(state)
    selected = {factor["id"]: _select_evidence(state, factor["cdd_section"]) for factor in definition["factors"]}
    results = _classify(inputs, definition["factors"])
    assessments = []
    for factor in definition["factors"]:
        result = results[factor["id"]]
        assessments.append({"factor_id": factor["id"], "title": factor["title"], "display_order": factor.get("order", 0), "cdd_section": factor["cdd_section"], "method": factor["method"], "outcome": result["outcome"], "summary": result["summary"], "detail": {"inputs": inputs, "rationale": result["rationale"]}, "severity": factor["severity"], "action": factor["action"], "selected_evidence": selected[factor["id"]], "provenance": {"method": "llm_structured", "model": DEFAULT_MODEL}})
    return {"definition": definition, "assessments": assessments}


def _inputs(state: dict[str, Any]) -> dict[str, Any]:
    cdd = state.get("cdd") or {}; profile = ((cdd.get("company_business_profile") or {}).get("customer_static") or {}); ownership = cdd.get("ownership_and_control") or {}; customer = (state.get("metadata") or {}).get("customer") or {}
    digital = next((item for item in reversed(state.get("assessments") or []) if item.get("assessment_type") == "digital_footprint"), {})
    digital_profile = digital.get("digital_business_profile") or {}
    members = (ownership.get("members") or {}).get("controlling_members") or []
    ubos = ownership.get("ubos") or []
    return {"account_opening_location": customer.get("account_location"), "paid_up_capital": profile.get("paid_up_capital") or (profile.get("display_capital") or {}).get("value"), "incorporation_date": profile.get("incorporation_date") or profile.get("registration_date"), "evaluation_date": datetime.now(UTC).date().isoformat(), "business_activity": digital_profile.get("business_activity") or profile.get("activity_type"), "registered_address": profile.get("registered_address"), "operating_locations": digital_profile.get("geographic_presence") or [], "ubos": ubos, "directors": [member for member in members if str(member.get("role") or "").casefold() in {"director", "managing director"}], "ownership_status": ownership.get("status"), "recent_incorporation_months": 12}


def _select_evidence(state: dict[str, Any], section: str) -> list[dict[str, Any]]:
    return [{"evidence_id": item["evidence_id"], "tool": item.get("tool"), "source": item.get("source"), "selection_reason": "Matches the factor's configured CDD section."} for item in state.get("evidence") or [] if item.get("evidence_id") and item.get("cdd_section") == section]


def _classify(inputs: dict[str, Any], factors: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    if not os.getenv("OPENAI_API_KEY"):
        raise ShellCompanyRiskError("OPENAI_API_KEY is required for Shell Company Risk classification")
    properties = {factor["id"]: {"type": "object", "additionalProperties": False, "properties": {"outcome": {"type": "string", "enum": ["triggered", "not_triggered", "inconclusive"]}, "summary": {"type": "string"}, "rationale": {"type": "string"}}, "required": ["outcome", "summary", "rationale"]} for factor in factors}
    schema = {"type": "object", "additionalProperties": False, "properties": properties, "required": list(properties)}
    policy = [{key: factor[key] for key in ("id", "title", "risk_definition", "recent_incorporation_months") if key in factor} for factor in factors]
    prompt = "Assess each shell-company risk factor using only the supplied facts and policy. Do not infer missing facts. Return inconclusive only where retained facts cannot support a reliable conclusion; do not make foreign nationality alone a risk trigger.\n\n" + json.dumps({"policy": policy, "retained_facts": inputs})
    try:
        response = traced_openai_client(OpenAI()).responses.create(model=DEFAULT_MODEL, input=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}], text={"format": {"type": "json_schema", "name": "shell_company_risk", "schema": schema, "strict": True}})
        parsed = json.loads(response.output_text)
    except OpenAIError as exc:
        raise ShellCompanyRiskError(f"Shell Company Risk classification failed: {exc}") from exc
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ShellCompanyRiskError("Shell Company Risk classification did not return valid structured output") from exc
    if not isinstance(parsed, dict) or any(not isinstance(parsed.get(factor["id"]), dict) or parsed[factor["id"]].get("outcome") not in {"triggered", "not_triggered", "inconclusive"} for factor in factors):
        raise ShellCompanyRiskError("Shell Company Risk classification returned an invalid result")
    return parsed
