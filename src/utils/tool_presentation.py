"""Compile a tool's small presentation extension onto the shared CDD view base."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TOOL_VIEW_SCHEMA_PATH = PROJECT_ROOT / "schemas" / "presentation" / "tool-view-v1.yaml"


class ToolPresentationError(ValueError):
    """Raised when a tool presentation declaration is not valid."""


_STATUS_LABELS = {
    "completed_with_findings": "Assessment completed with findings",
    "completed_no_material_findings": "Assessment completed",
    "completed_inconclusive": "Assessment completed with limitations",
    "unavailable": "Assessment unavailable",
}
_BASE_TAGS = [
    {"label": "Confidence", "value": "finding.confidence.level", "tone": "confidence"},
    {"label": "Severity", "value": "finding.severity.level", "tone": "severity"},
]
_BASE_SECTIONS = {
    "assessment": {"id": "summary", "title": "Assessment", "empty_text": "No assessment is available."},
    "findings": {"id": "findings", "title": "Findings", "empty_text": "No material findings were identified."},
    "evidence": {"id": "evidence", "title": "Evidence", "empty_text": "No retained source evidence was recorded."},
}
_ENTITY_SECTION = {"id": "entities", "title": "Entity screening", "empty_text": "No screened entities were recorded."}


def compile_tool_presentation(extension: dict[str, Any]) -> dict[str, Any]:
    """Validate and merge a tool extension with the generic artifact presentation.

    The shared base owns the evidence, assessment and ``finding/v1`` fields.  A
    tool file supplies only view selection plus domain-specific assessment and
    finding extensions.
    """
    _validate_extension(extension)
    views = extension["views"]
    assessment_extension = extension.get("assessment", {}).get("extension", {})
    finding_extension = extension.get("finding", {}).get("extension", {})

    def variant(name: str) -> dict[str, Any]:
        view = views[name]
        selected = view.get("sections") or []
        sections = [_BASE_SECTIONS[section] for section in selected]
        if assessment_extension.get("entity_sections"):
            entity_section = {**_ENTITY_SECTION, "title": assessment_extension.get("entity_title") or _ENTITY_SECTION["title"]}
            sections = [sections[0], entity_section, *sections[1:]] if "assessment" in selected else [entity_section, *sections]
        return {
            "title": view["title"],
            "status": "assessment.outcome",
            "text": "assessment.summary",
            "limitations": "assessment.limitations",
            "status_labels": _STATUS_LABELS,
            "metrics": assessment_extension.get("metrics") or [],
            "sections": sections,
            "entity_sections": assessment_extension.get("entity_sections") or [],
            "finding_tags": [*_BASE_TAGS, *(finding_extension.get("tags") or [])],
        }

    return {"schema": "tool_view/v1", "summary": variant("summary"), "detailed": variant("detailed")}


def _validate_extension(extension: dict[str, Any]) -> None:
    try:
        from jsonschema import Draft202012Validator
    except ImportError as exc:  # pragma: no cover - deployment dependency
        raise ToolPresentationError("jsonschema is required to validate tool presentations") from exc
    try:
        schema = yaml.safe_load(TOOL_VIEW_SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ToolPresentationError(f"Tool presentation schema could not be loaded: {exc}") from exc
    errors = list(Draft202012Validator(schema).iter_errors(extension))
    if errors:
        raise ToolPresentationError(f"Invalid tool presentation: {errors[0].message}")
