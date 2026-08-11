"""Stable UI projection for CSP address assessment artifacts."""

from __future__ import annotations

from typing import Any

from src.tools.csp_detector import load_csp_definition


def csp_view(state: dict[str, Any]) -> dict[str, Any]:
    """Present current and migrated CSP records without exposing artifact shapes."""
    presentation = load_csp_definition()["presentation"]
    assessments = [
        item
        for item in state.get("assessments") or []
        if isinstance(item, dict) and item.get("assessment_type") == "csp_address"
    ]
    assessment = (
        assessments[-1]
        if assessments
        else {
            "outcome": "not_run",
            "summary": None,
            "limitations": [],
            "source_evidence_ids": [],
        }
    )
    findings = [
        item
        for item in state.get("findings") or []
        if isinstance(item, dict) and item.get("category") == "csp_address"
    ]
    evidence = [
        item
        for item in state.get("evidence") or []
        if isinstance(item, dict) and item.get("tool") == "csp_address_assessment"
    ]
    context = {"source_count": len(assessment.get("source_evidence_ids") or [])}

    def variant(spec: dict[str, Any]) -> dict[str, Any]:
        return {
            "title": spec["title"],
            "text": assessment.get("summary"),
            "limitations": assessment.get("limitations") or [],
            "metrics": [
                {
                    "label": item["label"],
                    "value": context.get(str(item.get("value", "")).split(".")[-1]),
                }
                for item in spec.get("metrics") or []
            ],
            "sections": spec.get("sections") or [],
            "status_labels": {
                **(spec.get("status_labels") or {}),
                "triggered": "CSP address indicator identified",
                "not_triggered": "No CSP address indicator identified",
                "inconclusive": "CSP address assessment is inconclusive",
                "not_run": "Not run",
            },
            "assessment_tags": [
                {
                    "label": "Confidence",
                    "value": assessment.get("confidence") or "Not retained",
                    "tone": "confidence",
                },
                {"label": "Severity", "value": "not_applicable", "tone": "severity"},
            ],
            "findings": [
                _finding(item, spec.get("finding_tags") or []) for item in findings
            ],
        }

    return {
        "schema_version": "tool_view/v1",
        "tool": "csp_address",
        "status": assessment.get("outcome") or "not_run",
        "summary": variant(presentation["summary"]),
        "detailed": variant(presentation["detailed"]),
        "evidence": [
            {
                "id": item.get("evidence_id"),
                "title": item.get("description"),
                "url": item.get("source_url"),
                "source": item.get("source"),
            }
            for item in evidence
        ],
    }


def _finding(finding: dict[str, Any], tags: list[dict[str, Any]]) -> dict[str, Any]:
    values = {
        "Confidence": (finding.get("confidence") or {}).get("level"),
        "Severity": (finding.get("severity") or {}).get("level"),
    }
    return {
        "id": finding.get("finding_id"),
        "subject": (finding.get("subject") or {}).get("name"),
        "title": finding.get("title"),
        "summary": finding.get("summary"),
        "tags": [
            {
                "label": tag.get("label"),
                "value": values.get(tag.get("label"), "Not retained"),
                "tone": tag.get("tone"),
            }
            for tag in tags
        ],
        "evidence_ids": finding.get("relevant_evidence_ids") or [],
    }
