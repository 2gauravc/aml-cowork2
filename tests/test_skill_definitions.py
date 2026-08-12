from pathlib import Path

import pytest

from src.utils.skill_definitions import SkillDefinitionError, load_skill_definition


PROJECT_ROOT = Path(__file__).parents[1]
ACTIVE_SKILLS = {
    "adverse-news-screening", "case-checker", "cdd-completeness", "csp-detector",
    "digital-footprint", "evidence-quality", "other-risk-factors", "risk-rating",
    "shell-company-risk",
}


def test_active_skills_keep_markdown_guidance_separate_from_definitions() -> None:
    for name in ACTIVE_SKILLS:
        skill_path = PROJECT_ROOT / "skills" / name / "SKILL.md"
        filename = (
            "contract.yaml"
            if skill_path.with_name("contract.yaml").exists()
            else "definition.yaml"
        )
        definition, definition_path, version = load_skill_definition(skill_path, filename)
        assert definition["name"] == name
        assert Path(definition_path).name == filename
        assert len(version) == 64
        assert not skill_path.read_text(encoding="utf-8").lstrip().startswith("---")


def test_missing_definition_has_a_typed_error(tmp_path: Path) -> None:
    skill_path = tmp_path / "SKILL.md"
    skill_path.write_text("# Test skill\n", encoding="utf-8")
    with pytest.raises(SkillDefinitionError, match="could not be loaded"):
        load_skill_definition(skill_path)
