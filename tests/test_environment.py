"""Tests for safe project environment loading."""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from src.utils.environment import load_application_env


def test_project_env_does_not_load_static_aws_credentials() -> None:
    with TemporaryDirectory() as temporary_directory:
        env_file = Path(temporary_directory) / ".env"
        env_file.write_text(
            "OPENAI_API_KEY=project-key\nAWS_ACCESS_KEY_ID=from-dotenv\n"
            "AWS_SECRET_ACCESS_KEY=secret-from-dotenv\nAWS_SESSION_TOKEN=token-from-dotenv\n",
            encoding="utf-8",
        )
        with patch.dict(os.environ, {}, clear=True):
            load_application_env(env_file)

            assert os.environ["OPENAI_API_KEY"] == "project-key"
            assert "AWS_ACCESS_KEY_ID" not in os.environ
            assert "AWS_SECRET_ACCESS_KEY" not in os.environ
            assert "AWS_SESSION_TOKEN" not in os.environ


def test_process_credentials_are_not_overridden_by_project_env() -> None:
    with TemporaryDirectory() as temporary_directory:
        env_file = Path(temporary_directory) / ".env"
        env_file.write_text("AWS_ACCESS_KEY_ID=from-dotenv\n", encoding="utf-8")
        with patch.dict(os.environ, {"AWS_ACCESS_KEY_ID": "from-process"}, clear=True):
            load_application_env(env_file)

            assert os.environ["AWS_ACCESS_KEY_ID"] == "from-process"
