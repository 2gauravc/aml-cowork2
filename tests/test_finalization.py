from src.agents.nodes import finalize_cdd


def test_finalization_only_records_completion_timestamp() -> None:
    result = finalize_cdd({"cdd": {"ownership_and_control": {"status": "incomplete"}}, "risk_flags": [{"evaluation": "yes"}]})
    assert result["cdd"]["completed_at"]
    assert "case_status" not in result
