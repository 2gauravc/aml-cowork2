"""Regression coverage for parameters unsupported by the GPT-5.6 model family."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.tools.document_extraction import _run_schema_prompt


class OpenAIModelParameterTests(unittest.TestCase):
    def test_document_extraction_omits_temperature_for_gpt_5_6(self) -> None:
        response = Mock()
        response.output_text = '{"document_number":"ABC123"}'
        client = Mock()
        client.responses.create.return_value = response

        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), patch(
            "src.tools.document_extraction.OpenAI", return_value=client
        ), patch("src.tools.document_extraction._pdf_file_data", return_value="data:application/pdf;base64,AA=="), patch.object(
            Path, "exists", return_value=True
        ):
            _run_schema_prompt(
                pdf_path=Path("fixture.pdf"),
                schema_name="passport_extraction",
                schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"document_number": {"type": "string"}},
                    "required": ["document_number"],
                },
                prompt="Extract the document.",
            )

        request = client.responses.create.call_args.kwargs
        self.assertEqual(request["model"], "gpt-5.6")
        self.assertNotIn("temperature", request)

    def test_document_extraction_uses_image_input_for_png(self) -> None:
        response = Mock()
        response.output_text = '{"document_number":"ABC123"}'
        client = Mock()
        client.responses.create.return_value = response

        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), patch(
            "src.tools.document_extraction.OpenAI", return_value=client
        ), patch.object(Path, "exists", return_value=True), patch.object(
            Path, "read_bytes", return_value=b"\x89PNG\r\n\x1a\nimage"
        ):
            _run_schema_prompt(
                pdf_path=Path("fixture.png"),
                schema_name="passport_extraction",
                schema={"type": "object", "additionalProperties": False, "properties": {}, "required": []},
                prompt="Extract the document.",
            )

        content = client.responses.create.call_args.kwargs["input"][0]["content"]
        self.assertEqual(content[0]["type"], "input_image")
        self.assertTrue(content[0]["image_url"].startswith("data:image/png;base64,"))


if __name__ == "__main__":
    unittest.main()
