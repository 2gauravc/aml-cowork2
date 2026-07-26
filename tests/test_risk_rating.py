from unittest.mock import patch

from src.agents.nodes import assess_risk_rating
from src.tools.risk_rating import load_risk_rating_definition


def _state() -> dict:
    return {"findings": [{"finding_id": "finding:one", "category": "shell_company_risk", "title": "Low paid-up capital", "summary": "Capital needs review.", "confidence": {"level": "medium"}, "severity": {"level": "medium"}, "relevant_evidence_ids": ["evidence:one"]}], "assessments": [{"assessment_id": "assessment:shell", "assessment_type": "shell_company_risk", "outcome": "triggered", "summary": "Capital needs review.", "source_evidence_ids": ["evidence:one"]}], "risk_flags": [{"finding_id": "csp_address:category", "category": "csp_address", "evaluation": "no", "severity": "none", "description": "No CSP identified."}], "evidence": [{"evidence_id": "evidence:one", "tool": "shell_company_risk", "source": "Shell Company Risk", "description": "Capital evidence"}]}


def test_risk_rating_creates_one_assessment_without_a_duplicate_finding() -> None:
    classified = {"rating": "moderate", "rationale": "One retained indicator warrants monitoring.", "matched_criteria": ["A limited number of current risk flags warrant ongoing monitoring."], "limitations": [], "monitoring_posture": "Ongoing monitoring proportionate to retained risk."}
    with patch("src.tools.risk_rating.OpenAI") as client:
        client.return_value.responses.create.return_value.output_text = __import__("json").dumps(classified)
        result = assess_risk_rating(_state())
    assert result["findings"] == []
    assert result["assessments"][0]["rating"] == "moderate"
    assert result["assessments"][0]["selected_finding_ids"] == ["finding:one"]
    assert load_risk_rating_definition()["assessment"]["schema"] == "risk_rating_assessment/v1"


def test_risk_rating_policy_does_not_allow_an_inconclusive_rating() -> None:
    assert load_risk_rating_definition()["ratings"] == ["high", "standalone_high", "moderate", "low"]
