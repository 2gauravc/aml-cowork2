from pathlib import Path


def test_digital_footprint_tool_is_standalone_in_ui() -> None:
    app = Path("src/frontend/app.js").read_text()

    assert '{ id: "digital-footprint", label: "Digital Footprint" }' in app
    assert 'fetch("/api/digital-footprint/assess"' in app
    assert 'company_name: "", jurisdiction: "", registration_number: "", known_domain: "", registered_address: ""' in app
    assert "session_id" not in app[app.index("async function assessDigitalFootprint"):app.index("function selectExtractionFile")]
