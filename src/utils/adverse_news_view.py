"""Definition-driven stable UI projection for Adverse News CDD artifacts."""

from __future__ import annotations

from typing import Any

from src.tools.adverse_news import AdverseNewsError, load_adverse_news_definition


class AdverseNewsViewError(ValueError):
    """Raised when a presentation declaration cannot be compiled."""


def adverse_news_view(state: dict[str, Any], definition: dict[str, Any] | None = None) -> dict[str, Any]:
    """Compile canonical or migrated artifacts into the declared `tool_view/v1`."""
    definition = definition or load_adverse_news_definition()
    presentation = definition.get("presentation") or {}
    assessment = _latest_assessment(state)
    findings = [item for item in state.get("findings") or [] if isinstance(item, dict) and item.get("category") == "adverse_news"]
    evidence = [item for item in state.get("evidence") or [] if isinstance(item, dict) and item.get("tool") == "adverse_news_screening"]
    context = {"entity_count": len((assessment or {}).get("screened_entities") or []), "source_count": len((assessment or {}).get("source_evidence_ids") or [])}
    base = {"assessment": assessment or {"outcome": "not_run", "summary": None, "limitations": []}, "context": context}
    return {
        "schema_version": "tool_view/v1",
        "tool": "adverse_news",
        "status": _resolve(presentation.get("summary", {}).get("status"), base),
        "summary": _compile_variant(presentation.get("summary"), base, findings),
        "detailed": _compile_variant(presentation.get("detailed"), base, findings),
        "entities": _entities(assessment),
        "evidence": [_evidence_view(item) for item in evidence],
    }


def _compile_variant(spec: Any, base: dict[str, Any], findings: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(spec, dict) or not isinstance(spec.get("title"), str):
        raise AdverseNewsViewError("Presentation variant must declare a title")
    metrics = []
    for metric in spec.get("metrics") or []:
        if not isinstance(metric, dict) or not isinstance(metric.get("label"), str):
            raise AdverseNewsViewError("Presentation metric must declare a label")
        metrics.append({"label": metric["label"], "value": _resolve(metric.get("value"), base)})
    return {
        "title": spec["title"],
        "text": _resolve(spec.get("text"), base),
        "limitations": _resolve(spec.get("limitations"), base) or [],
        "metrics": metrics,
        "sections": _sections(spec.get("sections") or []),
        "entity_sections": _sections(spec.get("entity_sections") or []),
        "status_labels": _status_labels(spec.get("status_labels") or {}),
        "findings": [_finding_view(finding, spec.get("finding_tags") or []) for finding in findings],
    }


def _sections(value: list[Any]) -> list[dict[str, str]]:
    if any(not isinstance(item, dict) or not isinstance(item.get("id"), str) or not isinstance(item.get("title"), str) for item in value):
        raise AdverseNewsViewError("Presentation sections must declare id and title")
    return [{"id": item["id"], "title": item["title"], "text": item.get("text"), "limitations": item.get("limitations"), "empty_text": str(item.get("empty_text") or "")} for item in value]


def _status_labels(value: dict[str, Any]) -> dict[str, str]:
    if any(not isinstance(key, str) or not isinstance(label, str) for key, label in value.items()):
        raise AdverseNewsViewError("Presentation status labels must be strings")
    return value


def _finding_view(finding: dict[str, Any], tag_specs: list[Any]) -> dict[str, Any]:
    tags = []
    for tag in tag_specs:
        if not isinstance(tag, dict) or not isinstance(tag.get("label"), str):
            raise AdverseNewsViewError("Presentation finding tag must declare a label")
        tags.append({"label": tag["label"], "value": _resolve(tag.get("value"), {"finding": finding}), "tone": tag.get("tone")})
    return {"id": finding.get("finding_id"), "subject": (finding.get("subject") or {}).get("name") or "Screened entity", "title": finding.get("title"), "summary": finding.get("summary"), "tags": tags, "evidence_ids": finding.get("relevant_evidence_ids") or [], "source": (finding.get("source") or {}).get("producer_name")}


def _entities(assessment: dict[str, Any] | None) -> list[dict[str, Any]]:
    outcomes = {item.get("entity_key"): item for item in (assessment or {}).get("entity_outcomes") or [] if isinstance(item, dict)}
    return [{"key": entity.get("key"), "name": entity.get("name") or "Unnamed entity", "summary": (outcomes.get(entity.get("key")) or {}).get("summary"), "limitations": (outcomes.get(entity.get("key")) or {}).get("limitations") or []} for entity in (assessment or {}).get("screened_entities") or [] if isinstance(entity, dict)]


def _evidence_view(item: dict[str, Any]) -> dict[str, Any]:
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    return {"id": item.get("evidence_id"), "entity_key": data.get("entity_key"), "title": item.get("description") or data.get("title") or "Source", "url": item.get("source_url") or data.get("url"), "source": item.get("source") or "Web source", "published_at": item.get("published_at") or data.get("published_date")}


def _latest_assessment(state: dict[str, Any]) -> dict[str, Any] | None:
    assessments = [item for item in state.get("assessments") or [] if isinstance(item, dict) and item.get("assessment_type") == "adverse_news"]
    return assessments[-1] if assessments else None


def _resolve(path: Any, values: dict[str, Any]) -> Any:
    if path is None:
        return None
    if not isinstance(path, str) or not path:
        raise AdverseNewsViewError("Presentation binding must be a non-empty dotted path")
    current: Any = values
    for key in path.split("."):
        if not isinstance(current, dict) or key not in current:
            raise AdverseNewsViewError(f"Presentation binding does not resolve: {path}")
        current = current[key]
    return current
