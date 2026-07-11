#!/usr/bin/env python3
"""Apply structured ID&V policy requirements to CDD ownership data."""

from __future__ import annotations

from typing import Any


def establish_idv_requirements(
    cdd: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    """Return one ID&V requirement row per unique required individual."""
    ownership = cdd.get("ownership_and_control", {})
    required_for = {str(item).casefold() for item in policy.get("required_for", [])}
    accepted_documents = policy.get("accepted_documents") or ["passport", "national_id"]

    people: dict[tuple[str, str], dict[str, Any]] = {}
    if "ubo" in required_for:
        for row in ownership.get("ubos", []) or []:
            _merge_person(
                people,
                row,
                role="UBO",
                accepted_documents=accepted_documents,
                reason="Ultimate Beneficial Owner",
            )

    if "director" in required_for:
        for row in ownership.get("related_parties", []) or []:
            if _is_director(row):
                _merge_person(
                    people,
                    row,
                    role="Director",
                    accepted_documents=accepted_documents,
                    reason=row.get("reason") or "Director",
                )

    rows = sorted(people.values(), key=lambda item: item.get("name") or "")
    return {
        "status": "incomplete" if rows else "complete",
        "policy": policy,
        "required_individuals": rows,
        "missing_items": [row["name"] for row in rows if row.get("status") != "verified"],
        "notes": [],
    }


def _merge_person(
    people: dict[tuple[str, str], dict[str, Any]],
    row: dict[str, Any],
    *,
    role: str,
    accepted_documents: list[str],
    reason: str,
) -> None:
    name = row.get("name")
    if not name:
        return
    key = _existing_person_key(people, row) or _person_key(row)
    person = people.setdefault(
        key,
        {
            "name": name,
            "case_common_id": row.get("case_common_id"),
            "roles": [],
            "reasons": [],
            "required_documents": list(accepted_documents),
            "selected_document_type": accepted_documents[0] if accepted_documents else "passport",
            "status": "required",
        },
    )
    if not person.get("case_common_id") and row.get("case_common_id"):
        person["case_common_id"] = row.get("case_common_id")
    if role not in person["roles"]:
        person["roles"].append(role)
    if reason and reason not in person["reasons"]:
        person["reasons"].append(reason)


def _is_director(row: dict[str, Any]) -> bool:
    role = str(row.get("role") or "").casefold()
    return "director" in role


def _person_key(row: dict[str, Any]) -> tuple[str, str]:
    case_common_id = row.get("case_common_id")
    if case_common_id not in (None, ""):
        return ("id", str(case_common_id))
    return ("name", _normalize_name(row.get("name")))


def _existing_person_key(
    people: dict[tuple[str, str], dict[str, Any]],
    row: dict[str, Any],
) -> tuple[str, str] | None:
    case_common_id = row.get("case_common_id")
    normalized_name = _normalize_name(row.get("name"))
    if case_common_id not in (None, ""):
        id_key = ("id", str(case_common_id))
        if id_key in people:
            return id_key

    for key, person in people.items():
        if case_common_id not in (None, "") and str(person.get("case_common_id")) == str(case_common_id):
            return key
        if normalized_name and _normalize_name(person.get("name")) == normalized_name:
            return key
    return None


def _normalize_name(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())
