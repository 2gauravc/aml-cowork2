#!/usr/bin/env python3
"""CDD missing-field detection and enrichment from extracted documents."""

from __future__ import annotations

from typing import Any

from src.utils.document_pipeline import ABOUT_FIELD_PATHS, REGISTRY_SOURCE_LABEL


REGISTRY_DOCUMENT_FIELD_LABELS = {
    "name": "Company Name",
    "jurisdiction": "Jurisdiction",
    "company_status": "Company Status",
    "registration_number": "Registration Number",
    "company_type": "Company Type",
    "activity_type": "Activity Type",
    "incorporation_date": "Incorporation Date",
    "registered_address": "Registered Office Address",
    "paid_up_capital": "Paid-up Capital",
}


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

    _apply_scalar(static, source, extract, "name", applied)
    _apply_scalar(static, source, extract, "jurisdiction", applied)
    _apply_scalar(static, source, extract, "company_status", applied)
    _apply_scalar(static, source, extract, "registration_number", applied)
    _apply_scalar(static, source, extract, "company_type", applied)
    _apply_scalar(static, source, extract, "activity_type", applied)
    _apply_scalar(static, source, extract, "incorporation_date", applied)

    address = extract.get("registered_address") or {}
    if _is_blank(static.get("registered_address", {}).get("full_address")) and not _is_blank(
        address.get("full_address")
    ):
        static.setdefault("registered_address", {})["full_address"] = address["full_address"]
        source["registered_address"] = _registry_source_info("registered_address", extract)
        applied.append("registered_address")

    if _is_blank(_get_path(static, ("display_capital", "value"))) and not _is_blank(
        extract.get("paid_up_capital")
    ):
        source_info = _registry_source_info("paid_up_capital", extract)
        static["paid_up_capital"] = extract["paid_up_capital"]
        static["display_capital"] = {
            "label": "Paid-up Capital",
            "value": extract["paid_up_capital"],
            "canonical_type": "paid_up_capital",
            "confidence": "synthetic_demo_document",
            "source_label": "Paid-up Capital",
            "source": source_info,
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
    applied: list[str],
) -> None:
    if _is_blank(static.get(field)) and not _is_blank(extract.get(field)):
        static[field] = extract[field]
        source[field] = _registry_source_info(field, extract)
        applied.append(field)


def _registry_source_info(field: str, extract: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": REGISTRY_SOURCE_LABEL,
        "field": REGISTRY_DOCUMENT_FIELD_LABELS.get(field, field),
        "document_path": extract.get("extraction", {}).get("document_path"),
    }


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
