"""Runtime telemetry remains separate from CDD evidence and assessments."""

from types import SimpleNamespace

from langgraph.types import Overwrite

from src.utils.runtime_telemetry import (
    invoke_model_with_telemetry,
    run_node_with_telemetry,
    telemetry_view,
)


def test_non_llm_node_records_timing_and_not_applicable_tokens() -> None:
    result = run_node_with_telemetry("fetch_members", lambda state: {"cdd": {}})({})

    entry = result["runtime_telemetry"]["nodes"][0]
    assert entry["node"] == "fetch_members"
    assert entry["status"] == "completed"
    assert entry["elapsed_ms"] >= 0
    assert entry["tokens"] == {"status": "not_applicable"}


def test_llm_node_aggregates_provider_usage_through_the_shared_helper() -> None:
    response = SimpleNamespace(
        usage=SimpleNamespace(
            input_tokens=12,
            output_tokens=3,
            total_tokens=15,
            input_tokens_details=SimpleNamespace(cached_tokens=4),
        )
    )
    client = SimpleNamespace(responses=SimpleNamespace(create=lambda **request: response))

    def node(state):
        invoke_model_with_telemetry(client, model="test", input=[])
        return {"assessments": [{"outcome": "completed_no_material_findings"}]}

    result = run_node_with_telemetry("adverse_news_screening", node)({})
    tokens = result["runtime_telemetry"]["nodes"][0]["tokens"]

    assert tokens == {"status": "available", "calls": 1, "input": 12, "output": 3, "cached": 4, "total": 15}


def test_unavailable_node_and_legacy_view_are_explicit() -> None:
    result = run_node_with_telemetry(
        "assess_csp_address", lambda state: {"assessments": [{"outcome": "unavailable"}]}
    )({})

    assert result["runtime_telemetry"]["nodes"][0]["status"] == "unavailable"
    assert telemetry_view(None) == {"status": "not_retained", "nodes": []}


def test_node_with_langgraph_overwrite_update_is_recorded() -> None:
    result = run_node_with_telemetry(
        "assess_csp_address", lambda state: {"assessments": Overwrite([])}
    )({})

    assert result["assessments"].value == []
    assert result["runtime_telemetry"]["nodes"][0]["status"] == "completed"
