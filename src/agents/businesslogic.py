"""Business logic for deriving CDD outputs from cleaned KYC data.

This module is intentionally separate from src/agents/nodes.py:

- src/agents/nodes.py orchestrates the LangGraph workflow, calls tools/API helpers,
  and updates graph state.
- src/agents/businesslogic.py contains deterministic business rules, such as
  how to derive UBOs, >10% shareholders, and related parties from org-chart JSON.

Keeping these separate makes the graph easier to read and lets the CDD business
rules be tested without running a LangGraph workflow or calling the KYC API.
"""

from __future__ import annotations

from typing import Any


COMPANY_SUFFIXES = (
    "limited",
    "ltd",
    "llc",
    "plc",
    "gmbh",
    "inc",
    "corp",
    "corporation",
    "company",
    "group",
)


def build_ownership_tables(org_chart_payload: dict[str, Any]) -> dict[str, Any]:
    """Build UBO, shareholder, and related-party rows from cleaned org-chart JSON."""
    root = org_chart_payload.get("org_chart") or {}
    shareholders = _dedupe_largest(
        [
            row
            for row in _shareholder_rows(root)
            if row.get("effective_shareholding_percent") is not None
            and row["effective_shareholding_percent"] > 10
        ]
    )
    ubos = [
        {
            "name": row["name"],
            "case_common_id": row.get("case_common_id"),
            "effective_shareholding_percent": row["effective_shareholding_percent"],
        }
        for row in shareholders
        if row.get("type") == "Individual"
        and row.get("effective_shareholding_percent") is not None
        and row["effective_shareholding_percent"] > 25
    ]
    related_parties = _related_parties(root, shareholders)
    return {
        "ubos": ubos,
        "shareholders_over_10_percent": shareholders,
        "related_parties": related_parties,
    }


def _shareholder_rows(
    node: dict[str, Any],
    *,
    parent_effective_percent: float = 100.0,
) -> list[dict[str, Any]]:
    rows = []
    for child in node.get("shareholders") or []:
        if not isinstance(child, dict):
            continue
        direct_percent = _direct_percentage(child)
        effective_percent = _effective_percentage(parent_effective_percent, direct_percent)
        rows.append(_shareholder_row(child, direct_percent, effective_percent))
        if effective_percent is not None:
            rows.extend(
                _shareholder_rows(
                    child,
                    parent_effective_percent=effective_percent,
                )
            )
    return rows


def _shareholder_row(
    node: dict[str, Any],
    direct_percent: float | None,
    effective_percent: float | None,
) -> dict[str, Any]:
    return {
        "name": node.get("name"),
        "type": _entity_type(node),
        "case_common_id": node.get("case_common_id"),
        "direct_shareholding_percent": _round_percentage(direct_percent),
        "effective_shareholding_percent": _round_percentage(effective_percent),
    }


def _direct_percentage(node: dict[str, Any]) -> float | None:
    ownership = node.get("ownership") or {}
    value = ownership.get("shares")
    if value is None:
        value = ownership.get("effective_percentage")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _effective_percentage(
    parent_effective_percent: float | None,
    direct_percent: float | None,
) -> float | None:
    if parent_effective_percent is None or direct_percent is None:
        return None
    return parent_effective_percent * direct_percent / 100


def _round_percentage(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 2)


def _dedupe_largest(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        name = row.get("name")
        if not name:
            continue
        key = (str(row.get("case_common_id") or ""), _normalize_name(name))
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = row
            continue

        current_pct = row.get("effective_shareholding_percent") or 0
        existing_pct = existing.get("effective_shareholding_percent") or 0
        if current_pct > existing_pct:
            by_key[key] = row
    return sorted(
        by_key.values(),
        key=lambda item: item.get("effective_shareholding_percent") or 0,
        reverse=True,
    )


def _related_parties(
    root: dict[str, Any],
    shareholders: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    company_shareholder_ids = {
        row.get("case_common_id")
        for row in shareholders
        if row.get("type") == "Company" and row.get("case_common_id") is not None
    }
    company_shareholder_names = {
        _normalize_name(row["name"])
        for row in shareholders
        if row.get("type") == "Company" and row.get("name")
    }

    rows = []
    rows.extend(
        _officer_rows(
            root,
            related_entity=root.get("name"),
            reason="Officer of top-level entity",
        )
    )

    for node in _walk_nodes(root):
        if not _is_company_shareholder(
            node,
            company_shareholder_ids=company_shareholder_ids,
            company_shareholder_names=company_shareholder_names,
        ):
            continue
        rows.extend(
            _officer_rows(
                node,
                related_entity=node.get("name"),
                reason="Officer of >10% corporate shareholder",
            )
        )

    seen = set()
    deduped = []
    for row in rows:
        key = (
            _normalize_name(row.get("name")),
            row.get("role"),
            _normalize_name(row.get("related_entity")),
        )
        if key in seen or not row.get("name"):
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _officer_rows(
    node: dict[str, Any],
    *,
    related_entity: str | None,
    reason: str,
) -> list[dict[str, Any]]:
    rows = []
    for officer in node.get("officers") or []:
        if not isinstance(officer, dict):
            continue
        rows.append(
            {
                "name": officer.get("name"),
                "role": officer.get("role"),
                "case_common_id": officer.get("case_common_id"),
                "related_entity": related_entity,
                "reason": reason,
            }
        )
    return rows


def _walk_nodes(node: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = [node]
    for field in ("officers", "shareholders", "others", "joint_shareholder_members"):
        for child in node.get(field) or []:
            if isinstance(child, dict):
                nodes.extend(_walk_nodes(child))
    return nodes


def _is_company_shareholder(
    node: dict[str, Any],
    *,
    company_shareholder_ids: set[Any],
    company_shareholder_names: set[str],
) -> bool:
    case_common_id = node.get("case_common_id")
    if case_common_id is not None and case_common_id in company_shareholder_ids:
        return True
    name = node.get("name")
    return bool(name and _normalize_name(name) in company_shareholder_names)


def _entity_type(node: dict[str, Any]) -> str:
    if node.get("jurisdiction_id") is not None:
        return "Company"
    if node.get("nationality_id") is not None:
        return "Individual"

    name = str(node.get("name") or "").casefold()
    if any(suffix in name for suffix in COMPANY_SUFFIXES):
        return "Company"
    return "Individual"


def _normalize_name(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())
