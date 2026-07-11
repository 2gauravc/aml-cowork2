"""Synthetic demo document generation for CDD enrichment."""

from __future__ import annotations

import re
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from xhtml2pdf import pisa


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = PROJECT_ROOT / "templates"
DOCUMENT_DIR = PROJECT_ROOT / "documents"
REGISTRY_TEMPLATE = "registry_business_profile.html"
REGISTRY_SOURCE_LABEL = "Registry Document (synthetic demo)"

ABOUT_FIELD_PATHS = {
    "name": ("name",),
    "jurisdiction": ("jurisdiction",),
    "company_status": ("company_status",),
    "registration_number": ("registration_number",),
    "company_type": ("company_type",),
    "paid_up_capital": ("display_capital", "value"),
    "activity_type": ("activity_type",),
    "incorporation_date": ("incorporation_date",),
    "registered_address": ("registered_address", "full_address"),
}


def enrich_cdd_from_registry_document(
    cdd: dict[str, Any],
    *,
    output_dir: Path | str = DOCUMENT_DIR,
) -> dict[str, Any]:
    """Generate, extract, and merge a synthetic registry document into CDD."""
    from copy import deepcopy

    from tools.cdd_enrichment import (
        apply_document_extract_to_cdd,
        missing_about_customer_fields,
    )
    from tools.document_extraction import classify_document, extract_document

    enriched = deepcopy(cdd)
    missing_fields = missing_about_customer_fields(enriched)
    artifact = generate_registry_document(enriched, output_dir=output_dir)
    classification = classify_document(artifact["pdf_path"])
    extract = extract_document(artifact, classification=classification)
    applied_fields = apply_document_extract_to_cdd(enriched, extract)
    enriched.setdefault("documents", []).append(
        {
            "classification": classification,
            "missing_fields_before": missing_fields,
            "applied_fields": applied_fields,
            "artifact": artifact,
        }
    )
    return enriched


def generate_registry_document(
    cdd: dict[str, Any],
    *,
    output_dir: Path | str = DOCUMENT_DIR,
) -> dict[str, Any]:
    """Create a synthetic registry business profile HTML/PDF and sidecar JSON."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    document = _registry_document_data(cdd)
    stem = _document_stem(document)
    html_path = output_dir / f"{stem}.html"
    pdf_path = output_dir / f"{stem}.pdf"
    json_path = output_dir / f"{stem}.json"

    html = _render_registry_html(document)
    html_path.write_text(html, encoding="utf-8")
    json_path.write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    with pdf_path.open("wb") as fh:
        status = pisa.CreatePDF(html, dest=fh)
    if status.err:
        raise RuntimeError(f"Failed to generate registry document at {pdf_path}")

    return {
        "document_type": "registry_document",
        "source": REGISTRY_SOURCE_LABEL,
        "html_path": str(html_path),
        "pdf_path": str(pdf_path),
        "json_path": str(json_path),
        "generated_at": datetime.now(UTC).isoformat(),
    }


def _registry_document_data(cdd: dict[str, Any]) -> dict[str, Any]:
    static = _customer_static(cdd)
    name = static.get("name") or "Demo Company Limited"
    jurisdiction = static.get("jurisdiction") or "GB"
    return {
        "document_type": "registry_document",
        "name": name,
        "jurisdiction": jurisdiction,
        "company_status": static.get("company_status") or "Active",
        "registration_number": static.get("registration_number")
        or _demo_registration_number(name, jurisdiction),
        "company_type": static.get("company_type") or "Private Company Limited by Shares",
        "paid_up_capital": _get_path(static, ("display_capital", "value"))
        or static.get("paid_up_capital")
        or _demo_paid_up_capital(name, jurisdiction),
        "activity_type": static.get("activity_type") or _demo_activity(name),
        "incorporation_date": static.get("incorporation_date")
        or static.get("registration_date")
        or _demo_date(name),
        "registered_address": {
            "full_address": _get_path(static, ("registered_address", "full_address"))
            or _demo_address(name, jurisdiction)
        },
    }


def _render_registry_html(document: dict[str, Any]) -> str:
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(("html", "xml")),
    )
    template = env.get_template(REGISTRY_TEMPLATE)
    return template.render(document=document)


def _customer_static(cdd: dict[str, Any]) -> dict[str, Any]:
    return (
        cdd.setdefault("company_business_profile", {})
        .setdefault("customer_static", {})
    )


def _document_stem(document: dict[str, Any]) -> str:
    safe_name = re.sub(r"[^A-Za-z0-9]+", "-", str(document.get("name") or "Company"))
    safe_name = safe_name.strip("-") or "Company"
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return f"registry-business-profile-{safe_name}-{timestamp}"


def _get_path(data: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = data
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _is_blank(value: Any) -> bool:
    return value in (None, "", [], {})


def _stable_number(seed: str, *, minimum: int, maximum: int) -> int:
    value = sum((index + 1) * ord(char) for index, char in enumerate(seed))
    return minimum + (value % (maximum - minimum + 1))


def _demo_paid_up_capital(name: str, jurisdiction: str) -> str:
    amount = _stable_number(f"{name}:{jurisdiction}:capital", minimum=50_000, maximum=950_000)
    currency = {
        "GB": "GBP",
        "HK": "HKD",
        "SG": "SGD",
        "CH": "CHF",
        "US": "USD",
    }.get(str(jurisdiction).upper(), "USD")
    return f"{currency} {amount:,}"


def _demo_registration_number(name: str, jurisdiction: str) -> str:
    number = _stable_number(f"{name}:{jurisdiction}:registration", minimum=1000000, maximum=9999999)
    return f"{jurisdiction}-{number}"


def _demo_activity(name: str) -> str:
    if "ENGINEERING" in name.upper():
        return "Engineering services and related technical consulting"
    if "CREAMERY" in name.upper():
        return "Dairy production and wholesale distribution"
    return "Investment holding and business support services"


def _demo_address(name: str, jurisdiction: str) -> str:
    number = _stable_number(f"{name}:{jurisdiction}:address", minimum=10, maximum=240)
    return f"{number} Registry Street, {jurisdiction}"


def _demo_date(name: str) -> str:
    year = _stable_number(f"{name}:year", minimum=1995, maximum=2020)
    month = _stable_number(f"{name}:month", minimum=1, maximum=12)
    day = _stable_number(f"{name}:day", minimum=1, maximum=28)
    return f"{day:02d}/{month:02d}/{year}"
