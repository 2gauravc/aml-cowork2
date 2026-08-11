"""Canonical CDD records for CSP address screening."""

from __future__ import annotations
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4
from src.tools.csp_detector import CSPAssessmentError, evaluate_csp_address

_NA_SEVERITY = {
    "level": "not_applicable",
    "rationale": "CSP address detection is an address-service indicator; it does not independently assess the severity of financial-crime risk.",
}


def assess_csp_address(
    state: dict[str, Any],
    *,
    address: str | None = None,
    company_name: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    profile = ((state.get("cdd") or {}).get("company_business_profile") or {}).get(
        "customer_static"
    ) or {}
    address = address or ((profile.get("registered_address") or {}).get("full_address"))
    company_name = (
        company_name
        or profile.get("name")
        or ((state.get("metadata") or {}).get("customer") or {}).get("name")
    )
    run_id, created_at = f"run:csp-address:{uuid4().hex}", datetime.now(UTC).isoformat()
    if not address:
        result = {
            "sources": [
                {
                    "evidence_id": "evidence:csp-address:missing",
                    "title": "Registered address unavailable",
                    "url": "",
                    "content": None,
                    "context_only": True,
                }
            ],
            "assessment": {
                "assessment_id": "assessment:csp-address:missing",
                "source_evidence_ids": ["evidence:csp-address:missing"],
                "is_csp": "inconclusive",
                "confidence": "low",
                "explanation": "No registered address was available for CSP assessment.",
                "limitations": ["Registered address is missing."],
            },
            "finding_evidence_ids": ["evidence:csp-address:missing"],
            "finding_required": True,
            "definition": {},
        }
        outcome = "inconclusive"
    else:
        try:
            result = evaluate_csp_address(address, company_name=company_name)
            answer = result["assessment"]["is_csp"]
            outcome = {
                "yes": "triggered",
                "no": "not_triggered",
                "inconclusive": "inconclusive",
            }[answer]
        except CSPAssessmentError as exc:
            result = {
                "sources": [
                    {
                        "evidence_id": "evidence:csp-address:unavailable",
                        "title": "CSP assessment unavailable",
                        "url": "",
                        "content": None,
                        "context_only": True,
                    }
                ],
                "assessment": {
                    "assessment_id": "assessment:csp-address:unavailable",
                    "source_evidence_ids": ["evidence:csp-address:unavailable"],
                    "is_csp": "inconclusive",
                    "confidence": "low",
                    "explanation": "CSP address assessment could not be completed.",
                    "limitations": [str(exc)],
                },
                "finding_evidence_ids": [],
                "finding_required": False,
                "definition": {},
            }
            outcome = "unavailable"
    evidence = []
    for source in result["sources"]:
        evidence.append(
            {
                "evidence_id": source["evidence_id"],
                "source": (
                    "Tavily"
                    if not source.get("context_only")
                    else "CSP assessment input"
                ),
                "tool": "csp_address_assessment",
                "description": source.get("title") or "CSP address evidence",
                "relevance_tags": ["csp_address", "registered_address"],
                "cdd_section": "screening",
                "data": {
                    **source,
                    "web_search_evidence": {
                        "schema_version": "web_search_evidence/v1",
                        "evidence_id": source["evidence_id"],
                        "evidence_type": (
                            "context"
                            if source.get("context_only")
                            else "web_search_result"
                        ),
                        "source": {
                            "provider": (
                                "Tavily"
                                if not source.get("context_only")
                                else "CSP assessment input"
                            ),
                            "url": source.get("url") or "",
                            "title": source.get("title") or "",
                            "published_at": source.get("published_date"),
                            "retrieved_at": created_at,
                        },
                        "search": {
                            "query": result.get("search_query")
                            or source.get("query")
                            or "",
                            "source_result_id": source["evidence_id"],
                        },
                        "content": {"excerpt": source.get("content")},
                        "context": {
                            "tool": "csp_address_assessment",
                            "subject_key": "company",
                        },
                    },
                },
                "source_url": source.get("url"),
                "published_at": source.get("published_date"),
                "collected_at": created_at,
            }
        )
    model = result["assessment"]
    assessment_id = f"assessment:csp-address:{uuid4().hex}"
    selected = model.get("source_evidence_ids") or []
    assessment = {
        "assessment_id": assessment_id,
        "assessment_type": "csp_address",
        "schema_version": "csp_address_assessment/v2",
        "tool": "csp_address_assessment",
        "run_id": run_id,
        "created_at": created_at,
        "outcome": outcome,
        "is_csp": model["is_csp"],
        "summary": model["explanation"],
        "explanation": model["explanation"],
        "registered_address": address,
        "company_name": company_name,
        "confidence": model["confidence"],
        "limitations": model.get("limitations") or [],
        "source_evidence_ids": selected,
        "definition": {
            "contract_path": (result.get("definition") or {}).get("contract_path"),
            "contract_version": (result.get("definition") or {}).get(
                "contract_version"
            ),
            "presentation_path": (result.get("definition") or {}).get(
                "presentation_path"
            ),
            "presentation_version": (result.get("definition") or {}).get(
                "presentation_version"
            ),
        },
    }
    findings = []
    refs = result.get("finding_evidence_ids") or selected
    if result.get("finding_required"):
        if not refs:
            refs = selected or [evidence[0]["evidence_id"]]
        findings.append(
            {
                "finding_id": f"finding:csp-address:{uuid4().hex}",
                "schema_version": "finding/v1",
                "category": "csp_address",
                "assessment_id": assessment_id,
                "check_id": "csp_address",
                "title": "Company service provider address",
                "summary": assessment["summary"],
                "subject": {
                    "entity_type": "company",
                    "name": company_name or "Customer",
                },
                "confidence": {
                    "level": assessment["confidence"],
                    "rationale": "Derived from the CSP-address assessment.",
                    "limitations": assessment["limitations"],
                },
                "severity": _NA_SEVERITY,
                "potential_impact_risk": "A registered address associated with a company service provider can obscure the entity's operating presence.",
                "recommended_action_rfi": {
                    "internal_actions": [
                        "Review the company’s operating presence and address rationale."
                    ],
                    "rfi": [
                        {
                            "request": "Provide evidence of the company’s operating address and business presence.",
                            "reason": "To establish whether the registered address reflects an operating presence.",
                            "priority": "medium",
                        }
                    ],
                },
                "source": {
                    "producer_type": "tool",
                    "producer_name": "csp_address_assessment",
                    "run_id": run_id,
                    "created_at": created_at,
                },
                "relevant_evidence_ids": refs,
            }
        )
    return {"evidence": evidence, "assessments": [assessment], "findings": findings}
