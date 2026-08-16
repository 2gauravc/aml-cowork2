"""Optional LangSmith instrumentation for CDD runtime observability."""

from __future__ import annotations

import os
from typing import Any

from openai import OpenAI


def langsmith_tracing_enabled() -> bool:
    """Only instrument when tracing is explicitly enabled and configured."""
    return (
        os.getenv("LANGSMITH_TRACING", "").strip().casefold() in {"1", "true", "yes", "on"}
        and bool(os.getenv("LANGSMITH_API_KEY", "").strip())
    )


def traced_openai_client(client: Any | None = None) -> Any:
    """Return an OpenAI client with nested LangSmith tracing when enabled."""
    client = client or OpenAI()
    if not langsmith_tracing_enabled():
        return client
    from langsmith.wrappers import wrap_openai

    return wrap_openai(client)
