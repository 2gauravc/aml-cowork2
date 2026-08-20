"""Deterministic LangSmith evaluators for the final CDD risk rating.

Dataset examples should store the expected rating as::

    {"outputs": {"risk_rating": "high"}}

The CDD graph returns its final rating inside the assessment whose
``assessment_type`` is ``"risk_rating"``.  Assessment IDs and timestamps are
generated on every execution, so this evaluator deliberately does not compare
the full CDD state.
"""

from __future__ import annotations

from typing import Any, Mapping


def extract_risk_rating(outputs: Mapping[str, Any] | None) -> str | None:
    """Return the final risk rating from a completed CDD graph output."""
    for assessment in (outputs or {}).get("assessments", []):
        if assessment.get("assessment_type") == "risk_rating":
            rating = assessment.get("rating")
            return str(rating).casefold() if rating is not None else None
    return None


def risk_rating_exact_match(
    outputs: dict[str, Any], reference_outputs: dict[str, Any]
) -> dict[str, Any]:
    """Score whether graph output has the dataset's expected risk rating.

    This signature is for ``langsmith.evaluate(..., evaluators=[...])``.
    """
    actual = extract_risk_rating(outputs)
    expected_value = reference_outputs.get("risk_rating")
    expected = str(expected_value).casefold() if expected_value is not None else None

    return {
        "key": "risk_rating_exact_match",
        "score": actual == expected,
        "comment": f"expected={expected!r}, actual={actual!r}",
    }


def _outputs(record: Any) -> dict[str, Any]:
    """Read outputs from either SDK objects or UI evaluator dictionaries."""
    if isinstance(record, Mapping):
        return dict(record.get("outputs") or {})
    return dict(getattr(record, "outputs", None) or {})


def perform_eval(run: Any, example: Any) -> dict[str, Any]:
    """LangSmith UI adapter; evaluate a run against a dataset example."""
    return risk_rating_exact_match(_outputs(run), _outputs(example))
