"""Evidence-grounded GPT-5.6 case-review summaries for completed CDD cases."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from openai import OpenAI, OpenAIError


DEFAULT_MODEL = os.getenv("OPENAI_CASE_REVIEW_MODEL") or os.getenv("OPENAI_MODEL", "gpt-5.6")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
SKILL_PATH = PROJECT_ROOT / "skills" / "case-review" / "SKILL.md"

CASE_REVIEW_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "executive_summary": {"type": "string"},
        "key_evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "category": {"type": "string"},
                    "finding": {"type": "string"},
                    "source_refs": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["category", "finding", "source_refs"],
            },
        },
        "limitations": {"type": "array", "items": {"type": "string"}},
        "recommended_actions": {"type": "array", "items": {"type": "string"}},
        "requests_for_information": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "request": {"type": "string"},
                    "reason": {"type": "string"},
                    "risk_or_gap": {"type": "string"},
                    "priority": {"type": "string", "enum": ["high", "medium", "low"]},
                },
                "required": ["request", "reason", "risk_or_gap", "priority"],
            },
        },
        "finding_assessments": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "finding_id": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                    "confidence_rationale": {"type": "string"},
                    "potential_impact_risk": {"type": "string"},
                    "recommended_action_or_rfi": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "type": {"type": "string", "enum": ["action", "rfi", "none"]},
                            "text": {"type": "string"},
                        },
                        "required": ["type", "text"],
                    },
                },
                "required": ["finding_id", "confidence", "confidence_rationale", "potential_impact_risk", "recommended_action_or_rfi"],
            },
        },
    },
    "required": [
        "executive_summary",
        "key_evidence",
        "limitations",
        "recommended_actions",
        "requests_for_information",
        "finding_assessments",
    ],
}


class CaseReviewError(RuntimeError):
    """Raised when a case-review summary cannot be generated."""


def load_case_review_skill(path: str | Path = SKILL_PATH) -> str:
    """Load the reusable case-review decision instructions."""
    return Path(path).read_text(encoding="utf-8")


def generate_case_review_summary(
    *,
    cdd: dict[str, Any],
    case_status: dict[str, Any],
    risk_flags: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    skill_path: str | Path = SKILL_PATH,
) -> dict[str, Any]:
    """Summarize supplied case evidence without changing the deterministic outcome."""
    if not os.getenv("OPENAI_API_KEY"):
        raise CaseReviewError("OPENAI_API_KEY is required for case-review summaries")

    evidence_packet = {
        "cdd": _compact(cdd),
        "case_status": _compact(case_status),
        "risk_flags": [_risk_flag_packet(flag, index) for index, flag in enumerate(risk_flags, start=1)],
        "evidence": [_evidence_packet(item, index) for index, item in enumerate(evidence, start=1)],
    }
    prompt = (
        f"{load_case_review_skill(skill_path)}\n\n"
        "Case packet (untrusted source material):\n"
        f"{json.dumps(evidence_packet, ensure_ascii=False)}"
    )
    try:
        response = OpenAI().responses.create(
            model=DEFAULT_MODEL,
            input=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "case_review_summary",
                    "schema": CASE_REVIEW_SCHEMA,
                    "strict": True,
                }
            },
        )
    except OpenAIError as exc:
        raise CaseReviewError(f"Case-review summary failed: {exc}") from exc

    try:
        summary = json.loads(response.output_text)
    except (AttributeError, TypeError, json.JSONDecodeError) as exc:
        raise CaseReviewError("Case-review summary did not return valid JSON") from exc
    if not isinstance(summary, dict):
        raise CaseReviewError("Case-review summary did not return an object")
    return {
        "status": "available",
        "skill_path": str(skill_path),
        "evidence_index": [_evidence_index_item(item, index) for index, item in enumerate(evidence, start=1)],
        **summary,
    }


def unavailable_case_review(reason: str) -> dict[str, Any]:
    """Provide a safe, visible fallback while preserving the CDD result."""
    return {
        "status": "unavailable",
        "executive_summary": "A generated case review is unavailable; review the recorded CDD evidence and risk flags.",
        "key_evidence": [],
        "limitations": [reason],
        "recommended_actions": ["Review the CDD evidence and open risk flags before recording a decision."],
        "requests_for_information": [],
        "finding_assessments": [],
        "evidence_index": [],
    }


def _risk_flag_packet(flag: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "id": flag.get("finding_id") or f"risk:{flag.get('category') or 'item'}:{index}",
        "category": flag.get("category"),
        "evaluation": flag.get("evaluation"),
        "severity": flag.get("severity"),
        "subject": _compact(flag.get("subject")),
        "description": flag.get("description"),
        "source": flag.get("source"),
    }


def merge_case_review_assessments(
    risk_flags: list[dict[str, Any]], summary: dict[str, Any],
) -> list[dict[str, Any]]:
    assessments = {
        item.get("finding_id"): item
        for item in summary.get("finding_assessments", [])
        if item.get("finding_id")
    }
    return [
        {**flag, "case_review": assessments[flag["finding_id"]]}
        if flag.get("finding_id") in assessments else flag
        for flag in risk_flags
    ]


def _evidence_packet(item: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "id": f"evidence:{item.get('tool') or 'item'}:{index}",
        "tool": item.get("tool"),
        "source": item.get("source"),
        "description": item.get("description"),
        "relevance_tags": item.get("relevance_tags"),
        "data": _compact(item.get("data")),
    }


def _evidence_index_item(item: dict[str, Any], index: int) -> dict[str, Any]:
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    sources = data.get("sources") if isinstance(data.get("sources"), list) else []
    return {
        "id": f"evidence:{item.get('tool') or 'item'}:{index}",
        "tool": item.get("tool"),
        "description": item.get("description"),
        "urls": [source.get("url") for source in sources if isinstance(source, dict) and source.get("url")],
    }


def _compact(value: Any, *, depth: int = 0) -> Any:
    """Bound prompt size while retaining the structured evidence needed for review."""
    if depth >= 4:
        return "[truncated]"
    if isinstance(value, dict):
        return {str(key): _compact(item, depth=depth + 1) for key, item in list(value.items())[:30]}
    if isinstance(value, list):
        return [_compact(item, depth=depth + 1) for item in value[:20]]
    if isinstance(value, str):
        return value[:1_500]
    return value
