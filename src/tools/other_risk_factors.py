"""Deterministic, SKILL-configured Other Risk Factors assessments."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import yaml
from openai import OpenAI, OpenAIError
from src.utils.langsmith_tracing import traced_openai_client

from src.utils.skill_definitions import SkillDefinitionError, load_skill_definition

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SKILL_PATH = PROJECT_ROOT / "skills" / "other-risk-factors" / "SKILL.md"
SECTIONS = {"customer_business_profile", "ownership_and_control", "identity_verification", "screening"}
DEFAULT_MODEL = os.getenv("OPENAI_OTHER_RISK_FACTORS_MODEL") or os.getenv("OPENAI_MODEL", "gpt-5.6")


class OtherRiskFactorsError(RuntimeError):
    pass


def load_other_risk_factors_definition(path: str | Path = SKILL_PATH) -> dict[str, Any]:
    try:
        metadata, definition_path, definition_version = load_skill_definition(path)
    except (OSError, SkillDefinitionError) as exc:
        raise OtherRiskFactorsError(f"Other Risk Factors skill could not be loaded: {exc}") from exc
    assessment = metadata.get("assessment") if isinstance(metadata, dict) else None
    factors = metadata.get("factors") if isinstance(metadata, dict) else None
    expected = {"high_risk_industry", "high_aml_risk_jurisdiction_link", "high_tax_risk_jurisdiction_link", "complex_ownership_structure", "trust_or_nominee_arrangement"}
    if not isinstance(assessment, dict) or assessment.get("schema") != "other_risk_factors_assessment/v1":
        raise OtherRiskFactorsError("Other Risk Factors skill must declare assessment.schema")
    if not isinstance(factors, list) or {item.get("id") for item in factors if isinstance(item, dict)} != expected:
        raise OtherRiskFactorsError("Other Risk Factors skill must declare the five configured factors")
    if any(item.get("cdd_section") not in SECTIONS for item in factors):
        raise OtherRiskFactorsError("Every Other Risk Factors factor must declare a CDD section")
    return {"assessment": assessment, "factors": sorted(factors, key=lambda item: item.get("order", 0)), "path": definition_path, "definition_version": definition_version}


def evaluate_other_risk_factors(state: dict[str, Any]) -> dict[str, Any]:
    definition = load_other_risk_factors_definition()
    return {"definition": definition, "assessments": [_evaluate(state, factor) for factor in definition["factors"]]}


def _evaluate(state: dict[str, Any], factor: dict[str, Any]) -> dict[str, Any]:
    factor_id = factor["id"]
    selected_evidence, upstream = _select_context(state, factor["cdd_section"])
    if factor_id == "high_risk_industry":
        outcome, summary, detail = _industry(state, factor)
    elif factor_id == "high_aml_risk_jurisdiction_link":
        outcome, summary, detail = _aml_jurisdiction(state, factor)
    elif factor_id == "high_tax_risk_jurisdiction_link":
        outcome, summary, detail = _tax_jurisdiction(state, factor)
    elif factor_id.endswith("jurisdiction_link"):
        outcome, summary, detail = _jurisdiction(state, factor)
    elif factor_id == "complex_ownership_structure":
        outcome, summary, detail = _complexity(state, factor)
    else:
        outcome, summary, detail = _trust_nominee(state, factor)
    return {"factor_id": factor_id, "title": factor["title"], "display_order": factor.get("order", 0), "cdd_section": factor["cdd_section"], "method": factor["method"], "outcome": outcome, "summary": summary, "detail": detail, "severity": factor["severity"], "action": factor["action"], "selected_evidence": selected_evidence, "upstream_assessment_ids": upstream["assessments"], "upstream_finding_ids": upstream["findings"]}


def _industry(state: dict[str, Any], factor: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    profile = ((state.get("cdd") or {}).get("company_business_profile") or {}).get("customer_static") or {}
    digital = _latest_assessment(state, "digital_footprint").get("digital_business_profile") or {}
    activity = " ".join(str(value or "") for value in (profile.get("activity_type"), digital.get("business_activity"))).strip()
    if not activity:
        return "inconclusive", "The retained records do not identify a principal business activity to assess.", {"activity": "", "risk_indicators": [], "classification_provenance": {"method": "not_run"}}
    classification = _classify_industry(activity, factor)
    outcome = classification["outcome"]
    if outcome == "triggered":
        summary = "The retained business activity is classified as a high-risk industry for AML purposes."
    elif outcome == "inconclusive":
        summary = "The retained business activity cannot be confidently classified from the available description."
    else:
        summary = "The retained business activity is not classified as a high-risk industry under the configured AML definition."
    return outcome, summary, {"activity": activity, "risk_indicators": classification["risk_indicators"], "classification_rationale": classification["rationale"], "classification_provenance": {"method": "llm_structured", "model": DEFAULT_MODEL}}


def _classify_industry(activity: str, factor: dict[str, Any]) -> dict[str, Any]:
    """Classify retained activity only; the SKILL owns the risk definition and examples."""
    if not os.getenv("OPENAI_API_KEY"):
        raise OtherRiskFactorsError("OPENAI_API_KEY is required for high-risk industry classification")
    schema = {"type": "object", "additionalProperties": False, "properties": {"outcome": {"type": "string", "enum": ["triggered", "not_triggered", "inconclusive"]}, "rationale": {"type": "string"}, "risk_indicators": {"type": "array", "items": {"type": "string"}}}, "required": ["outcome", "rationale", "risk_indicators"]}
    prompt = "Classify the supplied business activity only. Do not use external knowledge about the named customer or add facts. Apply this AML risk definition and use the examples as illustrative, not exhaustive. Return triggered only where the retained description supports a high-risk-industry classification; return inconclusive if it is too vague.\n\n" + json.dumps({"risk_definition": factor.get("risk_definition"), "examples": factor.get("examples") or [], "business_activity": activity})
    try:
        result = traced_openai_client(OpenAI()).responses.create(model=DEFAULT_MODEL, input=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}], text={"format": {"type": "json_schema", "name": "high_risk_industry", "schema": schema, "strict": True}})
        parsed = json.loads(result.output_text)
    except OpenAIError as exc:
        raise OtherRiskFactorsError(f"High-risk industry classification failed: {exc}") from exc
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise OtherRiskFactorsError("High-risk industry classification did not return valid structured output") from exc
    if not isinstance(parsed, dict) or parsed.get("outcome") not in {"triggered", "not_triggered", "inconclusive"}:
        raise OtherRiskFactorsError("High-risk industry classification returned an invalid outcome")
    return {"outcome": parsed["outcome"], "rationale": str(parsed.get("rationale") or "No rationale was recorded."), "risk_indicators": [str(item) for item in parsed.get("risk_indicators") or []]}


def _jurisdiction(state: dict[str, Any], factor: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    links = _jurisdiction_links(state)
    high_risk = {str(code).upper() for code in factor.get("high_risk_jurisdictions", [])}
    matched = [link for link in links if link["country_code"] in high_risk]
    if matched:
        countries = ", ".join(sorted({item["country_code"] for item in matched}))
        return "triggered", f"A retained customer, ownership, or control record links the case to configured high-risk jurisdiction(s): {countries}.", {"jurisdiction_links": matched, "matched_policy_codes": sorted({item["country_code"] for item in matched})}
    if not links:
        return "inconclusive", "The retained records do not contain enough jurisdiction information to assess this policy.", {"jurisdiction_links": [], "matched_policy_codes": []}
    return "not_triggered", "No retained jurisdiction link matches the configured policy list.", {"jurisdiction_links": links, "matched_policy_codes": []}


def _aml_jurisdiction(state: dict[str, Any], factor: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    inputs = _jurisdiction_classification_inputs(state)
    inputs["ownership_and_control_links"] = [link for link in inputs["jurisdiction_links"] if "members" in link["source"]]
    policy_links = _policy_jurisdiction_links(inputs["jurisdiction_links"], factor)
    if not policy_links:
        return "not_triggered", "No retained jurisdiction link matches the configured FATF AML-risk lists.", {"inputs": inputs, "matched_jurisdiction_links": [], "policy_lists": factor.get("jurisdiction_lists") or [], "classification_provenance": {"method": "not_run", "reason": "No configured AML-risk jurisdiction link."}}
    if not any(value for key, value in inputs.items() if key not in {"jurisdiction_links", "ownership_and_control_links"}):
        return "inconclusive", "The retained CDD records do not contain enough information to assess AML-risk jurisdiction links.", {"inputs": inputs, "matched_jurisdiction_links": [], "classification_provenance": {"method": "not_run"}}
    inputs["policy_jurisdiction_links"] = policy_links
    classification = _classify_aml_jurisdiction(inputs, factor)
    links = inputs["jurisdiction_links"]
    matched = [links[index] for index in classification["matched_link_indexes"] if 0 <= index < len(links)]
    summary = "The retained CDD information indicates an AML-risk jurisdiction link requiring analyst review." if classification["outcome"] == "triggered" else "The retained CDD information is insufficient to confidently assess AML-risk jurisdiction links." if classification["outcome"] == "inconclusive" else "No AML-risk jurisdiction link was identified from the retained CDD information."
    return classification["outcome"], summary, {"inputs": inputs, "matched_jurisdiction_links": matched, "policy_lists": factor.get("jurisdiction_lists") or [], "classification_rationale": classification["rationale"], "classification_provenance": {"method": "llm_structured", "model": DEFAULT_MODEL}}


def _tax_jurisdiction(state: dict[str, Any], factor: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    inputs = _jurisdiction_classification_inputs(state)
    links = inputs["jurisdiction_links"]
    policy_links = _policy_jurisdiction_links(links, factor)
    if not policy_links:
        return "not_triggered", "No retained jurisdiction link matches the configured tax-risk jurisdiction lists.", {"inputs": inputs, "matched_jurisdiction_links": [], "policy_lists": factor.get("jurisdiction_lists") or [], "classification_provenance": {"method": "not_run", "reason": "No configured tax-risk jurisdiction link."}}
    if not any(value for key, value in inputs.items() if key != "jurisdiction_links"):
        return "inconclusive", "The retained business profile does not contain enough information to assess tax-risk jurisdiction links.", {"inputs": inputs, "matched_jurisdiction_links": [], "classification_provenance": {"method": "not_run"}}
    inputs["policy_jurisdiction_links"] = policy_links
    classification = _classify_tax_jurisdiction(inputs, factor)
    matched = [links[index] for index in classification["matched_link_indexes"] if 0 <= index < len(links)]
    summary = "The retained business-profile information indicates a tax-risk jurisdiction link requiring analyst review." if classification["outcome"] == "triggered" else "The retained business-profile information is insufficient to confidently assess tax-risk jurisdiction links." if classification["outcome"] == "inconclusive" else "No tax-risk jurisdiction link was identified from the retained business-profile information."
    return classification["outcome"], summary, {"inputs": inputs, "matched_jurisdiction_links": matched, "policy_lists": factor.get("jurisdiction_lists") or [], "classification_rationale": classification["rationale"], "classification_provenance": {"method": "llm_structured", "model": DEFAULT_MODEL}}


def _jurisdiction_classification_inputs(state: dict[str, Any]) -> dict[str, Any]:
    profile = ((state.get("cdd") or {}).get("company_business_profile") or {}).get("customer_static") or {}
    digital = _latest_assessment(state, "digital_footprint").get("digital_business_profile") or {}
    return {"country_of_incorporation": profile.get("jurisdiction"), "registered_address_country": (profile.get("registered_address") or {}).get("country_code") if isinstance(profile.get("registered_address"), dict) else None, "business_activity": digital.get("business_activity") or profile.get("activity_type"), "operating_locations": digital.get("geographic_presence") or [], "customers": digital.get("customers") or [], "suppliers": digital.get("suppliers") or [], "commercial_relationships": digital.get("commercial_relationships") or [], "jurisdiction_links": _jurisdiction_links(state)}


def _policy_jurisdiction_links(links: list[dict[str, str]], factor: dict[str, Any]) -> list[dict[str, Any]]:
    selected = []
    for index, link in enumerate(links):
        for policy_list in factor.get("jurisdiction_lists") or []:
            if link["country_code"] in {str(code).upper() for code in policy_list.get("country_codes") or []}:
                selected.append({"index": index, **link, "policy_list": policy_list.get("name"), "policy_source_url": policy_list.get("source_url")})
    return selected


def _classify_tax_jurisdiction(inputs: dict[str, Any], factor: dict[str, Any]) -> dict[str, Any]:
    if not os.getenv("OPENAI_API_KEY"):
        raise OtherRiskFactorsError("OPENAI_API_KEY is required for tax-risk jurisdiction classification")
    schema = {"type": "object", "additionalProperties": False, "properties": {"outcome": {"type": "string", "enum": ["triggered", "not_triggered", "inconclusive"]}, "rationale": {"type": "string"}, "matched_link_indexes": {"type": "array", "items": {"type": "integer", "minimum": 0}}}, "required": ["outcome", "rationale", "matched_link_indexes"]}
    prompt = "Assess only the supplied retained business-profile facts against the configured tax-risk jurisdiction definition. The policy_jurisdiction_links were deterministically matched to the configured tax-risk lists. Do not use external information about the customer, infer customers or suppliers, or invent jurisdictions. Return only indexes of the supplied policy_jurisdiction_links' underlying jurisdiction_links that support the conclusion. Return inconclusive where the retained facts cannot support a reliable conclusion.\n\n" + json.dumps({"risk_definition": factor.get("risk_definition"), "business_profile_inputs": inputs})
    try:
        result = traced_openai_client(OpenAI()).responses.create(model=DEFAULT_MODEL, input=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}], text={"format": {"type": "json_schema", "name": "tax_risk_jurisdiction", "schema": schema, "strict": True}})
        parsed = json.loads(result.output_text)
    except OpenAIError as exc:
        raise OtherRiskFactorsError(f"Tax-risk jurisdiction classification failed: {exc}") from exc
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise OtherRiskFactorsError("Tax-risk jurisdiction classification did not return valid structured output") from exc
    if not isinstance(parsed, dict) or parsed.get("outcome") not in {"triggered", "not_triggered", "inconclusive"}:
        raise OtherRiskFactorsError("Tax-risk jurisdiction classification returned an invalid outcome")
    links = inputs.get("jurisdiction_links") or []
    indexes = [index for index in parsed.get("matched_link_indexes") or [] if isinstance(index, int) and 0 <= index < len(links)]
    return {"outcome": parsed["outcome"], "rationale": str(parsed.get("rationale") or "No rationale was recorded."), "matched_link_indexes": indexes}


def _classify_aml_jurisdiction(inputs: dict[str, Any], factor: dict[str, Any]) -> dict[str, Any]:
    if not os.getenv("OPENAI_API_KEY"):
        raise OtherRiskFactorsError("OPENAI_API_KEY is required for AML-risk jurisdiction classification")
    schema = {"type": "object", "additionalProperties": False, "properties": {"outcome": {"type": "string", "enum": ["triggered", "not_triggered", "inconclusive"]}, "rationale": {"type": "string"}, "matched_link_indexes": {"type": "array", "items": {"type": "integer", "minimum": 0}}}, "required": ["outcome", "rationale", "matched_link_indexes"]}
    prompt = "Assess only the supplied retained CDD facts against the configured AML-risk jurisdiction definition. The policy_jurisdiction_links were deterministically matched to the configured FATF lists. Do not use external information about the customer, infer counterparties, or invent jurisdictions. Return only indexes of the supplied policy_jurisdiction_links' underlying jurisdiction_links that support the conclusion. Return inconclusive where the retained facts cannot support a reliable conclusion.\n\n" + json.dumps({"risk_definition": factor.get("risk_definition"), "cdd_inputs": inputs})
    try:
        result = traced_openai_client(OpenAI()).responses.create(model=DEFAULT_MODEL, input=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}], text={"format": {"type": "json_schema", "name": "aml_risk_jurisdiction", "schema": schema, "strict": True}})
        parsed = json.loads(result.output_text)
    except OpenAIError as exc:
        raise OtherRiskFactorsError(f"AML-risk jurisdiction classification failed: {exc}") from exc
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise OtherRiskFactorsError("AML-risk jurisdiction classification did not return valid structured output") from exc
    if not isinstance(parsed, dict) or parsed.get("outcome") not in {"triggered", "not_triggered", "inconclusive"}:
        raise OtherRiskFactorsError("AML-risk jurisdiction classification returned an invalid outcome")
    links = inputs.get("jurisdiction_links") or []
    indexes = [index for index in parsed.get("matched_link_indexes") or [] if isinstance(index, int) and 0 <= index < len(links)]
    return {"outcome": parsed["outcome"], "rationale": str(parsed.get("rationale") or "No rationale was recorded."), "matched_link_indexes": indexes}


def _complexity(state: dict[str, Any], factor: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    ownership = ((state.get("cdd") or {}).get("ownership_and_control") or {})
    org = ((ownership.get("org_chart") or {}).get("org_chart") or {})
    shareholders = org.get("shareholders") or []
    entities = [item for item in shareholders if str(item.get("member_type") or item.get("type") or "individual").casefold() not in {"individual", "person"}]
    countries = {str(item.get("jurisdiction") or item.get("nationality_id") or "") for item in [*shareholders, *entities] if item.get("jurisdiction") or item.get("nationality_id")}
    metrics = {"ownership_layers": 1 if shareholders else 0, "entity_count": len(entities), "cross_border_entities": max(0, len(countries) - 1), "circular_ownership": False, "unresolved_branches": list(ownership.get("missing_items") or [])}
    thresholds = factor.get("thresholds") or {}
    reasons = []
    if metrics["ownership_layers"] >= int(thresholds.get("ownership_layers", 99)): reasons.append("ownership layers")
    if metrics["entity_count"] >= int(thresholds.get("entity_count", 99)): reasons.append("intermediate entities")
    if metrics["cross_border_entities"] >= int(thresholds.get("cross_border_entities", 99)): reasons.append("cross-border entities")
    if metrics["circular_ownership"]: reasons.append("circular ownership")
    if metrics["unresolved_branches"]: return "inconclusive", "The ownership structure has unresolved branch(es), so complexity cannot be fully assessed.", metrics
    if reasons: return "triggered", f"The ownership graph meets configured complexity threshold(s) for {', '.join(reasons)}.", metrics
    return "not_triggered", "The retained ownership graph does not meet a configured complexity threshold.", metrics


def _trust_nominee(state: dict[str, Any], factor: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    ownership = ((state.get("cdd") or {}).get("ownership_and_control") or {})
    indicators = _ownership_evidence_indicators(state, factor)
    if indicators:
        matched = sorted({indicator["term"] for indicator in indicators})
        return "triggered", f"The retained ownership evidence contains trust or nominee indicator(s): {', '.join(matched)}.", {"matched_terms": matched, "matched_indicators": indicators}
    if ownership.get("status") != "complete":
        return "inconclusive", "The ownership record is incomplete, so it cannot rule out a trust or nominee arrangement.", {"matched_terms": [], "matched_indicators": []}
    return "not_triggered", "No trust or nominee indicator was identified in the configured ownership evidence.", {"matched_terms": [], "matched_indicators": []}


def _ownership_evidence_indicators(state: dict[str, Any], factor: dict[str, Any]) -> list[dict[str, str]]:
    tools = set(factor.get("evidence_tools") or [])
    terms = [str(term) for term in factor.get("terms") or []]
    fields = {str(field).casefold() for field in factor.get("indicator_field_names") or []}
    indicators: list[dict[str, str]] = []
    for evidence in state.get("evidence") or []:
        if evidence.get("tool") not in tools or not evidence.get("evidence_id"):
            continue
        for path, value in _indicator_fields(evidence.get("data"), "data", fields):
            lowered = value.casefold()
            for term in terms:
                if term.casefold() in lowered:
                    indicators.append({"term": term, "evidence_id": str(evidence["evidence_id"]), "field_path": path, "value": value})
    return indicators


def _indicator_fields(value: Any, path: str, allowed: set[str]) -> list[tuple[str, str]]:
    """Return only policy-configured ownership-label fields, never address or free-text fields."""
    if isinstance(value, dict):
        fields: list[tuple[str, str]] = []
        for key, nested in value.items():
            child_path = f"{path}.{key}"
            if isinstance(nested, (dict, list)):
                fields.extend(_indicator_fields(nested, child_path, allowed))
            elif str(key).casefold() in allowed and isinstance(nested, str) and nested.strip():
                fields.append((child_path, nested.strip()))
        return fields
    if isinstance(value, list):
        return [field for index, nested in enumerate(value) for field in _indicator_fields(nested, f"{path}[{index}]", allowed)]
    return []


def _jurisdiction_links(state: dict[str, Any]) -> list[dict[str, str]]:
    cdd = state.get("cdd") or {}; profile = ((cdd.get("company_business_profile") or {}).get("customer_static") or {}); customer = (state.get("metadata") or {}).get("customer") or {}
    links: list[dict[str, str]] = []
    def add(code: Any, source: str) -> None:
        if code: links.append({"country_code": str(code).upper(), "source": source})
    add(profile.get("jurisdiction"), "company jurisdiction"); add(customer.get("account_location"), "account location")
    members = ((cdd.get("ownership_and_control") or {}).get("members") or {})
    for group in ("controlling_members", "shareholders_and_beneficial_owners", "ultimate_beneficial_owners"):
        for member in members.get(group) or []:
            add(member.get("jurisdiction"), f"{group} jurisdiction"); add((member.get("address") or {}).get("country_code"), f"{group} address")
    digital = _latest_assessment(state, "digital_footprint").get("digital_business_profile") or {}
    for location in digital.get("geographic_presence") or []: add(location, "digital footprint operating presence")
    return list({(item["country_code"], item["source"]): item for item in links}.values())


def _select_context(state: dict[str, Any], section: str) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    evidence = [{"evidence_id": item.get("evidence_id"), "tool": item.get("tool"), "source": item.get("source"), "selection_reason": "Matches the factor's configured CDD section."} for item in state.get("evidence") or [] if item.get("evidence_id") and item.get("cdd_section") == section]
    assessments = [item.get("assessment_id") for item in state.get("assessments") or [] if item.get("assessment_id") and item.get("assessment_type") in {"digital_footprint", "adverse_news"}]
    findings = [item.get("finding_id") for item in state.get("findings") or [] if item.get("finding_id") and item.get("category") in {"digital_footprint", "adverse_news"}]
    return evidence, {"assessments": assessments, "findings": findings}


def _latest_assessment(state: dict[str, Any], assessment_type: str) -> dict[str, Any]:
    items = [item for item in state.get("assessments") or [] if item.get("assessment_type") == assessment_type]
    return items[-1] if items else {}


def _text(value: Any) -> str:
    if isinstance(value, dict): return " ".join(_text(item) for item in value.values())
    if isinstance(value, list): return " ".join(_text(item) for item in value)
    return str(value or "")
