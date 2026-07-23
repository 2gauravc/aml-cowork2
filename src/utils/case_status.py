"""Canonical case-status helpers shared by the pipeline, API, and chat."""

from __future__ import annotations

import re
from typing import Any, Literal


GenerationStatus = Literal["not_started", "in_progress", "completed", "failed"]
_EVALUATION_PATTERN = re.compile(r"Evaluation:\s*(Yes|No|Inconclusive)", re.IGNORECASE)


def risk_flag_evaluation(flag: dict[str, Any]) -> str:
    """Return the normalized evaluation recorded for one risk flag."""
    assessment = (flag.get("evidence") or {}).get("assessment") or {}
    value = assessment.get("is_csp") or _EVALUATION_PATTERN.search(str(flag.get("description") or ""))
    if hasattr(value, "group"):
        value = value.group(1)
    return str(value or "inconclusive").casefold()


def build_case_status(
    generation: GenerationStatus,
    risk_flags: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Build the API/UI status projection from detailed risk-flag evidence."""
    return {
        "cdd_generation": generation,
        "risk_flags_present": sum(
            risk_flag_evaluation(flag) == "yes" for flag in (risk_flags or [])
        ),
    }


def sync_case_status(
    container: dict[str, Any],
    *,
    generation: GenerationStatus | None = None,
) -> dict[str, Any]:
    """Refresh a state/session case_status object from its detailed risk flags."""
    current = container.get("case_status") or {}
    resolved_generation = generation or current.get("cdd_generation") or "not_started"
    status = build_case_status(resolved_generation, container.get("risk_flags"))
    container["case_status"] = status
    return status
