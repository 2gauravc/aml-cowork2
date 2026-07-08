"""Render final CDD JSON into an HTML template and PDF report."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from xhtml2pdf import pisa


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = PROJECT_ROOT / "templates"
OUTPUT_DIR = PROJECT_ROOT / "outputs"
DEFAULT_TEMPLATE = "CDD.html"


def render_cdd_pdf(
    cdd: dict[str, Any],
    *,
    output_dir: Path | str = OUTPUT_DIR,
    template_name: str = DEFAULT_TEMPLATE,
) -> Path:
    """Render the CDD JSON to HTML and convert it to a PDF file."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    html = render_cdd_html(cdd, template_name=template_name)
    pdf_path = output_dir / _pdf_filename(cdd)
    with open(pdf_path, "wb") as fh:
        status = pisa.CreatePDF(html, dest=fh)

    if status.err:
        raise RuntimeError(f"Failed to generate PDF report at {pdf_path}")
    return pdf_path


def render_cdd_html(
    cdd: dict[str, Any],
    *,
    template_name: str = DEFAULT_TEMPLATE,
) -> str:
    """Render CDD JSON to the HTML report template."""
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(("html", "xml")),
    )
    env.filters["blank"] = _blank
    env.filters["percent"] = _percent
    env.filters["date"] = _date_only
    template = env.get_template(template_name)
    return template.render(cdd=cdd, generated_at=datetime.now(UTC).isoformat())


def _pdf_filename(cdd: dict[str, Any]) -> str:
    name = (
        cdd.get("company_business_profile", {})
        .get("customer_static", {})
        .get("name")
        or "CDD"
    )
    safe_name = re.sub(r"[^A-Za-z0-9]+", "-", str(name)).strip("-") or "CDD"
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return f"CDD-{safe_name}-{timestamp}.pdf"


def _blank(value: Any) -> str:
    if value in (None, "", [], {}):
        return "-"
    return str(value)


def _percent(value: Any) -> str:
    if value in (None, ""):
        return "-"
    try:
        return f"{float(value):.2f}%"
    except (TypeError, ValueError):
        return str(value)


def _date_only(value: Any) -> str:
    if not value:
        return "-"
    text = str(value)
    return text[:10] if "T" in text else text
