"""Durable S3 storage for completed CDD state snapshots."""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, date, datetime
from typing import Any


SCHEMA_VERSION = 1
DEFAULT_PREFIX = "cdd-states"


class CDDStateStoreError(RuntimeError):
    pass


def save_completed_state(
    graph_state: dict[str, Any], *, customer_name: str, jurisdiction: str, case_id: str | None
) -> dict[str, Any] | None:
    """Store the final CDD state, returning its lightweight saved-state record.

    Storage is optional in local development: return ``None`` when no S3 bucket
    has been configured instead of preventing a completed CDD run from returning.
    """
    config = _config()
    if config is None:
        return None
    saved_at = datetime.now(UTC).isoformat()
    identity = {
        "customer_name": customer_name,
        "jurisdiction": jurisdiction.strip().upper(),
        "case_id": case_id or _state_case_id(graph_state),
    }
    record = {
        "schema_version": SCHEMA_VERSION,
        "saved_at": saved_at,
        "identity": identity,
        "graph_state": _json_safe(graph_state),
    }
    try:
        _client(config).put_object(
            Bucket=config["bucket"],
            Key=_key(config, identity["jurisdiction"], customer_name),
            Body=json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
            ContentType="application/json",
        )
    except Exception as exc:
        raise CDDStateStoreError(f"Unable to store completed CDD state: {exc}") from exc
    return {"saved_at": saved_at, "identity": identity}


def get_completed_state(*, customer_name: str, jurisdiction: str) -> dict[str, Any] | None:
    """Return one completed state snapshot for a customer/jurisdiction."""
    config = _config()
    if config is None:
        return None
    try:
        response = _client(config).get_object(
            Bucket=config["bucket"], Key=_key(config, jurisdiction, customer_name)
        )
        value = json.loads(response["Body"].read().decode("utf-8"))
    except Exception as exc:
        if _missing(exc):
            return None
        raise CDDStateStoreError(f"Unable to retrieve completed CDD state: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION:
        raise CDDStateStoreError("Stored CDD state has an unsupported schema")
    if not isinstance(value.get("graph_state"), dict) or not isinstance(value.get("identity"), dict):
        raise CDDStateStoreError("Stored CDD state is incomplete")
    return value


def _config() -> dict[str, str | None] | None:
    # Reuse the deployed KYC-cache bucket unless a dedicated state bucket is
    # configured. Both use distinct prefixes, so snapshots never mix with API
    # cache entries.
    bucket = (
        os.getenv("CDD_STATE_S3_BUCKET", "").strip()
        or os.getenv("KYC_CACHE_S3_BUCKET", "").strip()
    )
    if not bucket:
        return None
    return {
        "bucket": bucket,
        "prefix": os.getenv("CDD_STATE_S3_PREFIX", DEFAULT_PREFIX).strip().strip("/") or DEFAULT_PREFIX,
        "region": os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or None,
    }


def _key(config: dict[str, str | None], jurisdiction: str, customer_name: str) -> str:
    return f"{config['prefix']}/{jurisdiction.strip().upper()}/{_slug(customer_name)}/completed.json"


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.strip().casefold()).strip("-") or "unnamed"


def _client(config: dict[str, str | None]) -> Any:
    try:
        import boto3
    except ImportError as exc:
        raise CDDStateStoreError("boto3 is required for CDD state storage") from exc
    return boto3.client("s3", region_name=config["region"])


def _missing(exc: Exception) -> bool:
    response = getattr(exc, "response", {})
    return isinstance(response, dict) and str((response.get("Error") or {}).get("Code")) in {"NoSuchKey", "404", "NotFound"}


def _state_case_id(graph_state: dict[str, Any]) -> str | None:
    value = ((graph_state.get("metadata") or {}).get("kyc_case") or {}).get("case_id")
    return str(value) if value not in (None, "") else None


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "model_dump"):
        return _json_safe(value.model_dump(mode="json"))
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value
