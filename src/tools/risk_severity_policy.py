"""Interpret and apply the user-authored risk-severity policy."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.tools.idv_policy import PolicyInterpretationError, _run_policy_prompt


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_POLICY_PATH = PROJECT_ROOT / "policies" / "risk_severity_policy.txt"

RISK_SEVERITY_POLICY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "policy_name": {"type": "string"},
        "rules": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "category": {"type": "string", "enum": ["ownership", "aml", "csp_address"]},
                    "evaluation": {"type": "string", "enum": ["yes", "no", "inconclusive"]},
                    "severity": {"type": "string", "enum": ["none", "low", "medium", "high"]},
                },
                "required": ["category", "evaluation", "severity"],
            },
        },
        "notes": {"type": "string"},
    },
    "required": ["policy_name", "rules", "notes"],
}


def interpret_risk_severity_policy(policy_path: str | Path = DEFAULT_POLICY_PATH) -> dict[str, Any]:
    text = Path(policy_path).read_text(encoding="utf-8")
    result = _run_risk_policy_prompt(text)
    result["source_path"] = str(policy_path)
    result["method"] = "openai_policy_interpretation"
    return result


def _run_risk_policy_prompt(policy_text: str) -> dict[str, Any]:
    # Reuse the ID&V interpreter's OpenAI client/error handling while supplying
    # a risk-specific strict schema.
    import os
    from openai import OpenAI, OpenAIError

    if not os.getenv("OPENAI_API_KEY"):
        raise PolicyInterpretationError("OPENAI_API_KEY is required for policy interpretation")
    try:
        response = OpenAI().responses.create(
            model=os.getenv("OPENAI_POLICY_MODEL") or os.getenv("OPENAI_MODEL", "gpt-5.6"),
            input=[{"role": "user", "content": [{"type": "input_text", "text": (
                "Interpret this risk-severity policy into the provided JSON schema. "
                "Only include rules explicitly supported by the policy.\n\n" + policy_text
            )}]}],
            text={"format": {"type": "json_schema", "name": "risk_severity_policy", "schema": RISK_SEVERITY_POLICY_SCHEMA, "strict": True}},
        )
    except OpenAIError as exc:
        raise PolicyInterpretationError(f"Risk-severity policy interpretation failed: {exc}") from exc
    from src.tools.idv_policy import _parse_response_json
    return _parse_response_json(response)


def apply_risk_severity_policy(
    findings: list[dict[str, Any]], policy: dict[str, Any],
) -> list[dict[str, Any]]:
    rules = {
        (rule["category"], rule["evaluation"]): rule["severity"]
        for rule in policy.get("rules", [])
    }
    return [
        {
            **finding,
            "severity": rules.get((finding.get("category"), finding.get("evaluation")), "none"),
            "severity_policy": {"name": policy.get("policy_name"), "source_path": policy.get("source_path")},
        }
        for finding in findings
    ]
