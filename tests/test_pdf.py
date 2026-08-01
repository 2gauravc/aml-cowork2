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
            {"assessment_id": "assessment:shell", "assessment_type": "shell_company_risk", "title": "Registered-address indicator", "summary": "No indicator matched", "cdd_section": "customer_business_profile"},
            {"assessment_id": "assessment:other", "assessment_type": "other_risk_factors", "title": "High-risk industry", "summary": "No industry risk", "cdd_section": "screening"},
            {"assessment_id": "assessment:risk", "assessment_type": "risk_rating", "rating": "low", "total_score": 0, "summary": "No factors were triggered", "definition": {"factor_scores": {"high_risk_industry": 2}}},
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
        "Shell Company Risk",
        "Other Risk Factors",
        "CDD Completeness",
        "Evidence Quality",
        "All Findings",
        "Risk Rating",
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
    assert "CDD Checker" not in html
    assert html.index("Shell Company Risk") < html.index("Other Risk Factors") < html.index("CDD Completeness") < html.index("Evidence Quality") < html.index("All Findings") < html.index("Risk Rating")
    assert "Risk score: 0" in html


def test_report_pdf_renders_complete_state(tmp_path: Path) -> None:
    pdf_path = render_cdd_pdf(_state(), output_dir=tmp_path)

    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 0


def test_report_replaces_legacy_risk_rating_with_deterministic_rubric() -> None:
    state = _state()
    state["findings"] = []
    state["assessments"].extend([
        {"assessment_id": "assessment:adverse-input", "assessment_type": "adverse_news", "outcome": "completed_no_material_findings", "created_at": "2026-01-01T00:00:00Z"},
        {"assessment_id": "assessment:shell-input", "assessment_type": "shell_company_risk", "outcome": "not_triggered", "created_at": "2026-01-01T00:00:00Z"},
        {"assessment_id": "assessment:industry-input", "assessment_type": "other_risk_factors", "factor_id": "high_risk_industry", "outcome": "not_triggered", "created_at": "2026-01-01T00:00:00Z"},
        {"assessment_id": "assessment:aml-input", "assessment_type": "other_risk_factors", "factor_id": "high_aml_risk_jurisdiction_link", "outcome": "not_triggered", "created_at": "2026-01-01T00:00:00Z"},
        {"assessment_id": "assessment:tax-input", "assessment_type": "other_risk_factors", "factor_id": "high_tax_risk_jurisdiction_link", "outcome": "not_triggered", "created_at": "2026-01-01T00:00:00Z"},
        {"assessment_id": "assessment:legacy-risk", "assessment_type": "risk_rating", "rating": "standalone_high", "summary": "Legacy model rating"},
    ])

    html = render_cdd_html(state)

    assert "standalone_high" not in html
    assert "Legacy model rating" not in html
    assert "Risk score: 0" in html
    assert "Risk Rating Rubric" in html
    assert "High Risk Industry" in html
