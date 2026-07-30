"""Deterministic overall CDD risk-rating assessment."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SKILL_PATH = PROJECT_ROOT / "skills" / "risk-rating" / "SKILL.md"

REQUIRED_OTHER_RISK_FACTORS = {
    "high_risk_industry": "High-risk industry",
    "high_aml_risk_jurisdiction_link": "High AML-risk jurisdiction link",
    "high_tax_risk_jurisdiction_link": "High tax-risk jurisdiction link",
}


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
    factor_scores = metadata.get("factor_scores") if isinstance(metadata, dict) else None
    thresholds = metadata.get("thresholds") if isinstance(metadata, dict) else None
    expected_scores = {
        "material_adverse_news": 2,
        "high_risk_industry": 2,
        "shell_company_risk": 2,
        "high_aml_risk_jurisdiction_link": 1,
        "high_tax_risk_jurisdiction_link": 1,
    }
    if not isinstance(assessment, dict) or assessment.get("schema") != "risk_rating_assessment/v1":
        raise RiskRatingError("Risk Rating skill must declare assessment.schema")
    if ratings != ["high", "moderate", "low", "inconclusive"]:
        raise RiskRatingError("Risk Rating skill must declare the supported rating values")
    if factor_scores != expected_scores:
        raise RiskRatingError("Risk Rating skill must declare the configured factor scores")
    if thresholds != {"high": 4, "moderate": 1}:
        raise RiskRatingError("Risk Rating skill must declare the configured thresholds")
    return {
        "assessment": assessment,
        "ratings": ratings,
        "factor_scores": factor_scores,
        "thresholds": thresholds,
        "monitoring_guidance": metadata.get("monitoring_guidance") or {},
        "instructions": instructions.strip(),
        "path": str(path),
    }


def evaluate_risk_rating(state: dict[str, Any]) -> dict[str, Any]:
    definition = load_risk_rating_definition()
    inputs = _select_inputs(state)
    unavailable = _unavailable_requirements(inputs)
    if unavailable:
        explanation = f"Rule applied: risk rating is inconclusive because required assessments are missing or unavailable: {', '.join(unavailable)}."
        result = {
            "rating": "inconclusive",
            "total_score": 0,
            "contributing_factors": [],
            "matched_criteria": [f"Missing or unavailable required assessment: {item}." for item in unavailable],
            "rationale": explanation,
            "rule_explanation": explanation,
            "limitations": ["Complete the listed assessment(s) before relying on a risk rating."],
            "monitoring_posture": definition["monitoring_guidance"].get("inconclusive", "Complete outstanding assessments before setting monitoring."),
        }
        return {"definition": definition, "inputs": inputs, "result": result}

    scores = definition["factor_scores"]
    contributing = []
    if any(item["category"] == "adverse_news" for item in inputs["findings"]):
        contributing.append(_factor("material_adverse_news", "Material Adverse News finding", scores["material_adverse_news"]))
    if _other_factor_triggered(inputs["other_risk_factors"], "high_risk_industry"):
        contributing.append(_factor("high_risk_industry", "High-risk industry", scores["high_risk_industry"]))
    if any(item["outcome"] == "triggered" for item in inputs["shell_company_risk"]):
        contributing.append(_factor("shell_company_risk", "Shell Company Risk", scores["shell_company_risk"]))
    if _other_factor_triggered(inputs["other_risk_factors"], "high_aml_risk_jurisdiction_link"):
        contributing.append(_factor("high_aml_risk_jurisdiction_link", "High AML-risk jurisdiction link", scores["high_aml_risk_jurisdiction_link"]))
    if _other_factor_triggered(inputs["other_risk_factors"], "high_tax_risk_jurisdiction_link"):
        contributing.append(_factor("high_tax_risk_jurisdiction_link", "High tax-risk jurisdiction link", scores["high_tax_risk_jurisdiction_link"]))

    total_score = sum(item["points"] for item in contributing)
    rating = "high" if total_score >= definition["thresholds"]["high"] else "moderate" if total_score >= definition["thresholds"]["moderate"] else "low"
    factor_summary = "; ".join(f"{item['label']} ({item['points']})" for item in contributing) or "no scored factors"
    threshold_summary = f"score is at least {definition['thresholds']['high']}" if rating == "high" else "score is between 1 and 3" if rating == "moderate" else "score is 0"
    explanation = f"Rule applied: {factor_summary}; total score {total_score}, so {rating.title()} because the {threshold_summary}."
    return {"definition": definition, "inputs": inputs, "result": {
        "rating": rating,
        "total_score": total_score,
        "contributing_factors": contributing,
        "matched_criteria": [f"{item['label']}: {item['points']} point(s)." for item in contributing] or ["No scored risk factors were triggered."],
        "rationale": explanation,
        "rule_explanation": explanation,
        "limitations": [],
        "monitoring_posture": definition["monitoring_guidance"].get(rating, "Monitoring posture not configured."),
    }}


def _factor(factor_id: str, label: str, points: int) -> dict[str, Any]:
    return {"factor_id": factor_id, "label": label, "points": points}


def _unavailable_requirements(inputs: dict[str, Any]) -> list[str]:
    unavailable = []
    adverse = inputs["adverse_news"]
    if not adverse or any(item["outcome"] == "unavailable" for item in adverse):
        unavailable.append("Adverse News Screening")
    shell = inputs["shell_company_risk"]
    if not shell or any(item["outcome"] == "unavailable" for item in shell):
        unavailable.append("Shell Company Risk")
    for factor_id, label in REQUIRED_OTHER_RISK_FACTORS.items():
        factor = _latest_factor(inputs["other_risk_factors"], factor_id)
        if not factor or factor["outcome"] == "unavailable":
            unavailable.append(label)
    return unavailable


def _other_factor_triggered(assessments: list[dict[str, Any]], factor_id: str) -> bool:
    factor = _latest_factor(assessments, factor_id)
    return bool(factor and factor["outcome"] == "triggered")


def _latest_factor(assessments: list[dict[str, Any]], factor_id: str) -> dict[str, Any] | None:
    matches = [item for item in assessments if item.get("factor_id") == factor_id]
    return max(matches, key=lambda item: str(item.get("created_at") or ""), default=None)


def _select_inputs(state: dict[str, Any]) -> dict[str, Any]:
    findings = [
        {
            "finding_id": item.get("finding_id"),
            "category": item.get("category"),
            "relevant_evidence_ids": item.get("relevant_evidence_ids") or [],
        }
        for item in state.get("findings") or []
        if item.get("finding_id")
    ]
    assessments = [
        {
            "assessment_id": item.get("assessment_id"),
            "assessment_type": item.get("assessment_type"),
            "factor_id": item.get("factor_id") or (item.get("definition") or {}).get("factor_id"),
            "outcome": item.get("outcome"),
            "created_at": item.get("created_at"),
            "source_evidence_ids": item.get("source_evidence_ids") or [],
        }
        for item in state.get("assessments") or []
        if item.get("assessment_type") in {"adverse_news", "shell_company_risk", "other_risk_factors"}
    ]
    selected_ids = {identifier for finding in findings for identifier in finding["relevant_evidence_ids"]} | {identifier for assessment in assessments for identifier in assessment["source_evidence_ids"]}
    evidence = [
        {"evidence_id": item.get("evidence_id"), "tool": item.get("tool"), "source": item.get("source"), "description": item.get("description")}
        for item in state.get("evidence") or []
        if item.get("evidence_id") in selected_ids
    ]
    return {
        "findings": findings,
        "adverse_news": [item for item in assessments if item["assessment_type"] == "adverse_news"],
        "shell_company_risk": [item for item in assessments if item["assessment_type"] == "shell_company_risk"],
        "other_risk_factors": [item for item in assessments if item["assessment_type"] == "other_risk_factors"],
        "assessments": assessments,
        "evidence": evidence,
    }
