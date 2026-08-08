"""Canonical CDD records for Company Service Provider address screening."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from src.tools.csp_detector import CSPAssessmentError, evaluate_csp_address


def assess_csp_address(state: dict[str, Any], *, address: str | None = None, company_name: str | None = None) -> dict[str, list[dict[str, Any]]]:
    """Produce the auditable CSP assessment and, where needed, its finding."""
    profile = (((state.get("cdd") or {}).get("company_business_profile") or {}).get("customer_static") or {})
    address = address or ((profile.get("registered_address") or {}).get("full_address"))
    company_name = company_name or profile.get("name") or ((state.get("metadata") or {}).get("customer") or {}).get("name")
    run_id, created_at = f"run:csp-address:{uuid4().hex}", datetime.now(UTC).isoformat()
    if not address:
        result, outcome, summary = {"status": "skipped", "reason": "registered_address_missing"}, "inconclusive", "No registered address was available for CSP assessment."
    else:
        try:
            result = evaluate_csp_address(address, company_name=company_name)
            answer = str((result.get("assessment") or {}).get("is_csp") or "inconclusive").casefold()
            outcome = {"yes": "triggered", "no": "not_triggered", "inconclusive": "inconclusive"}.get(answer, "inconclusive")
            summary = str((result.get("assessment") or {}).get("explanation") or "CSP assessment completed.").strip()
        except CSPAssessmentError as exc:
            result, outcome, summary = {"status": "unavailable", "registered_address": address, "reason": str(exc)}, "unavailable", "CSP address assessment could not be completed."
    evidence_id = f"evidence:csp-address:{uuid4().hex}"
    evidence = {"evidence_id": evidence_id, "source": "CSP assessment tool", "tool": "csp_address_assessment", "description": "Assessed registered address for company service provider indicators.", "relevance_tags": ["csp_address", "registered_address"], "cdd_section": "screening", "data": result, "collected_at": created_at}
    assessment_id = f"assessment:csp-address:{uuid4().hex}"
    assessment = {"assessment_id": assessment_id, "assessment_type": "csp_address", "schema_version": "csp_address_assessment/v1", "tool": "csp_address_assessment", "run_id": run_id, "created_at": created_at, "outcome": outcome, "summary": summary, "registered_address": address, "company_name": company_name, "confidence": (result.get("assessment") or {}).get("confidence", "low" if outcome != "not_triggered" else "medium"), "skill_path": result.get("skill_path"), "source_evidence_ids": [evidence_id], "source_urls": [item.get("url") for item in result.get("sources", []) if item.get("url")], "result": result}
    findings: list[dict[str, Any]] = []
    if outcome in {"triggered", "inconclusive"}:
        findings.append({"finding_id": f"finding:csp-address:{uuid4().hex}", "schema_version": "finding/v1", "category": "csp_address", "assessment_id": assessment_id, "check_id": "csp_address", "title": "Company service provider address", "summary": summary, "subject": {"entity_type": "company", "name": company_name}, "confidence": {"level": assessment["confidence"], "rationale": "Derived from the CSP-address assessment.", "limitations": [result.get("reason")] if result.get("reason") else []}, "severity": {"level": "medium", "rationale": "A CSP address requires analyst review."}, "potential_impact_risk": "A registered address associated with a company service provider can obscure the entity's operating presence.", "recommended_action_rfi": {"internal_actions": ["Review the company’s operating presence and address rationale."], "rfi": [{"request": "Provide evidence of the company’s operating address and business presence."}]}, "source": {"producer_type": "tool", "producer_name": "csp_address_assessment", "run_id": run_id, "created_at": created_at}, "relevant_evidence_ids": [evidence_id]})
    return {"evidence": [evidence], "assessments": [assessment], "findings": findings}
