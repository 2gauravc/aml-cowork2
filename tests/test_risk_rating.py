from src.agents.nodes import assess_risk_rating
from src.tools.risk_rating import load_risk_rating_definition


def _state() -> dict:
    return {
        "findings": [],
        "assessments": [
            {"assessment_id": "assessment:adverse", "assessment_type": "adverse_news", "outcome": "completed_no_material_findings", "created_at": "2026-01-01T00:00:00Z", "source_evidence_ids": []},
            {"assessment_id": "assessment:shell", "assessment_type": "shell_company_risk", "factor_id": "low_paid_up_capital", "outcome": "not_triggered", "created_at": "2026-01-01T00:00:00Z", "source_evidence_ids": []},
            {"assessment_id": "assessment:industry", "assessment_type": "other_risk_factors", "factor_id": "high_risk_industry", "outcome": "not_triggered", "created_at": "2026-01-01T00:00:00Z", "source_evidence_ids": []},
            {"assessment_id": "assessment:aml-jurisdiction", "assessment_type": "other_risk_factors", "factor_id": "high_aml_risk_jurisdiction_link", "outcome": "not_triggered", "created_at": "2026-01-01T00:00:00Z", "source_evidence_ids": []},
            {"assessment_id": "assessment:tax-jurisdiction", "assessment_type": "other_risk_factors", "factor_id": "high_tax_risk_jurisdiction_link", "outcome": "not_triggered", "created_at": "2026-01-01T00:00:00Z", "source_evidence_ids": []},
        ],
        "evidence": [],
    }


def _assessment(state: dict) -> dict:
    result = assess_risk_rating(state)
    assert result["findings"] == []
    return result["assessments"][0]


def test_risk_rating_is_low_when_no_scored_factor_is_triggered() -> None:
    assessment = _assessment(_state())

    assert assessment["rating"] == "low"
    assert assessment["total_score"] == 0
    assert assessment["contributing_factors"] == []
    assert "score is 0" in assessment["rule_explanation"]
    assert assessment["provenance"] == {"method": "deterministic_rule_based"}


def test_risk_rating_is_high_at_four_points() -> None:
    state = _state()
    state["findings"] = [{"finding_id": "finding:adverse", "category": "adverse_news", "relevant_evidence_ids": []}]
    state["assessments"][2]["outcome"] = "triggered"

    assessment = _assessment(state)

    assert assessment["rating"] == "high"
    assert assessment["total_score"] == 4
    assert [item["factor_id"] for item in assessment["contributing_factors"]] == ["material_adverse_news", "high_risk_industry"]
    assert "total score 4" in assessment["rule_explanation"]


def test_multiple_shell_criteria_are_capped_at_two_points() -> None:
    state = _state()
    state["assessments"][1]["outcome"] = "triggered"
    state["assessments"].append({"assessment_id": "assessment:shell-address", "assessment_type": "shell_company_risk", "factor_id": "csp_address", "outcome": "triggered", "created_at": "2026-01-01T00:00:01Z", "source_evidence_ids": []})

    assessment = _assessment(state)

    assert assessment["rating"] == "moderate"
    assert assessment["total_score"] == 2
    assert assessment["contributing_factors"] == [{"factor_id": "shell_company_risk", "label": "Shell Company Risk", "points": 2}]


def test_jurisdiction_factors_are_moderate_and_can_be_combined() -> None:
    state = _state()
    state["assessments"][3]["outcome"] = "triggered"
    state["assessments"][4]["outcome"] = "triggered"

    assessment = _assessment(state)

    assert assessment["rating"] == "moderate"
    assert assessment["total_score"] == 2


def test_risk_rating_is_inconclusive_when_a_required_assessment_is_missing_or_unavailable() -> None:
    state = _state()
    state["assessments"] = [item for item in state["assessments"] if item.get("factor_id") != "high_tax_risk_jurisdiction_link"]

    assessment = _assessment(state)

    assert assessment["rating"] == "inconclusive"
    assert "High tax-risk jurisdiction link" in assessment["rule_explanation"]


def test_risk_rating_policy_is_deterministic() -> None:
    definition = load_risk_rating_definition()

    assert definition["ratings"] == ["high", "moderate", "low", "inconclusive"]
    assert definition["factor_scores"]["shell_company_risk"] == 2
    assert definition["thresholds"] == {"high": 4, "moderate": 1}
