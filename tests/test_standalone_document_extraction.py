"""Tests for the stateless standalone document extraction endpoint."""

from __future__ import annotations

import asyncio
import io
import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException, UploadFile

from src.backend.app import DOCUMENT_EXTRACTION_STAGING_DIR, extract_standalone_document


class StandaloneDocumentExtractionTests(unittest.TestCase):
    def _upload(self, content: bytes = b"%PDF-1.7 sample") -> UploadFile:
        return UploadFile(filename="identity.pdf", file=io.BytesIO(content), headers={"content-type": "application/pdf"})

    def _image_upload(self) -> UploadFile:
        return UploadFile(
            filename="passport.png",
            file=io.BytesIO(b"\x89PNG\r\n\x1a\nimage"),
            headers={"content-type": "image/png"},
        )

    def test_extracts_without_session_and_removes_staged_file(self) -> None:
        classification = {"document_type": "passport", "confidence": 0.98, "reason": "Passport layout"}
        extraction = {"full_name": "Jane Example", "document_number": "P123"}
        with patch.dict(os.environ, {"DEMO_MODE": "false"}, clear=False), patch(
            "src.backend.app.classify_document", return_value=classification
        ), patch(
            "src.backend.app.extract_document", return_value=extraction
        ):
            response = asyncio.run(extract_standalone_document(self._upload()))

        self.assertEqual(response, {"classification": classification, "extraction": extraction})
        self.assertFalse(list(DOCUMENT_EXTRACTION_STAGING_DIR.glob("*identity.pdf")))

    def test_accepts_image_documents(self) -> None:
        classification = {"document_type": "passport", "confidence": 0.98, "reason": "Passport image"}
        extraction = {"full_name": "Jane Example"}
        with patch.dict(os.environ, {"DEMO_MODE": "false"}, clear=False), patch(
            "src.backend.app.classify_document", return_value=classification
        ), patch("src.backend.app.extract_document", return_value=extraction):
            response = asyncio.run(extract_standalone_document(self._image_upload()))

        self.assertEqual(response["classification"], classification)

    def test_rejects_non_pdf_content(self) -> None:
        with patch.dict(os.environ, {"DEMO_MODE": "false"}, clear=False), self.assertRaises(HTTPException) as raised:
            asyncio.run(extract_standalone_document(self._upload(b"not a PDF")))

        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(raised.exception.detail, "Uploaded file does not match its declared document type")

    def test_is_disabled_in_demo_mode(self) -> None:
        with patch.dict(os.environ, {"DEMO_MODE": "true"}, clear=False), self.assertRaises(HTTPException) as raised:
            asyncio.run(extract_standalone_document(self._upload()))

        self.assertEqual(raised.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
