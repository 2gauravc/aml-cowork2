"""Application environment loading with AWS credential safeguards."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values


PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATIC_AWS_CREDENTIAL_KEYS = frozenset(
    {
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
    }
)


def load_application_env(path: Path | None = None) -> None:
    """Load settings from ``.env`` without loading static AWS credentials.

    Static credentials may still be supplied by the process environment for a
    local AWS toolchain. They are intentionally ignored in project ``.env``
    files so application configuration does not become a store for AWS secrets.
    """
    values = dotenv_values(path or PROJECT_ROOT / ".env")
    for key, value in values.items():
        if key in STATIC_AWS_CREDENTIAL_KEYS or value is None:
            continue
        os.environ.setdefault(key, value)
