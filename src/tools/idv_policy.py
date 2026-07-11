#!/usr/bin/env python3
"""Interpret plain-English ID&V policy into structured requirements."""

from __future__ import annotations

import argparse
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

load_dotenv(PROJECT_ROOT / ".env")

DEFAULT_POLICY_PATH = PROJECT_ROOT / "policies" / "idv_policy.txt"
DEFAULT_MODEL = os.getenv("OPENAI_POLICY_MODEL") or os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

IDV_POLICY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "policy_name": {"type": "string"},
        "required_for": {
            "type": "array",
            "items": {"type": "string", "enum": ["ubo", "director"]},
        },
        "accepted_documents": {
            "type": "array",
            "items": {"type": "string", "enum": ["passport", "national_id"]},
        },
        "minimum_documents_per_individual": {"type": "integer", "minimum": 1},
        "notes": {"type": "string"},
    },
    "required": [
        "policy_name",
        "required_for",
        "accepted_documents",
        "minimum_documents_per_individual",
        "notes",
    ],
}


class PolicyInterpretationError(RuntimeError):
    """Raised when policy interpretation cannot complete."""


def load_policy_text(path: str | Path = DEFAULT_POLICY_PATH) -> str:
    return Path(path).read_text(encoding="utf-8")


def interpret_idv_policy(
    policy_text: str | None = None,
    *,
    policy_path: str | Path = DEFAULT_POLICY_PATH,
) -> dict[str, Any]:
    """Convert the plain-English ID&V policy to structured JSON using OpenAI."""
    text = policy_text if policy_text is not None else load_policy_text(policy_path)
    result = _run_policy_prompt(text)
    result["source_path"] = str(policy_path)
    result["method"] = "openai_policy_interpretation"
    return result


def _run_policy_prompt(policy_text: str) -> dict[str, Any]:
    if not os.getenv("OPENAI_API_KEY"):
        raise PolicyInterpretationError("OPENAI_API_KEY is required for policy interpretation")

    client = OpenAI()
    try:
        response = client.responses.create(
            model=DEFAULT_MODEL,
            input=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "Interpret this ID&V policy into the provided JSON schema. "
                                "Only include requirements explicitly supported by the policy.\n\n"
                                f"{policy_text}"
                            ),
                        }
                    ],
                }
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "idv_policy_requirements",
                    "schema": IDV_POLICY_SCHEMA,
                    "strict": True,
                }
            },
            temperature=0,
        )
    except OpenAIError as exc:
        raise PolicyInterpretationError(f"OpenAI policy interpretation failed: {exc}") from exc

    return _parse_response_json(response)


def _parse_response_json(response: Any) -> dict[str, Any]:
    text = getattr(response, "output_text", None)
    if not text:
        try:
            text = response.output[0].content[0].text
        except (AttributeError, IndexError, KeyError, TypeError):
            text = None
    if not text:
        raise PolicyInterpretationError("OpenAI response did not include JSON text")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PolicyInterpretationError("OpenAI response was not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise PolicyInterpretationError("OpenAI response JSON was not an object")
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser(description="Interpret the ID&V policy")
    parser.add_argument("--policy-path", default=str(DEFAULT_POLICY_PATH))
    args = parser.parse_args()

    result = interpret_idv_policy(policy_path=args.policy_path)
    json.dump(result, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
