#!/usr/bin/env python3
"""Classify and extract generated document data for CDD enrichment."""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI, OpenAIError

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.document_pipeline import REGISTRY_SOURCE_LABEL  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

SCHEMA_DIR = PROJECT_ROOT / "config" / "schemas"
DEFAULT_MODEL = os.getenv("OPENAI_DOCUMENT_MODEL") or os.getenv("OPENAI_MODEL", "gpt-5.6")

CLASSIFICATION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "document_type": {
            "type": "string",
            "enum": ["registry_document", "passport", "national_id", "other"],
        },
        "confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
        },
        "reason": {
            "type": "string",
        },
    },
    "required": ["document_type", "confidence", "reason"],
}


class DocumentExtractionError(RuntimeError):
    """Raised when OpenAI-backed document extraction cannot complete."""


def classify_document(path: str | Path) -> dict[str, Any]:
    """Classify a PDF document using OpenAI."""
    result = _run_schema_prompt(
        pdf_path=Path(path),
        schema_name="document_classification",
        schema=CLASSIFICATION_SCHEMA,
        prompt=(
            "Classify this document as one of: registry_document, passport, "
            "national_id, or other. Use only the visible document content."
        ),
    )
    result["method"] = "openai_pdf_schema_classification"
    return result


def extract_document(
    artifact: dict[str, Any],
    *,
    classification: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract structured values from a PDF document using OpenAI and a schema."""
    pdf_path = artifact.get("pdf_path") or artifact.get("path")
    if not pdf_path:
        raise ValueError("Document artifact is missing pdf_path")

    classification = classification or classify_document(pdf_path)
    document_type = classification.get("document_type", "other")
    if document_type == "other":
        return {
            "document_type": "other",
            "extraction": {
                "method": "openai_pdf_schema_extraction",
                "source": "OpenAI document extraction",
                "document_path": str(pdf_path),
            },
        }

    schema = _schema_for_document_type(document_type)
    result = _run_schema_prompt(
        pdf_path=Path(pdf_path),
        schema_name=f"{document_type}_extraction",
        schema=schema,
        prompt=(
            f"Extract this {document_type} into the provided JSON schema. "
            "Use null-free strings where the document provides data. If a field "
            "is not present, use an empty string. Do not infer values that are "
            "not visible in the document."
        ),
    )
    result["extraction"] = {
        "method": "openai_pdf_schema_extraction",
        "source": _source_label(document_type),
        "document_path": str(pdf_path),
        "model": DEFAULT_MODEL,
    }
    return result


def _schema_for_document_type(document_type: str) -> dict[str, Any]:
    schema_paths = {
        "registry_document": SCHEMA_DIR / "registry_document.schema.json",
        "passport": SCHEMA_DIR / "passport.schema.json",
        "national_id": SCHEMA_DIR / "national_id.schema.json",
    }
    path = schema_paths.get(document_type)
    if not path:
        raise ValueError(f"Unsupported document type for extraction: {document_type}")
    return json.loads(path.read_text(encoding="utf-8"))


def _source_label(document_type: str) -> str:
    return {
        "registry_document": REGISTRY_SOURCE_LABEL,
        "passport": "Passport Document",
        "national_id": "National ID Document",
    }.get(document_type, "Document")


def _run_schema_prompt(
    *,
    pdf_path: Path,
    schema_name: str,
    schema: dict[str, Any],
    prompt: str,
) -> dict[str, Any]:
    if not os.getenv("OPENAI_API_KEY"):
        raise DocumentExtractionError("OPENAI_API_KEY is required for document extraction")
    if not pdf_path.exists():
        raise FileNotFoundError(pdf_path)

    client = OpenAI()
    file_data = _pdf_file_data(pdf_path)
    try:
        response = client.responses.create(
            model=DEFAULT_MODEL,
            input=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_file",
                            "filename": pdf_path.name,
                            "file_data": file_data,
                        },
                        {
                            "type": "input_text",
                            "text": prompt,
                        },
                    ],
                }
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "schema": schema,
                    "strict": True,
                }
            },
            temperature=0,
        )
    except OpenAIError as exc:
        raise DocumentExtractionError(f"OpenAI document extraction failed: {exc}") from exc

    return _parse_response_json(response)


def _pdf_file_data(path: Path) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("utf-8")
    return f"data:application/pdf;base64,{encoded}"


def _parse_response_json(response: Any) -> dict[str, Any]:
    text = getattr(response, "output_text", None)
    if not text:
        try:
            text = response.output[0].content[0].text
        except (AttributeError, IndexError, KeyError, TypeError):
            text = None
    if not text:
        raise DocumentExtractionError("OpenAI response did not include JSON text")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DocumentExtractionError("OpenAI response was not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise DocumentExtractionError("OpenAI response JSON was not an object")
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser(description="Classify and extract a document artifact")
    parser.add_argument("--artifact-json", required=True, help="Path to generated artifact JSON")
    args = parser.parse_args()

    artifact = json.loads(Path(args.artifact_json).read_text(encoding="utf-8"))
    classification = classify_document(artifact.get("pdf_path", ""))
    extract = extract_document(artifact, classification=classification)
    json.dump(
        {"classification": classification, "extract": extract},
        sys.stdout,
        indent=2,
        ensure_ascii=False,
    )
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
