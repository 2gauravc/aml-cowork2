"""Optional JSONL debug logging for LangGraph node execution."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DEBUG_DIR = PROJECT_ROOT / "outputs" / "debug"
MAX_VALUE_CHARS = int(os.getenv("CDD_DEBUG_MAX_VALUE_CHARS", "10000"))

NODE_FUNCTIONS = {
    "collect_required_inputs": [],
    "create_or_reuse_case": ["create_company_case"],
    "fetch_customer_static": ["_fetch_customer_static"],
    "fetch_org_chart": ["_fetch_company_org_chart"],
    "fetch_members": ["_fetch_company_members"],
    "build_company_business_profile": ["_latest_evidence_data"],
    "generate_registry_document": ["generate_registry_document"],
    "extract_registry_document": ["classify_document", "extract_document"],
    "enrich_cdd_from_registry_document": [
        "missing_about_customer_fields",
        "apply_document_extract_to_cdd",
    ],
    "build_ownership_and_control": ["_latest_evidence_data", "build_ownership_tables"],
    "evaluate_risk_flags": [],
    "finalize_cdd": [],
}

SECRET_MARKERS = (
    "api_key",
    "apikey",
    "secret",
    "token",
    "authorization",
    "password",
    "client_secret",
)


def maybe_debug_node(node_name: str, func: Callable[[dict[str, Any]], dict[str, Any]]):
    """Return a debug-wrapped node function when CDD_DEBUG is enabled."""
    if not _debug_enabled():
        return func
    return debug_node(node_name, func)


def debug_node(node_name: str, func: Callable[[dict[str, Any]], dict[str, Any]]):
    """Wrap a LangGraph node and append one JSONL debug entry per call."""

    def wrapped(state: dict[str, Any]) -> dict[str, Any]:
        incoming = _sanitize(state)
        started_at = datetime.now(UTC).isoformat()
        try:
            result = func(state)
        except Exception as exc:
            _write_entry(
                {
                    "timestamp": started_at,
                    "node": node_name,
                    "tools_or_functions": NODE_FUNCTIONS.get(node_name, []),
                    "incoming_state": incoming,
                    "outgoing_update": None,
                    "state_diff": None,
                    "error": {
                        "type": exc.__class__.__name__,
                        "message": str(exc),
                    },
                }
            )
            raise

        outgoing_update = _sanitize(result)
        _write_entry(
            {
                "timestamp": started_at,
                "node": node_name,
                "tools_or_functions": NODE_FUNCTIONS.get(node_name, []),
                "incoming_state": incoming,
                "outgoing_update": outgoing_update,
                "state_diff": _diff(incoming, outgoing_update),
                "error": None,
            }
        )
        return result

    wrapped.__name__ = getattr(func, "__name__", node_name)
    wrapped.__doc__ = getattr(func, "__doc__", None)
    return wrapped


def debug_log_path() -> Path:
    """Return the active debug log path, creating one if needed."""
    existing = os.getenv("CDD_DEBUG_FILE")
    if existing:
        return Path(existing)

    debug_dir = Path(os.getenv("CDD_DEBUG_DIR", str(DEFAULT_DEBUG_DIR)))
    debug_dir.mkdir(parents=True, exist_ok=True)
    path = debug_dir / f"cdd-debug-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.jsonl"
    os.environ["CDD_DEBUG_FILE"] = str(path)
    return path


def _debug_enabled() -> bool:
    return os.getenv("CDD_DEBUG", "").strip().casefold() in {"1", "true", "yes", "y", "on"}


def _write_entry(entry: dict[str, Any]) -> None:
    path = debug_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False, default=str))
        fh.write("\n")


def _sanitize(value: Any, *, key: str | None = None) -> Any:
    if key and _is_secret_key(key):
        return "[REDACTED]"

    if isinstance(value, dict):
        return {str(k): _sanitize(v, key=str(k)) for k, v in value.items()}

    if isinstance(value, list):
        return [_sanitize(item) for item in value]

    if isinstance(value, tuple):
        return [_sanitize(item) for item in value]

    if hasattr(value, "content") and value.__class__.__name__.endswith("Message"):
        return {
            "type": value.__class__.__name__,
            "content": _truncate(str(getattr(value, "content", ""))),
        }

    if isinstance(value, str):
        return _truncate(value)

    try:
        copied = deepcopy(value)
    except Exception:
        copied = str(value)
    return copied


def _is_secret_key(key: str) -> bool:
    lowered = key.casefold()
    return any(marker in lowered for marker in SECRET_MARKERS)


def _truncate(text: str) -> str:
    if len(text) <= MAX_VALUE_CHARS:
        return text
    return text[:MAX_VALUE_CHARS] + "...[truncated]"


def _diff(incoming_state: dict[str, Any], outgoing_update: dict[str, Any]) -> dict[str, Any]:
    diff = {}
    for key, new_value in outgoing_update.items():
        old_value = incoming_state.get(key)
        if old_value != new_value:
            diff[key] = {
                "before": old_value,
                "after": new_value,
            }
    return diff
