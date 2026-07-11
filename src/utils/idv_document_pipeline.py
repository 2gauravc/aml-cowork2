"""Synthetic demo identity document generation for ID&V."""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from xhtml2pdf import pisa


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = PROJECT_ROOT / "config" / "templates"
DOCUMENT_DIR = PROJECT_ROOT / "generated_documents"

IDV_SOURCE_LABELS = {
    "passport": "Passport Document",
    "national_id": "National ID Document",
}


def generate_idv_documents(
    individuals: list[dict[str, Any]],
    *,
    output_dir: Path | str = DOCUMENT_DIR,
) -> list[dict[str, Any]]:
    """Generate one synthetic ID document artifact per required individual."""
    return [
        generate_idv_document(individual, output_dir=output_dir)
        for individual in individuals
        if individual.get("name")
    ]


def generate_idv_document(
    individual: dict[str, Any],
    *,
    output_dir: Path | str = DOCUMENT_DIR,
) -> dict[str, Any]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    document = _identity_document_data(individual)
    stem = _document_stem(document)
    html_path = output_dir / f"{stem}.html"
    pdf_path = output_dir / f"{stem}.pdf"
    json_path = output_dir / f"{stem}.json"

    html = _render_identity_html(document)
    html_path.write_text(html, encoding="utf-8")
    json_path.write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    with pdf_path.open("wb") as fh:
        status = pisa.CreatePDF(html, dest=fh)
    if status.err:
        raise RuntimeError(f"Failed to generate ID&V document at {pdf_path}")

    return {
        "document_type": document["document_type"],
        "source": IDV_SOURCE_LABELS.get(document["document_type"], "Identity Document"),
        "person_name": document["full_name"],
        "case_common_id": individual.get("case_common_id"),
        "html_path": str(html_path),
        "pdf_path": str(pdf_path),
        "json_path": str(json_path),
        "generated_at": datetime.now(UTC).isoformat(),
    }


def _identity_document_data(individual: dict[str, Any]) -> dict[str, Any]:
    name = str(individual.get("name") or "Demo Person")
    document_type = individual.get("selected_document_type") or "passport"
    if document_type not in IDV_SOURCE_LABELS:
        document_type = "passport"

    seed = _seed(name)
    nationality = individual.get("nationality") or _demo_country(seed)
    issuing_country = individual.get("issuing_country") or nationality
    birth_year = 1965 + seed % 35
    dob = date(birth_year, (seed % 12) + 1, (seed % 27) + 1)
    expiry = date.today() + timedelta(days=365 * (5 + seed % 5))
    data = {
        "document_type": document_type,
        "full_name": name,
        "document_number": _document_number(document_type, seed),
        "nationality": nationality,
        "date_of_birth": dob.isoformat(),
        "expiry_date": expiry.isoformat(),
        "issuing_country": issuing_country,
    }
    if document_type == "national_id":
        data["address"] = individual.get("address") or f"{(seed % 88) + 10} Demo ID Street"
    return data


def _render_identity_html(document: dict[str, Any]) -> str:
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(("html", "xml")),
    )
    template_name = "passport.html" if document["document_type"] == "passport" else "national_id.html"
    template = env.get_template(template_name)
    return template.render(document=document)


def _document_stem(document: dict[str, Any]) -> str:
    safe_name = re.sub(r"[^A-Za-z0-9]+", "-", document["full_name"]).strip("-") or "Person"
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return f"{document['document_type']}-{safe_name}-{timestamp}"


def _document_number(document_type: str, seed: int) -> str:
    prefix = "P" if document_type == "passport" else "ID"
    return f"{prefix}{seed % 100000000:08d}"


def _demo_country(seed: int) -> str:
    countries = ["GB", "SG", "HK", "CH", "US"]
    return countries[seed % len(countries)]


def _seed(value: str) -> int:
    return sum((index + 1) * ord(char) for index, char in enumerate(value))
