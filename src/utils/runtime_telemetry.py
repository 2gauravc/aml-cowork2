"""Shared runtime telemetry for CDD graph nodes and model calls.

Telemetry is operational data. It is intentionally kept outside evidence,
assessments, and findings, and contains no prompts or provider responses.
"""

from __future__ import annotations

from contextvars import ContextVar
from copy import deepcopy
from datetime import UTC, datetime
from time import perf_counter
from typing import Any, Callable
from uuid import uuid4


_ACTIVE_USAGE: ContextVar[dict[str, Any] | None] = ContextVar("cdd_active_usage", default=None)


def run_node_with_telemetry(
    node_name: str, func: Callable[[dict[str, Any]], dict[str, Any]]
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Wrap a graph node and append one versioned timing/usage record."""
    def wrapped(state: dict[str, Any]) -> dict[str, Any]:
        trace = deepcopy(state.get("runtime_telemetry") or _new_trace())
        started_at, started = datetime.now(UTC).isoformat(), perf_counter()
        usage: dict[str, Any] = {"calls": 0, "input": 0, "output": 0, "cached": 0, "total": 0, "available": False}
        token = _ACTIVE_USAGE.set(usage)
        try:
            result = func(state)
            status = "unavailable" if _unavailable_result(result) else "completed"
        except Exception as exc:
            result = None
            status = "failed"
            error = str(exc)
        finally:
            _ACTIVE_USAGE.reset(token)
        entry: dict[str, Any] = {
            "node": node_name,
            "status": status,
            "started_at": started_at,
            "finished_at": datetime.now(UTC).isoformat(),
            "elapsed_ms": round((perf_counter() - started) * 1000),
            "tokens": _tokens_view(usage),
        }
        if status == "failed":
            entry["error"] = error
        trace["nodes"] = [*trace.get("nodes", []), entry]
        trace["finished_at"] = entry["finished_at"]
        if status == "failed":
            raise RuntimeError(error)
        return {**(result or {}), "runtime_telemetry": trace}

    wrapped.__name__ = getattr(func, "__name__", node_name)
    return wrapped


def invoke_model_with_telemetry(client: Any, **request: Any) -> Any:
    """Make one Responses API request and attribute provider usage to its node."""
    response = client.responses.create(**request)
    usage = _ACTIVE_USAGE.get()
    if usage is not None:
        _record_usage(usage, getattr(response, "usage", None))
    return response


def telemetry_view(trace: dict[str, Any] | None) -> dict[str, Any]:
    """Return a stable UI/API projection, including legacy-state fallback."""
    if not isinstance(trace, dict) or trace.get("schema_version") != "runtime_telemetry/v1":
        return {"status": "not_retained", "nodes": []}
    return {
        "status": "available",
        "run_id": trace.get("run_id"),
        "started_at": trace.get("started_at"),
        "finished_at": trace.get("finished_at"),
        "nodes": [
            {key: item.get(key) for key in ("node", "status", "elapsed_ms", "tokens", "started_at", "finished_at", "error") if key in item}
            for item in trace.get("nodes", []) if isinstance(item, dict)
        ],
    }


def _new_trace() -> dict[str, Any]:
    return {"schema_version": "runtime_telemetry/v1", "run_id": f"run:telemetry:{uuid4().hex}", "started_at": datetime.now(UTC).isoformat(), "nodes": []}


def _record_usage(target: dict[str, Any], usage: Any) -> None:
    values = usage if isinstance(usage, dict) else getattr(usage, "__dict__", {})
    if not isinstance(values, dict):
        return
    input_tokens = _number(values.get("input_tokens"))
    output_tokens = _number(values.get("output_tokens"))
    total_tokens = _number(values.get("total_tokens"))
    details = values.get("input_tokens_details") or getattr(usage, "input_tokens_details", None) or {}
    cached_tokens = _number((details.get("cached_tokens") if isinstance(details, dict) else getattr(details, "cached_tokens", None)))
    if all(value is None for value in (input_tokens, output_tokens, total_tokens, cached_tokens)):
        return
    target["available"] = True
    target["calls"] += 1
    target["input"] += input_tokens or 0
    target["output"] += output_tokens or 0
    target["cached"] += cached_tokens or 0
    target["total"] += total_tokens if total_tokens is not None else (input_tokens or 0) + (output_tokens or 0)


def _number(value: Any) -> int | None:
    return value if isinstance(value, int) and value >= 0 else None


def _tokens_view(usage: dict[str, Any]) -> dict[str, Any]:
    if not usage["available"]:
        return {"status": "not_applicable"}
    return {"status": "available", "calls": usage["calls"], "input": usage["input"], "output": usage["output"], "cached": usage["cached"], "total": usage["total"]}


def _unavailable_result(result: dict[str, Any]) -> bool:
    assessments = result.get("assessments") if isinstance(result, dict) else None
    # Some LangGraph nodes intentionally use ``Overwrite(list)`` to bypass a
    # reducer. Telemetry observes the update but must not iterate that wrapper.
    assessments = getattr(assessments, "value", assessments)
    return bool(assessments) and all(item.get("outcome") == "unavailable" for item in assessments if isinstance(item, dict))
