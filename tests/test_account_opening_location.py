"""Coverage for account opening location in CDD pipeline inputs and state."""

from typing import Literal, cast

import pytest
from pydantic import ValidationError

from src.agents.state import new_cdd_state
from src.backend.app import PipelineRequest


@pytest.mark.parametrize("account_location", ["SG", "HK", "GB"])
def test_account_location_is_retained_in_customer_metadata(account_location: str) -> None:
    state = new_cdd_state(
        customer_name="Example Ltd",
        jurisdiction="GB",
        account_location=cast(Literal["SG", "HK", "GB"], account_location),
    )

    assert state["metadata"]["customer"]["account_location"] == account_location


def test_pipeline_request_requires_an_allowed_account_location() -> None:
    request = PipelineRequest(
        customer_name="Example Ltd",
        jurisdiction="GB",
        account_location="HK",
    )

    assert request.account_location == "HK"
    with pytest.raises(ValidationError):
        PipelineRequest(customer_name="Example Ltd", jurisdiction="GB", account_location="US")
