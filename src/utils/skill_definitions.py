"""Shared loading and identity helpers for structured project skill definitions."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any

import yaml


class SkillDefinitionError(RuntimeError):
    """Raised when a skill definition is missing or malformed."""


def load_skill_definition(skill_path: str | Path, filename: str = "definition.yaml") -> tuple[dict[str, Any], str, str]:
    """Load a named sibling YAML contract and return its stable content hash."""
    definition_path = Path(skill_path).with_name(filename)
    try:
        raw = definition_path.read_bytes()
        value = yaml.safe_load(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise SkillDefinitionError(f"Skill definition could not be loaded: {exc}") from exc
    if not isinstance(value, dict):
        raise SkillDefinitionError("Skill definition must contain a YAML object")
    return value, str(definition_path), sha256(raw).hexdigest()
