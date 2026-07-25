"""Canonical case-status helpers shared by the pipeline, API, and chat."""

from __future__ import annotations

from typing import Any, Literal


GenerationStatus = Literal["not_started", "in_progress", "completed", "incomplete", "failed"]
def build_case_status(generation: GenerationStatus) -> dict[str, Any]:
    """Build the API/UI projection of CDD generation status."""
    return {"cdd_generation": generation}


def sync_case_status(
    container: dict[str, Any],
    *,
    generation: GenerationStatus | None = None,
) -> dict[str, Any]:
    """Refresh a state/session case-status object."""
    current = container.get("case_status") or {}
    resolved_generation = generation or current.get("cdd_generation") or "not_started"
    status = build_case_status(resolved_generation)
    container["case_status"] = status
    return status
