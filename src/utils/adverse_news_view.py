"""Stable UI projection for versioned Adverse News CDD artifacts."""

from __future__ import annotations

from typing import Any


def adverse_news_view(state: dict[str, Any]) -> dict[str, Any]:
    """Project canonical or migrated state without exposing storage-version details."""
    assessments = [item for item in state.get("assessments") or [] if isinstance(item, dict) and item.get("assessment_type") == "adverse_news"]
    assessment = assessments[-1] if assessments else None
    findings = []
    for item in state.get("findings") or []:
        if not isinstance(item, dict) or item.get("category") != "adverse_news":
            continue
        overlay = item.get("adverse_news") if isinstance(item.get("adverse_news"), dict) else {}
        identity = overlay.get("identity_match") if isinstance(overlay.get("identity_match"), dict) else {}
        event = overlay.get("adverse_event") if isinstance(overlay.get("adverse_event"), dict) else {}
        findings.append({**item, "tags": {"identity_match": identity.get("status", "unknown"), "adverse_event": event.get("event_category", "unknown"), "confidence": (item.get("confidence") or {}).get("level", "unknown"), "severity": (item.get("severity") or {}).get("level", "unknown")}})
    evidence = [item for item in state.get("evidence") or [] if isinstance(item, dict) and item.get("tool") == "adverse_news_screening"]
    return {
        "schema_version": "adverse_news_view/v1",
        "status": assessment.get("outcome") if assessment else "not_run",
        "assessment": assessment,
        "findings": findings,
        "evidence": evidence,
    }
