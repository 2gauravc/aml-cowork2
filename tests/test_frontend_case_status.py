"""Lightweight coverage for the backend-owned CDD metadata display."""

from pathlib import Path


def test_cdd_metadata_uses_case_status_from_api_response() -> None:
    app = (Path(__file__).parents[1] / "src" / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "setCaseStatus(data.case_status" in app
    assert "CDD Generation" in app
    assert "Risk Flags" in app
    assert "riskSummary" in app
    assert "Inconclusive" in app
    assert "generationStatusLabel" in app
    assert "cddStatusLabel" not in app


def test_new_pipeline_run_clears_previous_cdd_display_and_document_links() -> None:
    app = (Path(__file__).parents[1] / "src" / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "function resetCddRunDisplay()" in app
    assert "setDocumentLinks({});" in app
    assert "setCaseReviewSummary(null);" in app
    assert "setPdfUrl(null);" in app
    assert 'if (data.status === "running") resetCddRunDisplay();' in app
    assert "const runEpoch = cddRunEpochRef.current;" in app


def test_awaiting_documents_has_cdd_callout_and_documents_navigation() -> None:
    app = (Path(__file__).parents[1] / "src" / "frontend" / "app.js").read_text(encoding="utf-8")

    assert 'const cddPausedForDocuments = pipelineStatus === "awaiting_documents";' in app
    assert "CDD paused — documents required" in app
    assert 'setActiveWorkspace("generation")' in app
    assert "Generate the missing ID&V documents or upload customer-provided PDFs" in app


def test_pipeline_form_collects_account_opening_location() -> None:
    app = (Path(__file__).parents[1] / "src" / "frontend" / "app.js").read_text(encoding="utf-8")

    assert 'const ACCOUNT_OPENING_LOCATIONS = ["SG", "HK", "GB"];' in app
    assert 'aria-label="Account opening location"' in app
    assert "account_location: accountLocation" in app
    assert "!accountLocation" in app


def test_pipeline_form_uses_dropdown_placeholders_without_case_id() -> None:
    app = (Path(__file__).parents[1] / "src" / "frontend" / "app.js").read_text(encoding="utf-8")

    assert 'const [jurisdiction, setJurisdiction] = useState("");' in app
    assert '<option value="" disabled>Jurisdiction</option>' in app
    assert '<option value="" disabled>AO Location</option>' in app
    assert 'aria-label="Case ID"' not in app
    assert "case_id: caseId" not in app


def test_pipeline_form_gives_both_dropdowns_equal_width() -> None:
    styles = (Path(__file__).parents[1] / "src" / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert "grid-template-columns: minmax(220px, 2fr) minmax(120px, 1fr) minmax(120px, 1fr) auto auto;" in styles
