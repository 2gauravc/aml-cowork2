"""SKILL-driven overall CDD risk-rating assessment."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import yaml
from openai import OpenAI, OpenAIError

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SKILL_PATH = PROJECT_ROOT / "skills" / "risk-rating" / "SKILL.md"
DEFAULT_MODEL = os.getenv("OPENAI_RISK_RATING_MODEL") or os.getenv("OPENAI_MODEL", "gpt-5.6")


class RiskRatingError(RuntimeError):
    pass


def load_risk_rating_definition(path: str | Path = SKILL_PATH) -> dict[str, Any]:
    try:
        _, front, instructions = Path(path).read_text(encoding="utf-8").split("---\n", 2)
        metadata = yaml.safe_load(front)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise RiskRatingError(f"Risk Rating skill could not be loaded: {exc}") from exc
    assessment = metadata.get("assessment") if isinstance(metadata, dict) else None
    ratings = metadata.get("ratings") if isinstance(metadata, dict) else None
    if not isinstance(assessment, dict) or assessment.get("schema") != "risk_rating_assessment/v1": raise RiskRatingError("Risk Rating skill must declare assessment.schema")
    if ratings != ["high", "standalone_high", "moderate", "low"]: raise RiskRatingError("Risk Rating skill must declare the supported rating values")
    return {"assessment": assessment, "ratings": ratings, "criteria": metadata.get("criteria") or {}, "monitoring_guidance": metadata.get("monitoring_guidance") or {}, "instructions": instructions.strip(), "path": str(path)}


def evaluate_risk_rating(state: dict[str, Any]) -> dict[str, Any]:
    definition = load_risk_rating_definition(); inputs = _select_inputs(state)
    if not os.getenv("OPENAI_API_KEY"): raise RiskRatingError("OPENAI_API_KEY is required for Risk Rating assessment")
    schema = {"type": "object", "additionalProperties": False, "properties": {"rating": {"type": "string", "enum": definition["ratings"]}, "rationale": {"type": "string"}, "matched_criteria": {"type": "array", "items": {"type": "string"}}, "limitations": {"type": "array", "items": {"type": "string"}}, "monitoring_posture": {"type": "string"}}, "required": ["rating", "rationale", "matched_criteria", "limitations", "monitoring_posture"]}
    prompt = "Determine the overall CDD risk rating using only the retained inputs and policy. Follow the policy precedence and always select exactly one configured rating. Do not infer missing sanctions, PEP, adverse-news, or other risk information. Record unavailable screening coverage as a limitation, but do not let it prevent a rating.\n\n" + json.dumps({"policy": {"criteria": definition["criteria"], "monitoring_guidance": definition["monitoring_guidance"]}, "retained_inputs": inputs})
    try:
        response = OpenAI().responses.create(model=DEFAULT_MODEL, input=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}], text={"format": {"type": "json_schema", "name": "risk_rating", "schema": schema, "strict": True}})
        result = json.loads(response.output_text)
    except OpenAIError as exc: raise RiskRatingError(f"Risk Rating assessment failed: {exc}") from exc
    except (TypeError, ValueError, json.JSONDecodeError) as exc: raise RiskRatingError("Risk Rating assessment did not return valid structured output") from exc
    if not isinstance(result, dict) or result.get("rating") not in definition["ratings"]: raise RiskRatingError("Risk Rating assessment returned an invalid rating")
    return {"definition": definition, "inputs": inputs, "result": result}


def _select_inputs(state: dict[str, Any]) -> dict[str, Any]:
    findings = [{"finding_id": item.get("finding_id"), "category": item.get("category"), "title": item.get("title"), "summary": item.get("summary"), "confidence": item.get("confidence"), "severity": item.get("severity"), "relevant_evidence_ids": item.get("relevant_evidence_ids") or []} for item in state.get("findings") or [] if item.get("finding_id")]
    relevant_types = {"shell_company_risk", "other_risk_factors", "adverse_news", "digital_footprint", "cdd_completeness", "evidence_quality"}
    assessments = [{"assessment_id": item.get("assessment_id"), "assessment_type": item.get("assessment_type"), "outcome": item.get("outcome"), "summary": item.get("summary"), "source_evidence_ids": item.get("source_evidence_ids") or []} for item in state.get("assessments") or [] if item.get("assessment_type") in relevant_types]
    flags = [{"finding_id": item.get("finding_id"), "category": item.get("category"), "evaluation": item.get("evaluation"), "severity": item.get("severity"), "description": item.get("description")} for item in state.get("risk_flags") or []]
    selected_ids = {identifier for finding in findings for identifier in finding["relevant_evidence_ids"]} | {identifier for assessment in assessments for identifier in assessment["source_evidence_ids"]}
    evidence = [{"evidence_id": item.get("evidence_id"), "tool": item.get("tool"), "source": item.get("source"), "description": item.get("description")} for item in state.get("evidence") or [] if item.get("evidence_id") in selected_ids]
    return {"findings": findings, "assessments": assessments, "risk_flags": flags, "evidence": evidence}
