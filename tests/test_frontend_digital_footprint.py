from pathlib import Path


def test_digital_footprint_tool_supports_cdd_and_independent_modes() -> None:
    app = Path("src/frontend/app.js").read_text()

    assert '{ id: "digital-footprint", label: "Digital Footprint" }' in app
    assert 'fetch("/api/digital-footprint/assess"' in app
    assert 'company_name: "", jurisdiction: "", registration_number: "", known_domain: "", registered_address: ""' in app
    assert "session_id" not in app[app.index("async function assessDigitalFootprint"):app.index("async function attachDigitalFootprint")]
    assert 'Section title="Assessment"' in app
    assert 'Section title="Findings"' in app
    assert 'assessmentsByType(cddState, "digital_footprint")' in app
    assert "<AdverseNewsFinding" in app
    assert 'fetch("/api/digital-footprint/attach"' in app
    assert 'function loadDigitalFootprintFromCdd()' in app
    assert 'function digitalFootprintRecords(cddState)' in app
    assert 'item.tool === "digital_footprint_assessment"' in app
    assert 'finding.category === "digital_footprint"' in app
    assert 'Load from CDD' in app
    assert 'Run independent Digital Footprint Check' in app
    assert '(activeWorkspace === "digital-footprint" && digitalFootprintMode === "cdd")' in app
    assert '<DigitalFootprintScreening cddState={cddState} onOpenTool={loadDigitalFootprintFromCdd} />' in app
    assert app.index('<AdverseNewsScreening') < app.index('<DigitalFootprintScreening')
    assert 'function digitalPresenceDimensions(definition)' in app
    assert 'definition={assessment.definition}' in app
    assert 'LEGACY_DIGITAL_PRESENCE_DIMENSIONS' in app
    cdd_section = app[app.index('function DigitalFootprintScreening'):app.index('function ManifestFootprintSection')]
    assert 'Review in Digital Footprint tool' in cdd_section
    assert '<DigitalPresenceBreakdown' not in cdd_section
    assert '<h3>Business Profile</h3>' not in cdd_section
