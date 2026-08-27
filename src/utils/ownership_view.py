"""Stable view model for ownership-unwrapping artifacts."""

from __future__ import annotations

from typing import Any

from src.tools.unwrap_ownership import load_ownership_definition


def ownership_view(state: dict[str, Any]) -> dict[str, Any]:
    definition = load_ownership_definition()
    assessments = [item for item in state.get("assessments") or [] if isinstance(item, dict) and item.get("assessment_type") == "ownership_unwrap"]
    assessment = assessments[-1] if assessments else {"outcome": "not_run", "ubo_list": [], "corporate_shareholders_over_10_percent": [], "limitations": [], "source_evidence_ids": []}
    findings = [item for item in state.get("findings") or [] if isinstance(item, dict) and item.get("category") == "ownership_review"]
    evidence = [item for item in state.get("evidence") or [] if isinstance(item, dict) and item.get("tool") == "unwrap_ownership"]
    return {"schema_version": "tool_view/v1", "tool": "unwrap_ownership", "status": assessment.get("outcome") or "not_run", "summary": {"title": "Ownership unwrapping", "text": _summary(assessment), "limitations": assessment.get("limitations") or [], "metrics": [{"label": "UBOs identified", "value": len(assessment.get("ubo_list") or [])}, {"label": "Corporate shareholders >10%", "value": len(assessment.get("corporate_shareholders_over_10_percent") or [])}], "sections": definition["presentation"]["summary"]["sections"], "findings": [_finding(item) for item in findings]}, "detailed": {"title": "Ownership and control", "ownership_paths": assessment.get("ownership_paths") or [], "ubo_list": assessment.get("ubo_list") or [], "corporate_shareholders_over_10_percent": assessment.get("corporate_shareholders_over_10_percent") or [], "unresolved_branches": assessment.get("unresolved_branches") or [], "evidence_ids": assessment.get("source_evidence_ids") or [], "findings": [_finding(item) for item in findings]}, "evidence": [{"id": item.get("evidence_id"), "title": item.get("description"), "source": item.get("source")} for item in evidence]}


def _summary(assessment: dict[str, Any]) -> str:
    outcome = assessment.get("outcome") or "not_run"
    if outcome == "complete":
        return "Ownership paths were resolved from retained evidence."
    if outcome == "listed_company_exception":
        return "A listed-company authorised executive was recorded."
    if outcome == "not_run":
        return "Ownership unwrapping has not run."
    return "Ownership evidence requires further review."


def _finding(item: dict[str, Any]) -> dict[str, Any]:
    return {"id": item.get("finding_id"), "title": item.get("title"), "summary": item.get("summary"), "evidence_ids": item.get("relevant_evidence_ids") or []}
