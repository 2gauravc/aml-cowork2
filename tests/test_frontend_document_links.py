"""Coverage for retaining cached document download links in the browser."""

from pathlib import Path


def test_cached_document_requirement_keys_are_retained_in_document_links() -> None:
    app = (Path(__file__).parents[1] / "src" / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "setDocumentRequirements((data.documents || []).filter((document) => document.purpose));" in app
    assert "artifact?.reused_from_s3" in app
    assert "].filter(Boolean));" in app
    assert "Object.entries(current).filter(([key]) => keys.has(key))" in app
