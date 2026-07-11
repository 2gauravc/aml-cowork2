#!/usr/bin/env python3
"""CDD missing-field detection and enrichment from extracted documents."""

from __future__ import annotations

from typing import Any

from utils.document_pipeline import ABOUT_FIELD_PATHS, REGISTRY_SOURCE_LABEL


def missing_about_customer_fields(cdd: dict[str, Any]) -> list[str]:
    """Return About the Customer field keys that are blank in the CDD object."""
    static = _customer_static(cdd)
    missing = []
    for field, path in ABOUT_FIELD_PATHS.items():
        if _get_path(static, path) in (None, "", [], {}):
            missing.append(field)
    return missing


def apply_document_extract_to_cdd(
    cdd: dict[str, Any],
    extract: dict[str, Any],
) -> list[str]:
    """Populate missing About fields from a registry document extract."""
    if extract.get("document_type") != "registry_document":
        return []

    static = _customer_static(cdd)
    source = static.setdefault("source", {})
    applied = []
    source_info = {
        "source": REGISTRY_SOURCE_LABEL,
        "field": "Registry Business Profile",
        "document_path": extract.get("extraction", {}).get("document_path"),
    }

    _apply_scalar(static, source, extract, "name", source_info, applied)
    _apply_scalar(static, source, extract, "jurisdiction", source_info, applied)
    _apply_scalar(static, source, extract, "company_status", source_info, applied)
    _apply_scalar(static, source, extract, "registration_number", source_info, applied)
    _apply_scalar(static, source, extract, "company_type", source_info, applied)
    _apply_scalar(static, source, extract, "activity_type", source_info, applied)
    _apply_scalar(static, source, extract, "incorporation_date", source_info, applied)

    address = extract.get("registered_address") or {}
    if _is_blank(static.get("registered_address", {}).get("full_address")) and not _is_blank(
        address.get("full_address")
    ):
        static.setdefault("registered_address", {})["full_address"] = address["full_address"]
        source["registered_address"] = dict(source_info)
        applied.append("registered_address")

    if _is_blank(_get_path(static, ("display_capital", "value"))) and not _is_blank(
        extract.get("paid_up_capital")
    ):
        static["paid_up_capital"] = extract["paid_up_capital"]
        static["display_capital"] = {
            "label": "Paid-up Capital",
            "value": extract["paid_up_capital"],
            "canonical_type": "paid_up_capital",
            "confidence": "synthetic_demo_document",
            "source_label": "Paid-up Capital",
            "source": dict(source_info),
        }
        source["paid_up_capital"] = dict(source_info)
        applied.append("paid_up_capital")

    if applied:
        profile = cdd.setdefault("company_business_profile", {})
        profile["status"] = "complete"
        profile["missing_items"] = [
            item for item in profile.get("missing_items", []) if item not in applied
        ]
        static["missing_items"] = [
            item for item in static.get("missing_items", []) if item not in applied
        ]
    return applied


def _apply_scalar(
    static: dict[str, Any],
    source: dict[str, Any],
    extract: dict[str, Any],
    field: str,
    source_info: dict[str, Any],
    applied: list[str],
) -> None:
    if _is_blank(static.get(field)) and not _is_blank(extract.get(field)):
        static[field] = extract[field]
        source[field] = dict(source_info)
        applied.append(field)


def _customer_static(cdd: dict[str, Any]) -> dict[str, Any]:
    return (
        cdd.setdefault("company_business_profile", {})
        .setdefault("customer_static", {})
    )


def _get_path(data: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = data
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _is_blank(value: Any) -> bool:
    return value in (None, "", [], {})
