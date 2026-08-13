"""Deterministic, skill-configured CDD completeness assessments."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from src.utils.skill_definitions import SkillDefinitionError, load_skill_definition

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SKILL_PATH = PROJECT_ROOT / "skills" / "cdd-completeness" / "SKILL.md"


class CDDCompletenessError(RuntimeError):
    pass


def load_cdd_completeness_definition(path: str | Path = SKILL_PATH) -> dict[str, Any]:
    try:
        metadata, definition_path, definition_version = load_skill_definition(path)
    except (OSError, SkillDefinitionError) as exc:
        raise CDDCompletenessError(f"CDD Completeness skill could not be loaded: {exc}") from exc
    assessment = metadata.get("assessment") if isinstance(metadata, dict) else None
    checks = metadata.get("checks") if isinstance(metadata, dict) else None
    if not isinstance(assessment, dict) or assessment.get("schema") != "cdd_completeness_assessment/v1":
        raise CDDCompletenessError("CDD Completeness skill must declare assessment.schema")
    if not isinstance(checks, list) or len(checks) != 4 or any(not item.get("id") for item in checks if isinstance(item, dict)):
        raise CDDCompletenessError("CDD Completeness skill must declare four identified checks")
    return {"assessment": assessment, "checks": sorted(checks, key=lambda item: item.get("order", 0)), "path": definition_path, "definition_version": definition_version}


def evaluate_cdd_completeness(state: dict[str, Any]) -> dict[str, Any]:
    definition = load_cdd_completeness_definition()
    cdd = state.get("cdd") or {}
    profile = (cdd.get("company_business_profile") or {}).get("customer_static") or {}
    ownership = cdd.get("ownership_and_control") or {}
    idv = cdd.get("individual_identity_verification") or {}
    documents = state.get("documents") or []
    assessments = []
    for check in definition["checks"]:
        check_id = check["id"]
        if check_id == "customer_business_profile_complete":
            missing = [_display_field(field) for field in check.get("required_fields", []) if not _profile_value(profile, field, state)]
            detail = {"missing_items": missing}
        elif check_id == "ubos_identified":
            missing = [] if ownership.get("ubos") else ["Individual UBOs"]
            detail = {"missing_items": missing, "ubo_count": len(ownership.get("ubos") or [])}
        elif check_id == "ownership_structure_unwrapped":
            missing = list(ownership.get("missing_items") or [])
            if ownership.get("status") != "complete" and not missing:
                missing = ["Ownership and control structure"]
            detail = {"missing_items": missing}
        else:
            required = idv.get("required_individuals") or []
            incomplete = [
                _document_subject(document) for document in documents
                if document.get("purpose") == "identity_verification" and not _valid_idv_document(document)
            ]
            missing = incomplete or (["Required identity documents"] if required and not documents else [])
            detail = {"missing_items": missing, "required_individual_count": len(required)}
        outcome = "not_triggered" if not missing else "gap"
        assessments.append({
            "check_id": check_id,
            "title": check["title"],
            "display_order": check.get("order", 0),
            "outcome": outcome,
            "summary": "Check completed with no gap identified." if not missing else f"Gap identified: {', '.join(missing)}.",
            "detail": detail,
            "gap_severity": check.get("gap_severity"),
            "action": check.get("action"),
        })
    return {"definition": definition, "assessments": assessments}


def _profile_value(profile: dict[str, Any], field: str, state: dict[str, Any]) -> Any:
    if field == "principal_business_activity":
        candidates = [item for item in state.get("assessments", []) if item.get("assessment_type") == "digital_footprint"]
        latest = candidates[-1] if candidates else {}
        return (latest.get("digital_business_profile") or {}).get("business_activity")
    value = profile.get(field)
    return value.get("full_address") if field == "registered_address" and isinstance(value, dict) else value


def _valid_idv_document(document: dict[str, Any]) -> bool:
    validation = (document.get("processing") or {}).get("validation") or {}
    return document.get("status") == "processed" and (document.get("gap") or {}).get("status") == "resolved" and validation.get("accepted_type") is True and validation.get("name_match") is True


def _document_subject(document: dict[str, Any]) -> str:
    return str((document.get("subject") or {}).get("name") or document.get("document_id") or "Identity document")


def _display_field(field: str) -> str:
    return field.replace("_", " ").capitalize()
