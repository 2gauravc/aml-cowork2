from evaluations.risk_rating import extract_risk_rating, risk_rating_exact_match


def test_extract_risk_rating_ignores_other_assessments() -> None:
    outputs = {
        "assessments": [
            {"assessment_type": "cdd_completeness", "outcome": "clear"},
            {"assessment_type": "risk_rating", "rating": "High"},
        ]
    }

    assert extract_risk_rating(outputs) == "high"


def test_risk_rating_exact_match_compares_to_dataset_reference() -> None:
    result = risk_rating_exact_match(
        {"assessments": [{"assessment_type": "risk_rating", "rating": "medium"}]},
        {"risk_rating": "MEDIUM"},
    )

    assert result["key"] == "risk_rating_exact_match"
    assert result["score"] is True


def test_risk_rating_exact_match_reports_a_missing_rating() -> None:
    result = risk_rating_exact_match({"assessments": []}, {"risk_rating": "low"})

    assert result["score"] is False
    assert "actual=None" in result["comment"]
