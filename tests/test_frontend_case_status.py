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


def test_cdd_maker_includes_the_assessment_cards() -> None:
    app = (Path(__file__).parents[1] / "src" / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "CDD Checker" not in app
    assert '<CDDReviewCards\n            cddState={cddState}' in app
    assert 'function CDDCompleteness({ assessments, findings, loading, demoMode, onRun })' in app


def test_cdd_maker_uses_collapsed_accordion_panels_for_case_sections() -> None:
    app = (Path(__file__).parents[1] / "src" / "frontend" / "app.js").read_text(encoding="utf-8")
    styles = (Path(__file__).parents[1] / "src" / "frontend" / "styles.css").read_text(encoding="utf-8")

    for title in ("Customer Business Profile", "Ownership & Control", "ID&V", "Adverse News Screening", "Digital Footprint", "Shell Company Risk", "Other Risk Factors", "CDD Completeness", "Evidence Quality", "All Findings", "Risk Rating"):
        assert f'title="{title}" collapsible' in app
    assert '<details className="section collapsible-section">' in app
    assert '.collapsible-section > summary' in styles


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


def test_saved_completed_state_can_be_loaded_before_a_new_run() -> None:
    app = (Path(__file__).parents[1] / "src" / "frontend" / "app.js").read_text(encoding="utf-8")

    assert 'fetch("/api/cdd-states/availability"' in app
    assert 'fetch("/api/cdd-states/load"' in app
    assert "Load saved CDD" in app
    assert "Start new CDD run" in app


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
    assert 'cspAssessments' in app
    assert 'no duplicate Shell Company Risk finding was created' in app
    assert '<h3>Screening</h3><strong>CSP Address</strong>' not in app


def test_cdd_maker_orders_assessment_cards_and_separates_findings_from_risk_rating() -> None:
    app = (Path(__file__).parents[1] / "src" / "frontend" / "app.js").read_text(encoding="utf-8")
    assert 'function Findings' in app
    assert 'function RiskRating' in app
    assert '<Section title="All Findings" collapsible>' in app
    assert 'assessmentsByType(cddState, "risk_rating")' in app
    assert 'fetch("/api/risk-rating/run"' in app
    assert app.index('<ShellCompanyRisk') < app.index('<OtherRiskFactors') < app.index('<CDDCompleteness') < app.index('<EvidenceQuality') < app.index('<Findings') < app.index('<RiskRating')
    assert 'Risk score: ${rating.total_score}' in app
    assert 'rating.rule_explanation || rating.summary' in app
    assert 'Risk Rating Rubric' in app
    assert 'material_adverse_news: "Material Adverse News finding"' in app
    assert '<th>Available points</th><th>Score</th>' in app
    assert '<th colSpan="2">Total score</th>' in app
    assert '<th colSpan="2">Final rating</th>' in app
    assert 'Inconclusive: a required assessment is missing or unavailable.' in app
    assert 'Confidence: ${statusLabel(finding.confidence?.level)}' in app


def test_awaiting_documents_has_cdd_callout_and_documents_navigation() -> None:
    app = (Path(__file__).parents[1] / "src" / "frontend" / "app.js").read_text(encoding="utf-8")

    assert 'const cddPausedForDocuments = pipelineStatus === "awaiting_documents";' in app


def test_saved_cdd_loading_uses_a_dedicated_status_instead_of_chat_history() -> None:
    app = (Path(__file__).parents[1] / "src" / "frontend" / "app.js").read_text(encoding="utf-8")

    assert 'const loadingSavedCdd = pipelineLoading && Boolean(savedStatePrompt);' in app
    assert '? "Loading saved CDD…"' in app
    assert app.index('const loadingSavedCdd') < app.index('latestAssistantMessage(messages)')


def test_document_actions_poll_after_starting_a_background_resume() -> None:
    app = (Path(__file__).parents[1] / "src" / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "resumeStarted = resumeStarted || data.status === \"running\";" in app
    assert "Document generation completed — CDD restarted." in app
    assert 'cddPausedForDocuments ? "Paused"' in app
    assert 'pipelineStatus === "awaiting_documents"' in app
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
