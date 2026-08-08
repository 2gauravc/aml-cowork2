"""Idempotent normalization for completed CDD snapshots written by retired flows."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


def migrate_legacy_risk_flags(state: dict[str, Any]) -> bool:
    """Replace retired CSP flags with canonical records and discard ownership flags."""
    if "risk_flags" not in state:
        return False
    flags = state.pop("risk_flags")
    if not isinstance(flags, list):
        return True
    csp_flags = [item for item in flags if isinstance(item, dict) and item.get("category") == "csp_address"]
    if not csp_flags or any(item.get("assessment_type") == "csp_address" for item in state.get("assessments") or []):
        return True
    flag = csp_flags[-1]
    created_at = str(flag.get("collected_at") or datetime.now(UTC).isoformat())
    run_id = f"migration:legacy-risk-flags:{uuid4().hex}"
    raw = flag.get("evidence") if isinstance(flag.get("evidence"), dict) else {}
    matching = next((item for item in reversed(state.get("evidence") or []) if isinstance(item, dict) and item.get("tool") == "csp_address_assessment"), None)
    if matching:
        raw = raw or (matching.get("data") if isinstance(matching.get("data"), dict) else {})
    assessment_data = raw.get("assessment") if isinstance(raw.get("assessment"), dict) else {}
    raw_evaluation = flag.get("evaluation") if flag.get("evaluation") is not None else assessment_data.get("is_csp")
    evaluation = str(raw_evaluation).casefold() if raw_evaluation is not None else ""
    outcome = {"yes": "triggered", "no": "not_triggered", "inconclusive": "inconclusive"}.get(evaluation, "inconclusive")
    limitations = [] if evaluation in {"yes", "no", "inconclusive"} else ["Legacy CSP outcome was missing or invalid; migrated as inconclusive."]
    summary = str(flag.get("description") or assessment_data.get("explanation") or "Legacy CSP assessment was migrated without a recorded explanation.")
    profile = (((state.get("cdd") or {}).get("company_business_profile") or {}).get("customer_static") or {})
    evidence_id = matching.get("evidence_id") if matching else None
    if not evidence_id:
        evidence_id = f"evidence:csp-address:migrated:{uuid4().hex}"
        state.setdefault("evidence", []).append({"evidence_id": evidence_id, "source": "Legacy CDD snapshot", "tool": "csp_address_assessment", "description": "Migrated CSP address evidence from a retired risk flag.", "relevance_tags": ["csp_address", "registered_address", "migration"], "cdd_section": "screening", "data": raw, "collected_at": created_at, "provenance": {"method": "legacy_risk_flags_migration", "legacy_finding_id": flag.get("finding_id")}})
    assessment_id = f"assessment:csp-address:migrated:{uuid4().hex}"
    confidence = str(assessment_data.get("confidence") or "low")
    assessment = {"assessment_id": assessment_id, "assessment_type": "csp_address", "schema_version": "csp_address_assessment/v1", "tool": "csp_address_assessment", "run_id": run_id, "created_at": created_at, "outcome": outcome, "summary": summary, "registered_address": raw.get("registered_address") or ((profile.get("registered_address") or {}).get("full_address")), "company_name": raw.get("company_name") or profile.get("name"), "confidence": confidence, "skill_path": raw.get("skill_path"), "source_evidence_ids": [evidence_id], "source_urls": [item.get("url") for item in raw.get("sources", []) if isinstance(item, dict) and item.get("url")], "result": raw, "provenance": {"method": "legacy_risk_flags_migration", "legacy_finding_id": flag.get("finding_id"), "limitations": limitations}}
    state.setdefault("assessments", []).append(assessment)
    if outcome in {"triggered", "inconclusive"}:
        severity = str(flag.get("severity") or "medium").casefold()
        if severity not in {"low", "medium", "high"}:
            severity = "medium"
        state.setdefault("findings", []).append({"finding_id": f"finding:csp-address:migrated:{uuid4().hex}", "schema_version": "finding/v1", "category": "csp_address", "assessment_id": assessment_id, "check_id": "csp_address", "title": "Company service provider address", "summary": summary, "subject": {"entity_type": "company", "name": assessment["company_name"]}, "confidence": {"level": confidence, "rationale": "Migrated from the retired CSP risk-flag record.", "limitations": limitations}, "severity": {"level": severity, "rationale": "Migrated from the legacy CSP assessment."}, "potential_impact_risk": "A registered address associated with a company service provider can obscure the entity's operating presence.", "recommended_action_rfi": {"internal_actions": ["Review the company’s operating presence and address rationale."], "rfi": [{"request": "Provide evidence of the company’s operating address and business presence."}]}, "source": {"producer_type": "migration", "producer_name": "legacy_risk_flags", "run_id": run_id, "created_at": created_at}, "relevant_evidence_ids": [evidence_id]})
    return True
