"""Tests for stateless synthetic ID&V document generation."""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from src.backend.app import (
    STANDALONE_IDV_DOCUMENTS,
    StandaloneIDVDocumentRequest,
    _delete_standalone_idv_artifact,
    download_standalone_idv_document,
    generate_standalone_idv_document,
)


class StandaloneIDVDocumentGenerationTests(unittest.TestCase):
    def setUp(self) -> None:
        STANDALONE_IDV_DOCUMENTS.clear()

    def tearDown(self) -> None:
        STANDALONE_IDV_DOCUMENTS.clear()

    def test_generates_stateless_synthetic_document(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pdf_path = Path(directory) / "passport-jane.pdf"
            pdf_path.write_bytes(b"%PDF-1.7")
            artifact = {
                "document_type": "passport",
                "person_name": "Jane Example",
                "generated_at": "2026-07-21T00:00:00+00:00",
                "pdf_path": str(pdf_path),
                "html_path": str(Path(directory) / "passport-jane.html"),
                "json_path": str(Path(directory) / "passport-jane.json"),
            }
            request = StandaloneIDVDocumentRequest(full_name="Jane Example", document_type="passport")
            with patch.dict(os.environ, {"DEMO_MODE": "false"}, clear=False), patch(
                "src.backend.app.generate_idv_document", return_value=artifact
            ) as generate:
                response = asyncio.run(generate_standalone_idv_document(request))

            generate.assert_called_once()
            self.assertEqual(response["person_name"], "Jane Example")
            self.assertIn(response["artifact_id"], STANDALONE_IDV_DOCUMENTS)
            self.assertIn("not valid", response["notice"].lower())

    def test_rejects_generation_in_demo_mode(self) -> None:
        request = StandaloneIDVDocumentRequest(full_name="Jane Example", document_type="passport")
        with patch.dict(os.environ, {"DEMO_MODE": "true"}, clear=False), self.assertRaises(HTTPException) as raised:
            asyncio.run(generate_standalone_idv_document(request))

        self.assertEqual(raised.exception.status_code, 400)

    def test_download_requires_known_artifact(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            asyncio.run(download_standalone_idv_document("missing"))

        self.assertEqual(raised.exception.status_code, 404)

    def test_download_returns_registered_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pdf_path = Path(directory) / "passport-jane.pdf"
            pdf_path.write_bytes(b"%PDF-1.7")
            STANDALONE_IDV_DOCUMENTS["artifact"] = {"pdf_path": pdf_path}

            response = asyncio.run(download_standalone_idv_document("artifact"))

        self.assertEqual(Path(response.path), pdf_path)

    def test_cleanup_removes_all_generated_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = {
                "pdf_path": Path(directory) / "document.pdf",
                "html_path": Path(directory) / "document.html",
                "json_path": Path(directory) / "document.json",
            }
            for path in paths.values():
                path.write_text("synthetic", encoding="utf-8")
            STANDALONE_IDV_DOCUMENTS["artifact"] = paths

            _delete_standalone_idv_artifact("artifact")

            self.assertNotIn("artifact", STANDALONE_IDV_DOCUMENTS)
            self.assertFalse(any(path.exists() for path in paths.values()))
