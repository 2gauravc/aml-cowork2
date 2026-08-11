import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.tools.csp_detector import (
    CSPAssessmentError,
    _assess_search_results,
    _normalise_source,
    _validate_web_search_evidence,
    load_csp_definition,
)


def _response(payload: dict) -> SimpleNamespace:
    return SimpleNamespace(output_text=json.dumps(payload))


@patch("src.tools.csp_detector.OpenAI")
def test_csp_model_schema_is_complete_and_enforces_evidence_lineage(openai) -> None:
    payload = {
        "assessment": {
            "assessment_id": "assessment:test",
            "source_evidence_ids": ["evidence:test:1"],
            "is_csp": "yes",
            "confidence": "high",
            "explanation": "Direct provider evidence at the exact address.",
            "limitations": [],
        },
        "finding_evidence_ids": ["evidence:test:1"],
        "finding_required": True,
    }
    openai.return_value.responses.create.return_value = _response(payload)
    definition = load_csp_definition()
    result = _assess_search_results(
        "1 Example Street",
        "Example Ltd",
        [{"evidence_id": "evidence:test:1"}],
        definition,
        "assessment:test",
        ["evidence:test:1"],
    )

    schema = openai.return_value.responses.create.call_args.kwargs["text"]["format"][
        "schema"
    ]
    assert set(schema["required"]) == set(schema["properties"])
    assert set(schema["properties"]["assessment"]["required"]) == set(
        schema["properties"]["assessment"]["properties"]
    )
    assert result == payload


@patch("src.tools.csp_detector.OpenAI")
def test_csp_model_cannot_link_a_finding_to_unselected_evidence(openai) -> None:
    payload = {
        "assessment": {
            "assessment_id": "assessment:test",
            "source_evidence_ids": [],
            "is_csp": "no",
            "confidence": "low",
            "explanation": "No relevant source retained.",
            "limitations": [],
        },
        "finding_evidence_ids": ["evidence:test:1"],
        "finding_required": False,
    }
    openai.return_value.responses.create.return_value = _response(payload)
    with pytest.raises(CSPAssessmentError, match="lineage"):
        _assess_search_results(
            "1 Example Street",
            None,
            [{"evidence_id": "evidence:test:1"}],
            load_csp_definition(),
            "assessment:test",
            ["evidence:test:1"],
        )


def test_csp_evidence_is_normalized_and_schema_validated_before_model_use() -> None:
    evidence = _normalise_source(
        {
            "evidence_id": "evidence:test:1",
            "title": "Provider",
            "url": "https://example.test",
            "content": "Registered office services.",
        },
        query="Example address",
        retrieved_at="2026-08-11T00:00:00Z",
    )
    assert evidence["evidence_type"] == "web_search_result"
    assert evidence["source"]["retrieved_at"] == "2026-08-11T00:00:00Z"
    with pytest.raises(CSPAssessmentError, match="Invalid CSP web-search evidence"):
        _validate_web_search_evidence({"evidence_id": "missing-required-fields"})
