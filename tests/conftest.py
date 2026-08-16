"""Test import path setup."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


@pytest.fixture(autouse=True)
def disable_external_langsmith_tracing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never submit application traces to the configured LangSmith project."""
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
