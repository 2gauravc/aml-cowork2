"""Regression coverage for the complete-state CDD PDF report."""

from pathlib import Path

from src.utils.pdf import render_cdd_html, render_cdd_pdf


def _state() -> dict:
    return {
        "metadata": {"customer": {"name": "Acme Ltd", "jurisdiction": "GB"}, "kyc_case": {"case_id": "case-92"}},
        "cdd": {
            "started_at": "2026-07-28T05:14:21Z",
            "company_business_profile": {"customer_static": {"name": "Acme Ltd", "registration_number": "123"}},
            "ownership_and_control": {"ubos": [{"name": "Jane Doe", "effective_shareholding_percent": 75}]},
            "individual_identity_verification": {"required_individuals": [{"name": "Jane Doe", "status": "verified"}]},
        },
        "evidence": [
            {"evidence_id": "evidence:adverse", "tool": "adverse_news_screening", "data": {"source_url": "https://news.example/test", "detail": {"nested": {"value": "retained"}}}},
            {"evidence_id": "evidence:digital", "tool": "digital_footprint_assessment", "data": {"website": "https://acme.example"}},
        ],
        "findings": [{"finding_id": "finding:adverse", "category": "adverse_news", "title": "Example finding"}],
        "assessments": [
            {"assessment_id": "assessment:adverse", "assessment_type": "adverse_news", "summary": "Screening complete"},
            {"assessment_id": "assessment:digital", "assessment_type": "digital_footprint", "summary": "Assessment complete"},
            {"assessment_id": "assessment:completeness", "assessment_type": "cdd_completeness", "summary": "CDD complete"},
            {"assessment_id": "assessment:quality", "assessment_type": "evidence_quality", "summary": "Evidence sufficient"},
        ],
        "case_status": {"cdd_generation": "completed"},
    }


def test_report_html_includes_requested_sections_and_full_state_json() -> None:
    html = render_cdd_html(_state())

    for heading in (
        "CDD Metadata",
        "Customer Business Profile",
        "Ownership &amp; Control",
        "ID&amp;V",
        "Adverse News Screening",
        "Digital Footprint",
        "CDD Completeness Check",
        "Evidence Quality Check",
        "Full CDDState JSON",
    ):
        assert heading in html
    for ui_label in ("Registration No", "UBOs", "Shareholders &gt; 10%", "Related Parties", "Document No"):
        assert ui_label in html
    assert "case-92" in html
    assert "CDD Generation" in html
    assert "https://news.example/test" in html
    assert "https://acme.example" in html
    assert "All Business Profile Details" not in html
    assert "Retained Tool Evidence" not in html


def test_report_pdf_renders_complete_state(tmp_path: Path) -> None:
    pdf_path = render_cdd_pdf(_state(), output_dir=tmp_path)

    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 0
