"""Lightweight coverage for the backend-owned CDD metadata display."""

from pathlib import Path


def test_cdd_metadata_uses_case_status_from_api_response() -> None:
    app = (Path(__file__).parents[1] / "src" / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "setCaseStatus(data.case_status" in app
    assert "CDD Generation" in app
    assert "No open risk flags in the current CDD object." not in app
    assert "riskFlagRecords" not in app
    assert "riskSummary" not in app
    assert '<span>Risk Flags</span>' not in app
    assert "generationStatusLabel" in app
    assert "cddStatusLabel" not in app
    assert "Evidence Quality" in app
    assert "/api/evidence-quality/run" in app
    assert "assessment.definition?.dimensions" in app
    assert "evidence-quality-tag" in app
    assert "Customer Business Profile" in app
    assert "EvidenceReview" in app
    assert "dimension.label" in app
    assert "evidence-quality-section" in app


def test_case_assessment_workspace_uses_the_renamed_summary_field() -> None:
    app = (Path(__file__).parents[1] / "src" / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "Case Assessment" in app
    assert "data.case_assessment_summary" in app
    assert "data.case_review_summary" not in app
    assert '<CaseReview\n                cddState={cddState}' in app
    assert 'function CDDCompleteness({ assessments, findings, loading, demoMode, onRun })' in app


def test_risk_ui_has_no_aml_presentation() -> None:
    app = (Path(__file__).parents[1] / "src" / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "AML Risk" not in app
    assert 'aml:' not in app


def test_json_view_renders_the_complete_cdd_state() -> None:
    app = (Path(__file__).parents[1] / "src" / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "setCddState(data.cdd_state || null);" in app
    assert "CDDState JSON" in app
    assert "JSON.stringify(cddState, null, 2)" in app
    assert "JSON.stringify(cdd, null, 2)" not in app


def test_json_view_has_an_accessible_copy_control() -> None:
    app = (Path(__file__).parents[1] / "src" / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "navigator.clipboard.writeText(formattedCddState)" in app
    assert 'aria-label="Copy CDDState JSON to clipboard"' in app
    assert "Copied JSON to clipboard." in app
    assert "Unable to copy JSON. Please select and copy it manually." in app
    assert 'role="status" aria-live="polite"' in app


def test_adverse_news_screening_ui_uses_retained_coverage_and_accessible_source_popovers() -> None:
    app = (Path(__file__).parents[1] / "src" / "frontend" / "app.js").read_text(encoding="utf-8")
    styles = (Path(__file__).parents[1] / "src" / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert '<AdverseNewsScreening cddState={cddState} onOpenTool={loadAdverseNewsFromCdd} />' in app
    assert 'finding.category === "adverse_news"' in app
    assert 'assessmentsByType(cddState, "adverse_news")' in app
    assert 'className="adverse-news-entity-list"' in app
    assert "one query for each screened entity" in app
    assert "unique ${sourceCount === 1 ? \"source result was\" : \"source results were\"} retained." in app
    assert "No material attributable adverse-news findings were identified in the retained results." in app
    assert "Screening unavailable." in app
    assert "function LinkedAdverseNewsText" in app
    assert "split(/(source:\\d+)/gi)" in app
    assert 'className="adverse-news-finding-tag confidence-tag"' in app
    assert 'className={`adverse-news-finding-tag severity-tag severity-${finding.severity?.level || "unknown"}`}' in app
    assert 'type="button"' in app
    assert "aria-expanded={sourcesOpen}" in app
    assert 'aria-controls={popoverId}' in app
    assert 'event.key === "Escape"' in app
    assert "right: calc(100% + 8px);" in styles


def test_standalone_adverse_news_tool_filters_cdd_records_and_supports_both_modes() -> None:
    app = (Path(__file__).parents[1] / "src" / "frontend" / "app.js").read_text(encoding="utf-8")

    assert '{ id: "adverse-news", label: "Adverse News" }' in app
    assert 'finding.category === "adverse_news"' in app
    assert 'item.tool === "adverse_news_screening"' in app
    assert 'fetch("/api/adverse-news/assess"' in app
    assert "Load from CDD" in app
    assert "Run independent Adverse News Check" in app
    assert "← Previous" in app
    assert "Next →" in app
    assert "Review in Adverse News tool" in app


def test_new_pipeline_run_clears_previous_cdd_display_and_document_links() -> None:
    app = (Path(__file__).parents[1] / "src" / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "function resetCddRunDisplay()" in app
    assert "setDocumentLinks({});" in app
    assert "setCaseAssessmentSummary(null);" in app
    assert "setPdfUrl(null);" in app
    assert 'if (data.status === "running") resetCddRunDisplay();' in app
    assert "const runEpoch = cddRunEpochRef.current;" in app


def test_document_management_displays_generation_errors() -> None:
    app = (Path(__file__).parents[1] / "src" / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "error={error}" in app
    assert "function DocumentManagement" in app
    assert "{error && <p className=\"risk\">{error}</p>}" in app
    assert 'fetch(`/api/session/${sessionId}`)' in app
    assert "Unable to refresh document status" in app


def test_other_risk_factors_checker_is_grouped_by_cdd_section() -> None:
    app = (Path(__file__).parents[1] / "src" / "frontend" / "app.js").read_text(encoding="utf-8")
    assert 'function OtherRiskFactors' in app
    assert 'assessmentsByType(cddState, "other_risk_factors")' in app
    assert 'fetch("/api/other-risk-factors/run"' in app
    assert 'EVIDENCE_SECTION_ORDER.map((section)' in app
    assert 'Matched evidence: ${indicator.evidence_id}' in app


def test_shell_company_risk_checker_surfaces_existing_csp_record_without_duplication() -> None:
    app = (Path(__file__).parents[1] / "src" / "frontend" / "app.js").read_text(encoding="utf-8")
    assert 'function ShellCompanyRisk' in app
    assert 'assessmentsByType(cddState, "shell_company_risk")' in app
    assert 'fetch("/api/shell-company-risk/run"' in app
    assert 'flag.category === "csp_address"' in app
    assert 'no duplicate Shell Company Risk finding was created' in app


def test_risk_flags_is_the_top_cdd_checker_card_with_rating_and_findings() -> None:
    app = (Path(__file__).parents[1] / "src" / "frontend" / "app.js").read_text(encoding="utf-8")
    assert 'function RiskFlags' in app
    assert 'assessmentsByType(cddState, "risk_rating")' in app
    assert 'fetch("/api/risk-rating/run"' in app
    assert app.index('<RiskFlags') < app.index('<CDDCompleteness')
    assert 'Confidence: ${statusLabel(finding.confidence?.level)}' in app


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
