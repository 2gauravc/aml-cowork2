"""Idempotent normalization for completed CDD snapshots written by retired flows."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


def migrate_legacy_adverse_news(state: dict[str, Any]) -> bool:
    """Normalize retained Adverse News artifacts on load without inventing facts."""
    evidence = state.setdefault("evidence", [])
    assessments = state.setdefault("assessments", [])
    findings = [
        item
        for item in state.setdefault("findings", [])
        if isinstance(item, dict) and item.get("category") == "adverse_news"
    ]
    changed = False
    legacy_assessments = state.pop("adverse_news_assessments", None)
    if isinstance(legacy_assessments, list):
        for item in legacy_assessments:
            if not isinstance(item, dict):
                continue
            item = dict(item)
            item.setdefault("assessment_type", "adverse_news")
            if item.get("assessment_id") and not any(
                existing.get("assessment_id") == item["assessment_id"]
                for existing in assessments
                if isinstance(existing, dict)
            ):
                assessments.append(item)
        changed = True
    adverse_evidence = [
        item
        for item in evidence
        if isinstance(item, dict) and item.get("tool") == "adverse_news_screening"
    ]
    for item in adverse_evidence:
        data = item.get("data") if isinstance(item.get("data"), dict) else {}
        if isinstance(data.get("web_search_evidence"), dict):
            continue
        evidence_id = item.get("evidence_id")
        if not evidence_id:
            continue
        record = {
            "schema_version": "web_search_evidence/v1",
            "evidence_id": evidence_id,
            "evidence_type": "web_search_result",
            "source": {
                "provider": item.get("source") or "Legacy CDD snapshot",
                "url": item.get("source_url") or data.get("url") or "",
                "title": item.get("description") or data.get("title") or "",
                "published_at": item.get("published_at") or data.get("published_date"),
                "retrieved_at": item.get("collected_at")
                or datetime.now(UTC).isoformat(),
            },
            "search": {
                "query": data.get("query") or "",
                "source_result_id": data.get("id") or evidence_id,
            },
            "content": {"excerpt": data.get("content")},
            "context": {
                "tool": "adverse_news_screening",
                "subject_key": data.get("entity_key") or "",
            },
        }
        item["data"] = {**data, "web_search_evidence": record}
        item["provenance"] = {
            **(item.get("provenance") or {}),
            "migration": "adverse_news_artifacts_v1",
        }
        changed = True
    adverse_assessments = [
        item
        for item in assessments
        if isinstance(item, dict) and item.get("assessment_type") == "adverse_news"
    ]
    for finding in findings:
        refs = [
            value
            for value in finding.get("relevant_evidence_ids") or []
            if isinstance(value, str)
        ]
        created_at = (
            (finding.get("source") or {}).get("created_at")
            if isinstance(finding.get("source"), dict)
            else None
        ) or datetime.now(UTC).isoformat()
        if not refs:
            evidence_id = f"evidence:adverse-news:migrated:{uuid4().hex}"
            evidence.append(
                {
                    "evidence_id": evidence_id,
                    "tool": "adverse_news_screening",
                    "source": "Legacy CDD snapshot",
                    "description": "Migration record: the historical adverse-news finding retained no source evidence.",
                    "collected_at": created_at,
                    "data": {
                        "entity_key": "legacy:subject",
                        "web_search_evidence": {
                            "schema_version": "web_search_evidence/v1",
                            "evidence_id": evidence_id,
                            "evidence_type": "web_search_result",
                            "source": {
                                "provider": "Legacy CDD snapshot",
                                "url": "",
                                "title": "Historical evidence unavailable",
                                "published_at": None,
                                "retrieved_at": created_at,
                            },
                            "search": {"query": "", "source_result_id": evidence_id},
                            "content": {"excerpt": None},
                            "context": {
                                "tool": "adverse_news_screening",
                                "subject_key": "legacy:subject",
                            },
                        },
                    },
                    "provenance": {"migration": "adverse_news_artifacts_v1"},
                }
            )
            refs = [evidence_id]
            finding["relevant_evidence_ids"] = refs
            changed = True
        if finding.get("assessment_id"):
            required = {
                "schema_version",
                "title",
                "summary",
                "confidence",
                "severity",
                "potential_impact_risk",
                "recommended_action_rfi",
                "source",
                "relevant_evidence_ids",
            }
            if not required.issubset(finding):
                _normalise_legacy_adverse_finding(
                    finding, refs, finding["assessment_id"], created_at
                )
                changed = True
            continue
        candidates = [
            item
            for item in adverse_assessments
            if set(refs).issubset(set(item.get("source_evidence_ids") or []))
        ]
        assessment = candidates[-1] if len(candidates) == 1 else None
        if assessment is None:
            overlay = (
                finding.get("adverse_news")
                if isinstance(finding.get("adverse_news"), dict)
                else {}
            )
            coverage = (
                overlay.get("screening_coverage")
                if isinstance(overlay.get("screening_coverage"), dict)
                else {}
            )
            subject = (
                finding.get("subject")
                if isinstance(finding.get("subject"), dict)
                else {}
            )
            assessment = {
                "assessment_id": f"assessment:adverse-news:migrated:{uuid4().hex}",
                "assessment_type": "adverse_news",
                "schema_version": "adverse_news_assessment/v1",
                "tool": "adverse_news_screening",
                "run_id": f"migration:adverse-news:{uuid4().hex}",
                "created_at": created_at,
                "outcome": "completed_with_findings",
                "summary": "Migrated adverse-news assessment reconstructed from retained finding evidence.",
                "limitations": [
                    "Historical screening assessment was not retained; this record was reconstructed without new research."
                ],
                "screened_entities": [
                    {
                        "key": "legacy:subject",
                        "entity_type": subject.get("entity_type") or "unknown",
                        "entity_id": subject.get("entity_id"),
                        "name": subject.get("name") or "Unknown",
                    }
                ],
                "queries": coverage.get("queries") or [],
                "source_evidence_ids": refs,
                "entity_outcomes": [
                    {
                        "entity_key": "legacy:subject",
                        "source_evidence_ids": refs,
                        "summary": "Historical finding retained for review.",
                        "limitations": [
                            "Migrated from a legacy finding without entity-level assessment details."
                        ],
                    }
                ],
                "provenance": {"method": "adverse_news_artifacts_v1_migration"},
            }
            assessments.append(assessment)
            adverse_assessments.append(assessment)
        finding["assessment_id"] = assessment["assessment_id"]
        _normalise_legacy_adverse_finding(
            finding, refs, assessment["assessment_id"], created_at
        )
        changed = True
    return changed


def migrate_legacy_digital_footprint(state: dict[str, Any]) -> bool:
    """Make retained Digital Footprint findings safe for the canonical view."""
    findings = [
        x
        for x in state.setdefault("findings", [])
        if isinstance(x, dict) and x.get("category") == "digital_footprint"
    ]
    assessments = state.setdefault("assessments", [])
    changed = False
    for finding in findings:
        if (finding.get("migration") or {}).get(
            "method"
        ) == "digital_footprint_artifacts_v1_migration":
            continue
        refs = [
            x for x in finding.get("relevant_evidence_ids") or [] if isinstance(x, str)
        ]
        assessment = next(
            (
                x
                for x in reversed(assessments)
                if isinstance(x, dict)
                and x.get("assessment_type") == "digital_footprint"
                and set(refs).issubset(set(x.get("source_evidence_ids") or []))
            ),
            None,
        )
        created = (
            (finding.get("source") or {}).get("created_at")
            if isinstance(finding.get("source"), dict)
            else None
        ) or datetime.now(UTC).isoformat()
        if assessment is None:
            assessment = {
                "assessment_id": f"assessment:digital-footprint:migrated:{uuid4().hex}",
                "assessment_type": "digital_footprint",
                "schema_version": "digital_footprint_assessment/v3",
                "tool": "digital_footprint_assessment",
                "run_id": None,
                "created_at": created,
                "outcome": "completed_with_findings",
                "summary": "Migrated Digital Footprint assessment reconstructed from retained finding data.",
                "limitations": [
                    "Historical assessment detail was not retained; no new research was performed."
                ],
                "queries": [],
                "source_evidence_ids": refs,
            }
            assessments.append(assessment)
        subject = (
            finding.get("subject") if isinstance(finding.get("subject"), dict) else {}
        )
        finding.setdefault(
            "finding_id", f"finding:digital-footprint:migrated:{uuid4().hex}"
        )
        finding["schema_version"] = "finding/v1"
        finding["assessment_id"] = assessment["assessment_id"]
        finding["subject"] = {
            "entity_type": subject.get("entity_type") or "company",
            "name": subject.get("name") or "Unknown",
            "entity_id": subject.get("entity_id"),
        }
        finding.setdefault("title", "Historical digital-footprint finding")
        finding.setdefault(
            "summary",
            "Historical digital-footprint finding retained for analyst review.",
        )
        finding.setdefault(
            "confidence",
            {
                "level": "low",
                "rationale": "The retained historical record lacks sufficient assessment detail to reassess confidence.",
                "limitations": ["Migrated from a legacy Digital Footprint record."],
            },
        )
        finding.setdefault(
            "severity",
            {
                "level": "not_applicable",
                "rationale": "The retained historical record lacks sufficient detail to reassess severity.",
            },
        )
        finding.setdefault(
            "potential_impact_risk",
            "The historical footprint concern may require renewed review because underlying assessment detail is incomplete.",
        )
        finding.setdefault(
            "recommended_action_rfi",
            {
                "internal_actions": [
                    "Review the historical record and rerun Digital Footprint assessment if the relationship remains in scope."
                ],
                "rfi": [],
            },
        )
        source = (
            finding.get("source") if isinstance(finding.get("source"), dict) else {}
        )
        finding["source"] = {
            "producer_type": (
                source.get("producer_type")
                if source.get("producer_type") in {"tool", "case_assessment", "case_checker"}
                else "tool"
            ),
            "producer_name": source.get("producer_name")
            or "digital_footprint_assessment",
            "run_id": source.get("run_id"),
            "created_at": source.get("created_at") or created,
        }
        finding["migration"] = {
            **(finding.get("migration") or {}),
            "method": "digital_footprint_artifacts_v1_migration",
            "limitations": [
                "Missing historical Digital Footprint fields are displayed as not retained."
            ],
        }
        changed = True
    return changed


def _normalise_legacy_adverse_finding(
    finding: dict[str, Any], refs: list[str], assessment_id: str, created_at: str
) -> None:
    """Fill canonical generic fields without asserting historical event facts."""
    subject = finding.get("subject") if isinstance(finding.get("subject"), dict) else {}
    entity_type = str(subject.get("entity_type") or "unknown")
    name = str(subject.get("name") or "Unknown")
    finding.setdefault("finding_id", f"finding:adverse-news:migrated:{uuid4().hex}")
    finding["schema_version"] = "finding/v1"
    finding["assessment_id"] = assessment_id
    finding["subject"] = {
        "entity_type": entity_type,
        "name": name,
        "entity_id": subject.get("entity_id"),
    }
    finding.setdefault("title", "Historical adverse-news finding")
    finding.setdefault(
        "summary",
        "Historical adverse-news finding retained for analyst review; its underlying assessment was not retained.",
    )
    finding.setdefault(
        "confidence",
        {
            "level": "low",
            "rationale": "The historical record does not retain sufficient identity-attribution evidence to assess confidence.",
            "limitations": [
                "Migrated from a legacy record without a complete assessment."
            ],
        },
    )
    finding.setdefault(
        "severity",
        {
            "level": "not_applicable",
            "rationale": "The historical record does not retain an event category or legal/procedural status; severity has not been reassessed.",
        },
    )
    finding.setdefault(
        "potential_impact_risk",
        "The retained historical record may require renewed review because its underlying evidence and assessment are incomplete.",
    )
    finding.setdefault(
        "recommended_action_rfi",
        {
            "internal_actions": [
                "Review the retained historical record and perform a new adverse-news assessment if the relationship remains in scope."
            ],
            "rfi": [],
        },
    )
    source = finding.get("source") if isinstance(finding.get("source"), dict) else {}
    finding["source"] = {
        "producer_type": (
            source.get("producer_type")
                if source.get("producer_type") in {"tool", "case_assessment", "case_checker"}
            else "tool"
        ),
        "producer_name": source.get("producer_name") or "adverse_news_screening",
        "run_id": source.get("run_id") or assessment_id,
        "created_at": source.get("created_at") or created_at,
    }
    finding["relevant_evidence_ids"] = refs
    finding["migration"] = {
        **(finding.get("migration") or {}),
        "method": "adverse_news_artifacts_v1_migration",
        "limitations": [
            "Domain-specific identity and event metadata were not added because they were not retained in the historical record."
        ],
    }


def migrate_legacy_risk_flags(state: dict[str, Any]) -> bool:
    """Replace retired CSP flags with canonical records and discard ownership flags."""
    if "risk_flags" not in state:
        return False
    flags = state.pop("risk_flags")
    if not isinstance(flags, list):
        return True
    csp_flags = [
        item
        for item in flags
        if isinstance(item, dict) and item.get("category") == "csp_address"
    ]
    if not csp_flags or any(
        item.get("assessment_type") == "csp_address"
        for item in state.get("assessments") or []
    ):
        return True
    flag = csp_flags[-1]
    created_at = str(flag.get("collected_at") or datetime.now(UTC).isoformat())
    run_id = f"migration:legacy-risk-flags:{uuid4().hex}"
    raw = flag.get("evidence") if isinstance(flag.get("evidence"), dict) else {}
    matching = next(
        (
            item
            for item in reversed(state.get("evidence") or [])
            if isinstance(item, dict) and item.get("tool") == "csp_address_assessment"
        ),
        None,
    )
    if matching:
        raw = raw or (
            matching.get("data") if isinstance(matching.get("data"), dict) else {}
        )
    assessment_data = (
        raw.get("assessment") if isinstance(raw.get("assessment"), dict) else {}
    )
    raw_evaluation = (
        flag.get("evaluation")
        if flag.get("evaluation") is not None
        else assessment_data.get("is_csp")
    )
    evaluation = str(raw_evaluation).casefold() if raw_evaluation is not None else ""
    outcome = {
        "yes": "triggered",
        "no": "not_triggered",
        "inconclusive": "inconclusive",
    }.get(evaluation, "inconclusive")
    limitations = (
        []
        if evaluation in {"yes", "no", "inconclusive"}
        else ["Legacy CSP outcome was missing or invalid; migrated as inconclusive."]
    )
    summary = str(
        flag.get("description")
        or assessment_data.get("explanation")
        or "Legacy CSP assessment was migrated without a recorded explanation."
    )
    profile = ((state.get("cdd") or {}).get("company_business_profile") or {}).get(
        "customer_static"
    ) or {}
    evidence_id = matching.get("evidence_id") if matching else None
    if not evidence_id:
        evidence_id = f"evidence:csp-address:migrated:{uuid4().hex}"
        state.setdefault("evidence", []).append(
            {
                "evidence_id": evidence_id,
                "source": "Legacy CDD snapshot",
                "tool": "csp_address_assessment",
                "description": "Migrated CSP address evidence from a retired risk flag.",
                "relevance_tags": ["csp_address", "registered_address", "migration"],
                "cdd_section": "screening",
                "data": raw,
                "collected_at": created_at,
                "provenance": {
                    "method": "legacy_risk_flags_migration",
                    "legacy_finding_id": flag.get("finding_id"),
                },
            }
        )
    assessment_id = f"assessment:csp-address:migrated:{uuid4().hex}"
    confidence = str(assessment_data.get("confidence") or "low")
    if confidence not in {"low", "medium", "high"}:
        confidence = "low"
    assessment = {
        "assessment_id": assessment_id,
        "assessment_type": "csp_address",
        "schema_version": "csp_address_assessment/v1",
        "tool": "csp_address_assessment",
        "run_id": run_id,
        "created_at": created_at,
        "outcome": outcome,
        "summary": summary,
        "registered_address": raw.get("registered_address")
        or ((profile.get("registered_address") or {}).get("full_address")),
        "company_name": raw.get("company_name") or profile.get("name"),
        "confidence": confidence,
        "skill_path": raw.get("skill_path"),
        "source_evidence_ids": [evidence_id],
        "source_urls": [
            item.get("url")
            for item in raw.get("sources", [])
            if isinstance(item, dict) and item.get("url")
        ],
        "result": raw,
        "provenance": {
            "method": "legacy_risk_flags_migration",
            "legacy_finding_id": flag.get("finding_id"),
            "limitations": limitations,
        },
    }
    state.setdefault("assessments", []).append(assessment)
    if outcome in {"triggered", "inconclusive"}:
        state.setdefault("findings", []).append(
            {
                "finding_id": f"finding:csp-address:migrated:{uuid4().hex}",
                "schema_version": "finding/v1",
                "category": "csp_address",
                "assessment_id": assessment_id,
                "check_id": "csp_address",
                "title": "Company service provider address",
                "summary": summary,
                "subject": {
                    "entity_type": "company",
                    "name": assessment["company_name"] or "Customer",
                },
                "confidence": {
                    "level": confidence,
                    "rationale": "Migrated from the retired CSP risk-flag record.",
                    "limitations": limitations,
                },
                "severity": {
                    "level": "not_applicable",
                    "rationale": "CSP address detection is an address-service indicator; it does not independently assess the severity of financial-crime risk.",
                },
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
                "relevant_evidence_ids": [evidence_id],
                "migration": {
                    "method": "legacy_risk_flags_migration",
                    "legacy_finding_id": flag.get("finding_id"),
                    "limitations": limitations,
                },
            }
        )
    return True


def migrate_legacy_csp_address(state: dict[str, Any]) -> bool:
    """Normalize retained CSP artifacts for the v2 contract and stable view.

    This runs after retired ``risk_flags`` have been converted.  It preserves the
    historical conclusion and sources; only missing normalized evidence and the
    v2 neutral-assessment fields are added.
    """
    evidence = state.setdefault("evidence", [])
    assessments = state.setdefault("assessments", [])
    changed = False
    csp_evidence = [
        item
        for item in evidence
        if isinstance(item, dict) and item.get("tool") == "csp_address_assessment"
    ]
    for item in csp_evidence:
        evidence_id = item.get("evidence_id")
        if not isinstance(evidence_id, str) or not evidence_id:
            continue
        data = item.get("data") if isinstance(item.get("data"), dict) else {}
        if isinstance(data.get("web_search_evidence"), dict):
            continue
        item["data"] = {
            **data,
            "web_search_evidence": {
                "schema_version": "web_search_evidence/v1",
                "evidence_id": evidence_id,
                "evidence_type": (
                    "web_search_result" if item.get("source_url") else "context"
                ),
                "source": {
                    "provider": item.get("source") or "Legacy CDD snapshot",
                    "url": item.get("source_url") or data.get("url") or "",
                    "title": item.get("description") or data.get("title") or "",
                    "published_at": item.get("published_at")
                    or data.get("published_date"),
                    "retrieved_at": item.get("collected_at")
                    or datetime.now(UTC).isoformat(),
                },
                "search": {
                    "query": data.get("query") or "",
                    "source_result_id": data.get("id") or evidence_id,
                },
                "content": {"excerpt": data.get("content")},
                "context": {"tool": "csp_address_assessment", "subject_key": "company"},
            },
        }
        item["provenance"] = {
            **(item.get("provenance") or {}),
            "migration": "csp_address_artifacts_v2",
        }
        changed = True
    for assessment in assessments:
        if (
            not isinstance(assessment, dict)
            or assessment.get("assessment_type") != "csp_address"
        ):
            continue
        if assessment.get("schema_version") == "csp_address_assessment/v2":
            continue
        result = (
            assessment.get("result")
            if isinstance(assessment.get("result"), dict)
            else {}
        )
        result_assessment = (
            result.get("assessment")
            if isinstance(result.get("assessment"), dict)
            else {}
        )
        evaluation = result_assessment.get("is_csp")
        if evaluation not in {"yes", "no", "inconclusive"}:
            evaluation = {"triggered": "yes", "not_triggered": "no"}.get(
                assessment.get("outcome"), "inconclusive"
            )
        assessment["schema_version"] = "csp_address_assessment/v2"
        assessment.setdefault(
            "limitations", (assessment.get("provenance") or {}).get("limitations") or []
        )
        assessment["is_csp"] = evaluation
        assessment["explanation"] = (
            assessment.get("summary")
            or result_assessment.get("explanation")
            or "Historical CSP assessment retained for review."
        )
        assessment["source_evidence_ids"] = [
            item
            for item in assessment.get("source_evidence_ids") or []
            if isinstance(item, str)
        ]
        assessment["provenance"] = {
            **(assessment.get("provenance") or {}),
            "migration": "csp_address_artifacts_v2",
        }
        changed = True
    return changed
