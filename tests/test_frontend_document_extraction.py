"""Lightweight coverage for the standalone document extraction workspace."""

from pathlib import Path


def test_document_extraction_workspace_calls_stateless_endpoint() -> None:
    app = (Path(__file__).parents[1] / "src" / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "Document Extraction" in app
    assert 'setActiveWorkspace("document-extraction")' in app
    assert 'fetch("/api/document-extraction/extract", { method: "POST", body })' in app
    assert "<DocumentExtraction" in app
    assert "image/png" in app
    assert "ID&V Document Generation" in app
    assert 'fetch("/api/idv-document-generation/generate"' in app
    assert "downloadStandaloneIdvDocument" in app
