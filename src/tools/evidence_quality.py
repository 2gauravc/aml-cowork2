"""Deterministic, SKILL-configured evidence-quality assessments."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SKILL_PATH = PROJECT_ROOT / "skills" / "evidence-quality" / "SKILL.md"


class EvidenceQualityError(RuntimeError):
    pass


def load_evidence_quality_definition(path: str | Path = SKILL_PATH) -> dict[str, Any]:
    try:
        _, front, instructions = Path(path).read_text(encoding="utf-8").split("---\n", 2)
        metadata = yaml.safe_load(front)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise EvidenceQualityError(f"Evidence Quality skill could not be loaded: {exc}") from exc
    assessment = metadata.get("assessment") if isinstance(metadata, dict) else None
    claims = metadata.get("claims") if isinstance(metadata, dict) else None
    dimensions = metadata.get("dimensions") if isinstance(metadata, dict) else None
    if not isinstance(assessment, dict) or assessment.get("schema") != "evidence_quality_assessment/v1":
        raise EvidenceQualityError("Evidence Quality skill must declare assessment.schema")
    if not isinstance(claims, list) or not claims or any(not isinstance(item, dict) or not item.get("id") for item in claims):
        raise EvidenceQualityError("Evidence Quality skill must declare identified claims")
    expected_dimensions = {"veracity_source_integrity", "adequacy", "consistency", "plausibility"}
    if not isinstance(dimensions, list) or {item.get("key") for item in dimensions if isinstance(item, dict)} != expected_dimensions or any(not isinstance(item.get("label"), str) or not item["label"].strip() for item in dimensions if isinstance(item, dict)):
        raise EvidenceQualityError("Evidence Quality skill must declare labelled source-integrity, adequacy, consistency, and plausibility dimensions")
    allowed_sections = {"customer_business_profile", "ownership_and_control", "identity_verification", "screening"}
    if any(item.get("cdd_section") not in allowed_sections for item in claims):
        raise EvidenceQualityError("Every Evidence Quality claim must declare a CDD section")
    return {
        "assessment": assessment,
        "claims": sorted(claims, key=lambda item: item.get("order", 0)),
        "dimensions": dimensions,
        "source_classes": metadata.get("source_classes") or {},
        "instructions": instructions.strip(),
        "path": str(path),
    }


def evaluate_evidence_quality(state: dict[str, Any]) -> dict[str, Any]:
    definition = load_evidence_quality_definition()
    assessments = [_evaluate_claim(state, claim, definition) for claim in definition["claims"]]
    return {"definition": definition, "assessments": assessments}


def _evaluate_claim(state: dict[str, Any], claim: dict[str, Any], definition: dict[str, Any]) -> dict[str, Any]:
    value, subject, applicable = _claim_value(state, str(claim["value_adapter"]))
    selected, excluded = _select_evidence(state.get("evidence") or [], claim, definition, subject, value)
    source_classes = {item["source_class"] for item in selected}
    synthetic = [item for item in selected if item["source_class"] == "generated_or_synthetic"]
    unknown = [item["evidence_id"] for item in selected if item["source_class"] == "unknown"]
    if not applicable:
        integrity = _dimension("not_applicable", "This check could not be applied because the CDD claim is unavailable.")
        adequacy = _dimension("not_applicable", "No evidence sufficiency decision is needed because the claim is unavailable.")
    elif not selected:
        status = "invalid" if excluded else "unavailable"
        integrity = _dimension(status, "The available evidence could not be linked to this customer and claim.")
        adequacy = _dimension("gap", "More evidence is needed to support this claim.")
    elif synthetic:
        integrity = _dimension("inconclusive", "The evidence includes a generated or synthetic item, so source reliability cannot be confirmed from that item alone.", [item["evidence_id"] for item in synthetic], [item.get("provenance") for item in synthetic if item.get("provenance")])
        adequacy = _adequacy(claim, selected, source_classes)
    elif unknown:
        rationale = (
            "The extracted identity-document record does not retain explicit document provenance, so it cannot independently confirm the individual’s identity."
            if claim.get("value_adapter") == "identity_verification"
            else "The source of some retained evidence is not recorded, so source reliability cannot be confirmed."
        )
        integrity = _dimension("inconclusive", rationale, unknown)
        adequacy = _adequacy(claim, selected, source_classes)
    else:
        integrity = _dimension("not_triggered", "The retained evidence is linked to this customer and has a recorded source.")
        adequacy = _adequacy(claim, selected, source_classes)
    consistency = _consistency(claim, value, selected, state, applicable)
    plausibility = _plausibility(claim, value, selected, state, applicable)
    statuses = {integrity["outcome"], adequacy["outcome"], consistency["outcome"], plausibility["outcome"]}
    outcome = next((status for status in ("invalid", "unavailable", "inconclusive", "gap") if status in statuses), "not_triggered")
    return {
        "claim_id": claim["id"], "title": claim["title"], "display_order": claim.get("order", 0),
        "claim": {"value": value, "subject": subject, "applicable": applicable},
        "outcome": outcome,
        "summary": "Evidence reviewed: source reliability is confirmed, the evidence is sufficient, and no material inconsistency or plausibility concern was identified." if outcome == "not_triggered" else _summary(claim["title"], integrity, adequacy, consistency, plausibility),
        "dimensions": {"veracity_source_integrity": integrity, "adequacy": adequacy, "consistency": consistency, "plausibility": plausibility},
        "cdd_section": claim["cdd_section"],
        "selected_evidence": selected, "excluded_evidence": excluded,
        "severity": claim.get("severity", "medium"), "action": claim.get("action", "Review the evidence quality concern."),
    }


def _claim_value(state: dict[str, Any], adapter: str) -> tuple[dict[str, Any], dict[str, Any], bool]:
    cdd = state.get("cdd") or {}
    profile = ((cdd.get("company_business_profile") or {}).get("customer_static") or {})
    metadata = state.get("metadata") or {}
    customer = metadata.get("customer") or {}
    subject = {"entity_type": "company", "entity_id": str(profile.get("registration_number") or "") or None, "name": profile.get("name") or customer.get("name") or "Customer"}
    if adapter == "company_registration":
        value = {key: profile.get(key) for key in ("name", "registration_number", "jurisdiction", "company_status")}
        return value, subject, bool(value.get("name") and value.get("registration_number"))
    if adapter == "ownership_and_control":
        ownership = cdd.get("ownership_and_control") or {}
        value = {"case_id": (metadata.get("kyc_case") or {}).get("case_id"), "status": ownership.get("status"), "ubos": ownership.get("ubos") or []}
        # An ownership structure remains a claim to assess when it has been
        # evaluated but no individual UBO was identified.  CDD Completeness
        # reports that separate gap; Evidence Quality must still evaluate the
        # retained org-chart and members evidence.
        return value, subject, value["status"] in {"complete", "incomplete"}
    if adapter == "identity_verification":
        idv = cdd.get("individual_identity_verification") or {}
        value = {"required_individuals": idv.get("required_individuals") or [], "validated_document_count": sum(1 for document in state.get("documents") or [] if _valid_idv_document(document))}
        return value, subject, bool(value["required_individuals"])
    if adapter == "business_activity":
        candidates = [item for item in state.get("assessments") or [] if item.get("assessment_type") == "digital_footprint"]
        profile_assessment = candidates[-1] if candidates else {}
        digital_profile = profile_assessment.get("digital_business_profile") or {}
        value = {"name": profile.get("name") or customer.get("name"), "registry_activity": profile.get("activity_type"), "business_activity": digital_profile.get("business_activity"), "geographic_presence": digital_profile.get("geographic_presence") or [], "registered_address": ((profile.get("registered_address") or {}).get("full_address") if isinstance(profile.get("registered_address"), dict) else profile.get("registered_address"))}
        return value, subject, bool(value.get("business_activity"))
    if adapter == "screening_conclusions":
        screening = [item for item in state.get("assessments") or [] if item.get("assessment_type") in {"adverse_news", "digital_footprint"}]
        value = {"outcomes": [{"type": item.get("assessment_type"), "outcome": item.get("outcome"), "summary": item.get("summary")} for item in screening]}
        return value, subject, bool(screening)
    raise EvidenceQualityError(f"Unknown claim value adapter: {adapter}")


def _select_evidence(evidence: list[dict[str, Any]], claim: dict[str, Any], definition: dict[str, Any], subject: dict[str, Any], value: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    selected, excluded = [], []
    tools = set(claim.get("evidence_tools") or [])
    required = {str(value.get(field)).casefold() for field in claim.get("required_match_fields") or [] if value.get(field) not in (None, "")}
    for item in evidence:
        if item.get("tool") not in tools:
            continue
        evidence_id = item.get("evidence_id")
        if not evidence_id:
            continue
        haystack = _text(item.get("data")) + " " + _text(item.get("description"))
        if required and not all(token in haystack.casefold() for token in required):
            excluded.append({"evidence_id": evidence_id, "reason": "Configured subject or claim values did not match the retained evidence."})
            continue
        source_class, provenance = _source_class(item, definition.get("source_classes") or {})
        selected.append({"evidence_id": evidence_id, "tool": item.get("tool"), "source": item.get("source"), "source_class": source_class, "provenance": provenance, "cdd_section": item.get("cdd_section"), "evidence_area": item.get("evidence_area"), "relationship": "supports", "selection_reason": "The evidence matches this customer and claim."})
    return selected, excluded


def _source_class(item: dict[str, Any], configured: dict[str, Any]) -> tuple[str, dict[str, str] | None]:
    provenance = _synthetic_provenance(item.get("data"))
    if provenance:
        return "generated_or_synthetic", provenance
    if item.get("tool") == "extract_idv_documents" and not _has_explicit_idv_provenance(item.get("data")):
        return "unknown", None
    if not item.get("source") or not item.get("tool"):
        return "unknown", None
    return str(configured.get(item.get("tool")) or "unknown"), None


def _synthetic_provenance(data: Any) -> dict[str, str] | None:
    """Read explicit source metadata only; never classify arbitrary content text."""
    if not isinstance(data, dict):
        return None
    candidates = [("source", data.get("source")), ("source_type", data.get("source_type")), ("provenance", data.get("provenance"))]
    artifact = data.get("artifact")
    if isinstance(artifact, dict):
        candidates.extend([("artifact.source", artifact.get("source")), ("artifact.source_type", artifact.get("source_type")), ("artifact.provenance", artifact.get("provenance"))])
    for path, value in candidates:
        if isinstance(value, str) and any(marker in value.casefold() for marker in ("synthetic", "generated")):
            return {"field": path, "value": value}
    for path, value in (("synthetic", data.get("synthetic")), ("synthetic_demo", data.get("synthetic_demo")), ("artifact.synthetic", artifact.get("synthetic") if isinstance(artifact, dict) else None)):
        if value is True:
            return {"field": path, "value": "true"}
    documents = data.get("documents")
    if isinstance(documents, list):
        for index, document in enumerate(documents):
            if not isinstance(document, dict):
                continue
            nested = _synthetic_provenance({"artifact": document.get("artifact")})
            if nested:
                return {"field": f"documents[{index}].{nested['field']}", "value": nested["value"]}
    return None


def _has_explicit_idv_provenance(data: Any) -> bool:
    """Accept only structured provenance from the extracted document artifact."""
    if not isinstance(data, dict) or not isinstance(data.get("documents"), list):
        return False
    for document in data["documents"]:
        artifact = document.get("artifact") if isinstance(document, dict) else None
        if not isinstance(artifact, dict):
            return False
        if not any(artifact.get(field) not in (None, "") for field in ("provenance", "source_type", "synthetic")):
            return False
    return bool(data["documents"])


def _adequacy(claim: dict[str, Any], selected: list[dict[str, Any]], source_classes: set[str]) -> dict[str, Any]:
    allowed = set(claim.get("allowed_source_classes") or [])
    accepted = [item for item in selected if item["source_class"] in allowed]
    required = int(claim.get("min_supporting_evidence", 1))
    if len(accepted) >= required:
        return _dimension("not_triggered", "The available evidence is sufficient for this check.")
    return _dimension("gap", "More suitable evidence is needed for this check.", [item["evidence_id"] for item in selected])


def _consistency(claim: dict[str, Any], value: dict[str, Any], selected: list[dict[str, Any]], state: dict[str, Any], applicable: bool) -> dict[str, Any]:
    if not applicable:
        return _dimension("not_applicable", "No consistency decision is needed because the claim is unavailable.")
    if claim["value_adapter"] == "business_activity":
        registry_activity = str(value.get("registry_activity") or "").strip()
        digital_activity = str(value.get("business_activity") or "").strip()
        if registry_activity and digital_activity and not _descriptions_overlap(registry_activity, digital_activity):
            return _dimension("inconclusive", "The registry/KYC activity and the digital business description appear materially different. The retained evidence does not explain how they relate, so an analyst should confirm the current principal activity.", [item["evidence_id"] for item in selected])
    if claim["value_adapter"] == "identity_verification":
        required_count = len(value.get("required_individuals") or [])
        if required_count and value.get("validated_document_count", 0) < required_count:
            return _dimension("inconclusive", "The final ID&V record does not show a validated document for every required individual. Reconcile the policy requirement and document-validation records.", [item["evidence_id"] for item in selected])
    if claim["value_adapter"] == "screening_conclusions":
        outcomes = value.get("outcomes") or []
        if any(item.get("outcome") in {"completed_clear", "clear", "negative"} for item in outcomes) and any(item.get("tool") == "adverse_news_screening" for item in selected):
            return _dimension("inconclusive", "A clear screening conclusion needs entity-specific retained results. Generic screening-resource pages alone do not demonstrate clearance.", [item["evidence_id"] for item in selected])
    return _dimension("not_triggered", "No material contradiction was identified in the retained information for this check.")


def _plausibility(claim: dict[str, Any], value: dict[str, Any], selected: list[dict[str, Any]], state: dict[str, Any], applicable: bool) -> dict[str, Any]:
    if not applicable:
        return _dimension("not_applicable", "No plausibility decision is needed because the claim is unavailable.")
    if claim["value_adapter"] == "business_activity":
        if not value.get("geographic_presence"):
            return _dimension("inconclusive", "The retained business description does not include corroborated operating-location evidence. Obtain a current operating address, website, licence, or other business-presence evidence.", [item["evidence_id"] for item in selected])
        address = str(value.get("registered_address") or "").casefold()
        activity = f"{value.get('registry_activity') or ''} {value.get('business_activity') or ''}".casefold()
        residential_markers = ("apartment", "residential", "flat", "unit ")
        operational_markers = ("manufactur", "factory", "industrial", "warehouse")
        if any(marker in address for marker in residential_markers) and any(marker in activity for marker in operational_markers):
            return _dimension("inconclusive", "The retained address appears residential while the stated activity suggests a substantial operating footprint. Obtain evidence that explains the operating location.", [item["evidence_id"] for item in selected])
    return _dimension("not_triggered", "The retained information does not present a clear fact-pattern mismatch requiring additional corroboration.")


def _dimension(outcome: str, rationale: str, evidence_ids: list[str] | None = None, provenance: list[dict[str, str]] | None = None) -> dict[str, Any]:
    return {"outcome": outcome, "rationale": rationale, "evidence_ids": evidence_ids or [], "provenance": provenance or []}


def _summary(title: str, integrity: dict[str, Any], adequacy: dict[str, Any], consistency: dict[str, Any], plausibility: dict[str, Any]) -> str:
    concerns = []
    if integrity["outcome"] not in {"not_triggered", "not_applicable"}:
        concerns.append("source reliability could not be confirmed")
    if adequacy["outcome"] not in {"not_triggered", "not_applicable"}:
        concerns.append("more evidence is needed")
    if consistency["outcome"] not in {"not_triggered", "not_applicable"}:
        concerns.append("the retained information needs reconciliation")
    if plausibility["outcome"] not in {"not_triggered", "not_applicable"}:
        concerns.append("the fact pattern needs further corroboration")
    return f"{title}: {' and '.join(concerns)}."


def _text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_text(item) for item in value)
    return str(value or "")


def _valid_idv_document(document: dict[str, Any]) -> bool:
    validation = (document.get("processing") or {}).get("validation") or {}
    return document.get("status") == "processed" and (document.get("gap") or {}).get("status") == "resolved" and validation.get("accepted_type") is True and validation.get("name_match") is True


def _descriptions_overlap(left: str, right: str) -> bool:
    stop_words = {"and", "the", "for", "with", "services", "service", "business", "company", "activities", "activity", "limited", "private"}
    left_terms = {term for term in _words(left) if term not in stop_words}
    right_terms = {term for term in _words(right) if term not in stop_words}
    return bool(left_terms & right_terms)


def _words(value: str) -> list[str]:
    token = ""
    words = []
    for character in value.casefold():
        if character.isalnum():
            token += character
        elif token:
            words.append(token)
            token = ""
    if token:
        words.append(token)
    return words
