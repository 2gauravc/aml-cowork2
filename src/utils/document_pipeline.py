"""Synthetic demo document generation for CDD enrichment."""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from openai import OpenAI, OpenAIError

from xhtml2pdf import pisa


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = PROJECT_ROOT / "config" / "templates"
DOCUMENT_DIR = PROJECT_ROOT / "generated_documents"
REGISTRY_TEMPLATE = "registry_business_profile.html"
REGISTRY_SOURCE_LABEL = "Registry Document (synthetic demo)"
ACTIVITY_INFERENCE_MODEL = os.getenv("OPENAI_SYNTHETIC_ACTIVITY_MODEL") or os.getenv(
    "OPENAI_MODEL", "gpt-5.6"
)

ACTIVITY_INFERENCE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "activity_type": {"type": "string"},
        "rationale": {"type": "string"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
    },
    "required": ["activity_type", "rationale", "confidence"],
}


class SyntheticActivityInferenceError(RuntimeError):
    """Raised when the required synthetic business-activity inference fails."""

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

    from src.tools.cdd_enrichment import (
        apply_document_extract_to_cdd,
        missing_about_customer_fields,
    )
    from src.tools.document_extraction import classify_document, extract_document

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
        "source_type": "generated_demo",
        "provenance": "synthetic_demo",
        "synthetic": True,
        "html_path": str(html_path),
        "pdf_path": str(pdf_path),
        "json_path": str(json_path),
        "generated_at": datetime.now(UTC).isoformat(),
        "activity_inference": document.get("activity_inference"),
    }


def _registry_document_data(cdd: dict[str, Any]) -> dict[str, Any]:
    static = _customer_static(cdd)
    name = static.get("name") or "Demo Company Limited"
    jurisdiction = static.get("jurisdiction") or "GB"
    upstream_activity = static.get("activity_type")
    activity_inference = None
    if not upstream_activity:
        activity_inference = infer_synthetic_activity(
            {
                "name": name,
                "jurisdiction": jurisdiction,
                "company_type": static.get("company_type"),
                "company_status": static.get("company_status"),
                "registered_address": _get_path(static, ("registered_address", "full_address")),
            }
        )
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
        "activity_type": upstream_activity or activity_inference["activity_type"],
        "activity_inference": activity_inference,
        "incorporation_date": static.get("incorporation_date")
        or static.get("registration_date")
        or _demo_date(name),
        "registered_address": {
            "full_address": _get_path(static, ("registered_address", "full_address"))
            or _demo_address(name, jurisdiction)
        },
        "shareholders": [{
            "name": f"{name} Beneficial Owner",
            "entity_type": "individual",
            "ownership_percent": 100,
            "role": "Shareholder",
        }],
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


def infer_synthetic_activity(customer_context: dict[str, Any]) -> dict[str, str]:
    """Infer an auditable synthetic activity when no upstream value is available."""
    if not os.getenv("OPENAI_API_KEY"):
        raise SyntheticActivityInferenceError(
            "OPENAI_API_KEY is required to infer a synthetic registry activity"
        )

    prompt = (
        "Create a synthetic demo business activity from the supplied company context. "
        "Use only that context; do not search for or claim facts about the company. "
        "Always return one concise, plausible activity. If the name is ambiguous, "
        "choose the most plausible broad but specific commercial activity rather than "
        "an unknown value or a generic investment-holding catch-all. The result is an "
        "inference, not authoritative registry information. Explain the basis briefly "
        "and calibrate confidence to the available context.\n\n"
        + json.dumps(customer_context, ensure_ascii=False)
    )
    try:
        response = OpenAI().responses.create(
            model=ACTIVITY_INFERENCE_MODEL,
            input=[
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": prompt}],
                }
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "synthetic_registry_activity",
                    "schema": ACTIVITY_INFERENCE_SCHEMA,
                    "strict": True,
                }
            },
        )
        result = json.loads(response.output_text)
    except OpenAIError as exc:
        raise SyntheticActivityInferenceError(
            f"Synthetic registry activity inference failed: {exc}"
        ) from exc
    except (AttributeError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise SyntheticActivityInferenceError(
            "Synthetic registry activity inference did not return valid structured output"
        ) from exc

    if not isinstance(result, dict):
        raise SyntheticActivityInferenceError(
            "Synthetic registry activity inference did not return an object"
        )
    activity = str(result.get("activity_type") or "").strip()
    rationale = str(result.get("rationale") or "").strip()
    confidence = str(result.get("confidence") or "").strip().casefold()
    if not activity or not rationale or confidence not in {"high", "medium", "low"}:
        raise SyntheticActivityInferenceError(
            "Synthetic registry activity inference returned incomplete output"
        )
    return {
        "activity_type": activity,
        "rationale": rationale,
        "confidence": confidence,
        "source": "synthetic_llm_inference",
        "model": ACTIVITY_INFERENCE_MODEL,
    }


def _demo_address(name: str, jurisdiction: str) -> str:
    number = _stable_number(f"{name}:{jurisdiction}:address", minimum=10, maximum=240)
    return f"{number} Registry Street, {jurisdiction}"


def _demo_date(name: str) -> str:
    year = _stable_number(f"{name}:year", minimum=1995, maximum=2020)
    month = _stable_number(f"{name}:month", minimum=1, maximum=12)
    day = _stable_number(f"{name}:day", minimum=1, maximum=28)
    return f"{day:02d}/{month:02d}/{year}"
