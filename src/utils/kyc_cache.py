"""Small persistent cache for sandbox KYC API responses."""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CACHE_PATH = PROJECT_ROOT / "outputs" / "cache" / "kyc_api_cache.json"

_LOCK = threading.Lock()


def get_cache_value(namespace: str, parts: list[str | int]) -> Any | None:
    """Return a cached value, or None when the key has not been stored."""
    key = cache_key(namespace, parts)
    with _LOCK:
        data = _read_cache()
        return data.get(key)


def set_cache_value(namespace: str, parts: list[str | int], value: Any) -> Any:
    """Persist a cache value with no expiry and return the stored value."""
    key = cache_key(namespace, parts)
    with _LOCK:
        data = _read_cache()
        data[key] = value
        _write_cache(data)
    return value


def cache_key(namespace: str, parts: list[str | int]) -> str:
    normalized_parts = [_normalize_part(str(part)) for part in parts]
    return ":".join([namespace, *normalized_parts])


def _cache_path() -> Path:
    configured = os.getenv("KYC_CACHE_PATH")
    return Path(configured) if configured else DEFAULT_CACHE_PATH


def _read_cache() -> dict[str, Any]:
    path = _cache_path()
    if not path.exists():
        return {}

    with path.open(encoding="utf-8") as fh:
        try:
            data = json.load(fh)
        except json.JSONDecodeError:
            return {}

    return data if isinstance(data, dict) else {}


def _write_cache(data: dict[str, Any]) -> None:
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
    ) as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
        fh.write("\n")
        temp_name = fh.name

    Path(temp_name).replace(path)


def _normalize_part(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    return normalized.strip("-") or "empty"
