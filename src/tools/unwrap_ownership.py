"""Deterministic, evidence-first ownership unwrapping."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.utils.skill_definitions import SkillDefinitionError, load_skill_definition
from src.utils.tool_presentation import ToolPresentationError, compile_tool_presentation


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SKILL_PATH = PROJECT_ROOT / "skills" / "unwrap-ownership" / "SKILL.md"
OWNERSHIP_EVIDENCE_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["schema_version", "source_evidence_id", "entities", "ownership_relationships", "source_citations", "extraction_limitations"],
    "properties": {
        "schema_version": {"const": "ownership_source_evidence/v1"},
        "source_evidence_id": {"type": "string", "minLength": 1},
        "entities": {"type": "array"}, "ownership_relationships": {"type": "array"},
        "source_citations": {"type": "array"}, "extraction_limitations": {"type": "array"},
    },
}


class OwnershipUnwrapError(RuntimeError):
    pass


def load_ownership_definition(path: str | Path = SKILL_PATH) -> dict[str, Any]:
    try:
        instructions = Path(path).read_text(encoding="utf-8").strip()
        contract, contract_path, contract_version = load_skill_definition(path, "contract.yaml")
        presentation, presentation_path, presentation_version = load_skill_definition(path, "presentation.yaml")
        presentation = compile_tool_presentation(presentation)
    except (OSError, SkillDefinitionError, ToolPresentationError) as exc:
        raise OwnershipUnwrapError(f"Ownership skill could not be loaded: {exc}") from exc
    if contract.get("name") != "unwrap-ownership":
        raise OwnershipUnwrapError("Ownership contract must be named unwrap-ownership")
    assessment = contract.get("assessment") or {}
    if assessment.get("schema") != "ownership_unwrap_assessment/v1":
        raise OwnershipUnwrapError("Ownership contract must declare ownership_unwrap_assessment/v1")
    return {"instructions": instructions, "contract": contract, "contract_path": contract_path,
            "contract_version": contract_version, "presentation": presentation,
            "presentation_path": presentation_path, "presentation_version": presentation_version}


def unwrap_ownership(state: dict[str, Any]) -> dict[str, Any]:
    """Produce canonical ownership evidence, assessment, and conditional finding."""
    definition = load_ownership_definition()
    run_id = f"run:unwrap-ownership:{uuid4().hex}"
    now = datetime.now(UTC).isoformat()
    assessment_id = f"assessment:unwrap-ownership:{uuid4().hex}"
    sources = _ownership_sources(state)
    entity_types = _source_entity_types(sources)
    normalized, source_ids = _normalize_sources(sources, now, entity_types)
    retained_evidence, retained_ubo_claims = _retained_ubo_evidence(state, now)
    retained_ubo_claims = _unique_claims([
        *retained_ubo_claims,
        *_member_ubo_claims(sources),
    ])
    if retained_evidence:
        normalized.append(retained_evidence)
        source_ids.append(retained_evidence["evidence_id"])
    listed = _listed_company_substitute(state, source_ids)
    if listed:
        assessment = _assessment(assessment_id, run_id, now, definition, source_ids, "listed_company_exception", [], [listed], [], [])
        return {"evidence": normalized, "assessments": [assessment], "findings": []}
    rows, gaps = _ownership_rows(sources, entity_types)
    if not rows:
        outcome = "unavailable" if not source_ids else "incomplete"
        limitation = "No supported ownership relationships were retained." if source_ids else "No ownership evidence is available."
        gaps = [{"entity": "Ownership chain", "reason": limitation}, *_ubo_claim_gaps(retained_ubo_claims, [])]
        assessment = _assessment(assessment_id, run_id, now, definition, source_ids, outcome, [], [], gaps, gaps)
        assessment["retained_ubo_claims"] = retained_ubo_claims
        finding = _review_finding(assessment, now, [limitation]) if source_ids else None
        return {"evidence": normalized, "assessments": [assessment], "findings": [finding] if finding else []}
    ubos = [row for row in rows if row.get("type") == "Individual" and _pct(row) > 25]
    corporates = [row for row in rows if row.get("type") == "Company" and _pct(row) > 10]
    gaps.extend(_ubo_claim_gaps(retained_ubo_claims, ubos))
    outcome = "complete"
    if gaps:
        outcome = "conflicting_sources" if any(item.get("kind") in {"duplicate", "reconciliation"} for item in gaps) else "incomplete"
    assessment = _assessment(assessment_id, run_id, now, definition, source_ids, outcome, rows, ubos, corporates, gaps)
    assessment["retained_ubo_claims"] = retained_ubo_claims
    finding = _review_finding(assessment, now, assessment["limitations"]) if gaps and source_ids else None
    return {"evidence": normalized, "assessments": [assessment], "findings": [finding] if finding else []}


def _ownership_sources(state: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in state.get("evidence") or [] if isinstance(item, dict) and item.get("tool") in {"get_company_org_chart_by_case_id", "unwrap_ownership_document", "get_company_members_by_case_id"}]


def _normalize_sources(
    sources: list[dict[str, Any]], now: str, entity_types: dict[tuple[str, str], str]
) -> tuple[list[dict[str, Any]], list[str]]:
    records, ids = [], []
    for source in sources:
        source_id = str(source.get("evidence_id") or "")
        if not source_id:
            continue
        ids.append(source_id)
        data = source.get("data") if isinstance(source.get("data"), dict) else {}
        entities = data.get("entities") or []
        relationships = data.get("ownership_relationships") or []
        if source.get("tool") == "get_company_org_chart_by_case_id":
            entities, relationships = _normalize_org_chart(data.get("org_chart") or {}, entity_types)
        normalized = {"schema_version": "ownership_source_evidence/v1", "source_evidence_id": source_id, "entities": entities, "ownership_relationships": relationships, "source_citations": data.get("source_citations") or [{"evidence_id": source_id}], "extraction_limitations": data.get("extraction_limitations") or []}
        _validate_evidence(normalized)
        records.append({"evidence_id": f"evidence:ownership-normalized:{source_id.split(':')[-1]}", "source": source.get("source") or "CDD evidence", "tool": "unwrap_ownership", "description": "Normalized ownership source evidence", "collected_at": now, "relevance_tags": ["ownership", "normalized"], "data": normalized})
    return records, ids


def _retained_ubo_evidence(state: dict[str, Any], now: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Keep previously retained UBO facts visible to a newer resolver run."""
    ownership = ((state.get("cdd") or {}).get("ownership_and_control") or {})
    claims = [dict(item) for item in ownership.get("ubos") or [] if isinstance(item, dict) and item.get("name")]
    if not claims:
        return None, []
    evidence_id = f"evidence:ownership-retained-cdd:{uuid4().hex}"
    return ({"evidence_id": evidence_id, "source": "Retained CDD state", "tool": "unwrap_ownership", "description": "Historical UBO claims retained for ownership reconciliation", "collected_at": now, "relevance_tags": ["ownership", "ubo", "retained_claim"], "data": {"schema_version": "ownership_source_evidence/v1", "source_evidence_id": evidence_id, "entities": claims, "ownership_relationships": [], "source_citations": [{"state_path": "cdd.ownership_and_control.ubos"}], "extraction_limitations": ["Historical UBO claims may not retain their original source relationship."]}}, claims)


def _member_ubo_claims(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    for source in sources:
        if source.get("tool") != "get_company_members_by_case_id":
            continue
        data = source.get("data") if isinstance(source.get("data"), dict) else {}
        for member in data.get("ultimate_beneficial_owners") or []:
            if not isinstance(member, dict) or not member.get("name"):
                continue
            ownership = member.get("ownership") if isinstance(member.get("ownership"), dict) else {}
            claims.append({"name": member.get("name"), "case_common_id": member.get("case_common_id"), "effective_shareholding_percent": ownership.get("percentage") or ownership.get("shares"), "claim_source": "kyc_members"})
    return claims


def _unique_claims(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for claim in claims:
        if claim.get("name"):
            unique.setdefault(_identity_key(claim), claim)
    return list(unique.values())


def _ubo_claim_gaps(retained_claims: list[dict[str, Any]], resolved_ubos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not retained_claims:
        return []
    retained = {_identity_key(item) for item in retained_claims}
    resolved = {_identity_key(item) for item in resolved_ubos}
    if retained == resolved:
        return []
    return [{"kind": "retained_ubo_conflict", "entity": "Retained CDD UBO claims", "reason": "Retained CDD UBO claims do not match the UBOs resolved from current ownership evidence.", "retained_ubo_count": len(retained), "resolved_ubo_count": len(resolved)}]


def _ownership_rows(
    sources: list[dict[str, Any]], entity_types: dict[tuple[str, str], str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    for source in sources:
        data = source.get("data") if isinstance(source.get("data"), dict) else {}
        if source.get("tool") == "get_company_org_chart_by_case_id":
            source_rows, source_gaps = _rows_from_org_chart(data.get("org_chart") or {}, entity_types)
            rows.extend(source_rows)
            gaps.extend(source_gaps)
        document_rows, document_gaps = _rows_from_document(data.get("ownership_relationships") or [])
        rows.extend(document_rows)
        gaps.extend(document_gaps)
    return rows, gaps


def _rows_from_org_chart(
    root: dict[str, Any], entity_types: dict[tuple[str, str], str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []

    def visit(node: dict[str, Any], parent_effective: float, layer: str) -> None:
        children = [child for child in node.get("shareholders") or [] if isinstance(child, dict)]
        if not children:
            return
        percentages = [_direct_pct(child) for child in children]
        known = [value for value in percentages if value is not None]
        if len(known) != len(children):
            gaps.append({"kind": "missing_percentage", "entity": layer, "reason": f"Ownership percentages are missing for {len(children) - len(known)} shareholder entries."})
        total = sum(known)
        if abs(total - 100) > 0.01:
            gaps.append({"kind": "reconciliation", "entity": layer, "reason": f"Direct ownership reconciles to {total:.4f}% rather than 100.0000%.", "total_percent": round(total, 4)})
        seen: dict[tuple[str, str], int] = {}
        for child, direct in zip(children, percentages):
            name = str(child.get("name") or "Unnamed shareholder")
            key = (str(child.get("case_common_id") or ""), name.casefold())
            seen[key] = seen.get(key, 0) + 1
            effective = parent_effective * direct / 100 if direct is not None else None
            row = {"name": child.get("name"), "type": _entity_type(child, entity_types), "case_common_id": child.get("case_common_id"), "direct_shareholding_percent": direct, "effective_shareholding_percent": _round(effective), "ownership_layer": layer}
            rows.append(row)
            child_layer = f"{layer} → {name}"
            if row["type"] == "Company" and _pct(row) > 10 and not (child.get("shareholders") or []):
                gaps.append({"kind": "unresolved_corporate_branch", "entity": name, "reason": f"Material corporate shareholder {name} ({_pct(row):.4f}%) has not been unwrapped."})
            visit(child, effective or 0, child_layer)
        for (_, name), count in seen.items():
            if count > 1:
                gaps.append({"kind": "duplicate", "entity": layer, "reason": f"{name} appears {count} times in the same ownership layer and was not consolidated."})

    visit(root, 100.0, str(root.get("name") or "Customer"))
    return rows, gaps


def _source_entity_types(sources: list[dict[str, Any]]) -> dict[tuple[str, str], str]:
    """Build a stable-ID type index from complementary KYC source sections."""
    types: dict[tuple[str, str], str] = {}
    for source in sources:
        data = source.get("data") if isinstance(source.get("data"), dict) else {}
        candidates: list[Any] = []
        if source.get("tool") == "get_company_members_by_case_id":
            for field in ("controlling_members", "shareholders_and_beneficial_owners", "ultimate_beneficial_owners"):
                candidates.extend(data.get(field) or [])
        if source.get("tool") == "get_company_org_chart_by_case_id":
            root = data.get("org_chart") if isinstance(data.get("org_chart"), dict) else {}
            candidates.extend(root.get("others") or [])
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            entity_type = _entity_type(candidate)
            if entity_type != "Unknown":
                types[_identity_key(candidate)] = entity_type
    return types


def _normalize_org_chart(
    root: dict[str, Any], entity_types: dict[tuple[str, str], str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Convert the provider's nested ownership tree into canonical source evidence."""
    entities: list[dict[str, Any]] = []
    relationships: list[dict[str, Any]] = []

    def visit(node: dict[str, Any], owner: str | None = None) -> None:
        name = node.get("name")
        if name:
            entities.append({"name": name, "case_common_id": node.get("case_common_id"), "type": _entity_type(node, entity_types)})
        for child in node.get("shareholders") or []:
            if not isinstance(child, dict):
                continue
            direct = _direct_pct(child)
            relationships.append({"owner_name": child.get("name"), "owner_id": child.get("case_common_id"), "owner_type": _entity_type(child, entity_types), "owned_entity": name or owner, "direct_shareholding_percent": direct, "effective_shareholding_percent": direct})
            visit(child, name)

    visit(root)
    return entities, relationships


def _rows_from_document(relations: list[Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows, gaps = [], []
    by_layer: dict[str, list[dict[str, Any]]] = {}
    for relation in relations:
        if not isinstance(relation, dict):
            continue
        layer = str(relation.get("owned_entity") or relation.get("ownership_layer") or "Document ownership layer")
        row = {"name": relation.get("owner_name") or relation.get("name"), "type": relation.get("owner_type") or relation.get("type"), "case_common_id": relation.get("owner_id"), "direct_shareholding_percent": relation.get("direct_shareholding_percent"), "effective_shareholding_percent": relation.get("effective_shareholding_percent"), "ownership_layer": layer}
        rows.append(row)
        by_layer.setdefault(layer, []).append(row)
    for layer, layer_rows in by_layer.items():
        direct = [_direct_row_pct(row) for row in layer_rows]
        if all(value is not None for value in direct):
            total = sum(value for value in direct if value is not None)
            if abs(total - 100) > 0.01:
                gaps.append({"kind": "reconciliation", "entity": layer, "reason": f"Direct ownership reconciles to {total:.4f}% rather than 100.0000%.", "total_percent": round(total, 4)})
        seen: dict[tuple[str, str], int] = {}
        for row in layer_rows:
            key = (str(row.get("case_common_id") or ""), str(row.get("name") or "").casefold())
            seen[key] = seen.get(key, 0) + 1
            if row.get("type") == "Company" and _pct(row) > 10:
                gaps.append({"kind": "unresolved_corporate_branch", "entity": row.get("name") or "Corporate shareholder", "reason": f"Material corporate shareholder {row.get('name') or 'Unknown'} ({_pct(row):.4f}%) has not been unwrapped."})
        for (_, name), count in seen.items():
            if name and count > 1:
                gaps.append({"kind": "duplicate", "entity": layer, "reason": f"{name} appears {count} times in the same ownership layer and was not consolidated."})
    return rows, gaps


def _listed_company_substitute(state: dict[str, Any], source_ids: list[str]) -> dict[str, Any] | None:
    profile = (((state.get("cdd") or {}).get("company_business_profile") or {}).get("customer_static") or {})
    if not profile.get("is_listed"):
        return None
    executive = profile.get("authorised_executive") or {}
    if not executive.get("name") or not source_ids:
        return None
    return {"name": executive["name"], "case_common_id": executive.get("case_common_id"), "basis": "listed_company_authorised_executive", "effective_shareholding_percent": None}


def _assessment(assessment_id: str, run_id: str, now: str, definition: dict[str, Any], source_ids: list[str], outcome: str, paths: list[dict[str, Any]], ubos: list[dict[str, Any]], corporates: list[dict[str, Any]], limitations: list[Any]) -> dict[str, Any]:
    unresolved = limitations if limitations and isinstance(limitations[0], dict) else []
    text_limitations = [item if isinstance(item, str) else str(item.get("reason") or "Unresolved ownership branch") for item in limitations]
    return {"assessment_id": assessment_id, "assessment_type": "ownership_unwrap", "schema_version": "ownership_unwrap_assessment/v1", "tool": "unwrap_ownership", "run_id": run_id, "created_at": now, "outcome": outcome, "ownership_paths": paths, "ubo_list": ubos, "corporate_shareholders_over_10_percent": corporates, "unresolved_branches": unresolved, "limitations": text_limitations, "source_evidence_ids": source_ids, "definition": {"contract_path": definition["contract_path"], "contract_version": definition["contract_version"], "presentation_path": definition["presentation_path"], "presentation_version": definition["presentation_version"]}}


def _review_finding(assessment: dict[str, Any], now: str, limitations: list[str]) -> dict[str, Any]:
    return {"finding_id": f"finding:ownership-review:{uuid4().hex}", "schema_version": "finding/v1", "category": "ownership_review", "assessment_id": assessment["assessment_id"], "title": "Ownership evidence requires review", "summary": limitations[0], "subject": {"entity_type": "company"}, "confidence": {"level": "low", "rationale": "Ownership chain could not be resolved from retained evidence.", "limitations": limitations}, "severity": {"level": "medium", "rationale": "Reviewer action is required before ownership can be confirmed."}, "potential_impact_risk": "An unresolved ownership chain may prevent complete customer due diligence.", "recommended_action_rfi": {"internal_actions": ["Review the ownership evidence and retrieve the unresolved branch."], "rfi": []}, "source": {"producer_type": "tool", "producer_name": "unwrap_ownership", "created_at": now}, "relevant_evidence_ids": assessment["source_evidence_ids"], "ownership_review": {"reason": limitations[0], "unresolved_branches": assessment["unresolved_branches"]}}


def _pct(row: dict[str, Any]) -> float:
    try:
        return float(row.get("effective_shareholding_percent"))
    except (TypeError, ValueError):
        return 0.0


def _direct_pct(node: dict[str, Any]) -> float | None:
    ownership = node.get("ownership") if isinstance(node.get("ownership"), dict) else {}
    value = ownership.get("shares")
    if value is None:
        value = ownership.get("effective_percentage")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _direct_row_pct(row: dict[str, Any]) -> float | None:
    try:
        value = row.get("direct_shareholding_percent")
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


def _entity_type(
    node: dict[str, Any], entity_types: dict[tuple[str, str], str] | None = None
) -> str:
    value = str(node.get("type") or node.get("member_type") or "").casefold()
    if value in {"company", "corporate"}:
        return "Company"
    if value in {"individual", "person"}:
        return "Individual"
    if entity_types:
        return entity_types.get(_identity_key(node), "Unknown")
    return "Unknown"


def _round(value: float | None) -> float | None:
    return round(value, 4) if value is not None else None


def _identity_key(row: dict[str, Any]) -> tuple[str, str]:
    case_common_id = row.get("case_common_id")
    if case_common_id not in (None, ""):
        return ("case_common_id", str(case_common_id))
    return ("name", str(row.get("name") or "").casefold())


def _validate_evidence(value: dict[str, Any]) -> None:
    try:
        from jsonschema import Draft202012Validator
    except ImportError as exc:
        raise OwnershipUnwrapError("jsonschema is required to validate ownership evidence") from exc
    errors = list(Draft202012Validator(OWNERSHIP_EVIDENCE_SCHEMA).iter_errors(value))
    if errors:
        raise OwnershipUnwrapError(f"Invalid ownership evidence: {errors[0].message}")


def _dedupe(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        if not row.get("name"):
            continue
        key = (str(row.get("case_common_id") or ""), str(row["name"]).casefold())
        if key not in best or _pct(row) > _pct(best[key]):
            best[key] = row
    return sorted(best.values(), key=_pct, reverse=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the production ownership-unwrapping node against a state JSON file.")
    parser.add_argument("--state-json", required=True)
    parser.add_argument("--raw", action="store_true", help="Include the supplied input state in the output.")
    args = parser.parse_args(argv)
    state = json.loads(Path(args.state_json).read_text(encoding="utf-8"))
    # Import lazily to avoid the production node's import of this module during
    # normal application startup. The CLI intentionally exercises that same
    # node users receive from the API and chat surfaces.
    from src.agents.nodes import unwrap_ownership as production_node

    result = production_node(state)
    if args.raw:
        result["input"] = state
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
