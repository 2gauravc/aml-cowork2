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
