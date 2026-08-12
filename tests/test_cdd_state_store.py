"""Tests for completed CDD state S3 persistence."""

from __future__ import annotations

from datetime import date
from io import BytesIO
import json
from unittest.mock import MagicMock, patch

from src.utils.cdd_state_store import (
    get_completed_state,
    list_completed_state_keys,
    save_completed_state,
)


def test_completed_state_round_trips_through_s3() -> None:
    client = MagicMock()
    state = {
        "metadata": {"kyc_case": {"case_id": 42}},
        "cdd": {"completed_at": "2026-07-27T00:00:00+00:00"},
        "evidence": [{"evidence_id": "e-1"}],
        "source_date": date(2026, 7, 28),
    }
    with patch.dict("os.environ", {"CDD_STATE_S3_BUCKET": "test-bucket"}, clear=False), patch(
        "src.utils.cdd_state_store.has_resolved_credentials", return_value=True
    ), patch("src.utils.cdd_state_store.s3_client", return_value=client):
        saved = save_completed_state(
            state, customer_name="Example Ltd", jurisdiction="gb", case_id=None
        )
        payload = json.loads(client.put_object.call_args.kwargs["Body"].decode("utf-8"))
        client.get_object.return_value = {"Body": BytesIO(json.dumps(payload).encode("utf-8"))}
        restored = get_completed_state(customer_name="Example Ltd", jurisdiction="GB")

    assert saved["identity"]["case_id"] == "42"
    assert client.put_object.call_args.kwargs["Key"] == "cdd-states/GB/example-ltd/completed.json"
    assert restored["graph_state"]["metadata"] == state["metadata"]
    assert restored["graph_state"]["cdd"] == state["cdd"]
    assert restored["graph_state"]["evidence"] == state["evidence"]
    assert restored["graph_state"]["source_date"] == "2026-07-28"


def test_state_store_is_disabled_without_an_s3_bucket() -> None:
    with patch.dict("os.environ", {"CDD_STATE_S3_BUCKET": "", "KYC_CACHE_S3_BUCKET": ""}, clear=False):
        assert save_completed_state({}, customer_name="Example Ltd", jurisdiction="GB", case_id=None) is None
        assert get_completed_state(customer_name="Example Ltd", jurisdiction="GB") is None


def test_state_store_is_disabled_without_resolved_credentials() -> None:
    with patch.dict("os.environ", {"CDD_STATE_S3_BUCKET": "state-bucket"}, clear=False), patch(
        "src.utils.cdd_state_store.has_resolved_credentials", return_value=False
    ), patch("src.utils.cdd_state_store.s3_client") as client:
        assert save_completed_state({}, customer_name="Example Ltd", jurisdiction="GB", case_id=None) is None
        assert get_completed_state(customer_name="Example Ltd", jurisdiction="GB") is None

    client.assert_not_called()


def test_state_store_defaults_to_the_configured_kyc_cache_bucket() -> None:
    with patch.dict("os.environ", {"CDD_STATE_S3_BUCKET": "", "KYC_CACHE_S3_BUCKET": "cache-bucket"}, clear=False):
        with patch("src.utils.cdd_state_store.has_resolved_credentials", return_value=True), patch(
            "src.utils.cdd_state_store.s3_client"
        ) as client:
            save_completed_state({}, customer_name="Example Ltd", jurisdiction="GB", case_id=None)

    assert client.return_value.put_object.call_args.kwargs["Bucket"] == "cache-bucket"


def test_listing_completed_states_paginates_and_honours_a_limit() -> None:
    client = MagicMock()
    client.get_paginator.return_value.paginate.return_value = [
        {"Contents": [{"Key": "cdd-states/GB/one/completed.json"}]},
        {"Contents": [{"Key": "cdd-states/GB/two/completed.json"}, {"Key": "cdd-states/GB/two/notes.json"}]},
    ]
    config = {"bucket": "state-bucket", "prefix": "cdd-states", "region": None}
    with patch("src.utils.cdd_state_store.s3_client", return_value=client):
        keys = list_completed_state_keys(config=config, prefix="cdd-states/GB", max_keys=2)

    assert keys == ["cdd-states/GB/one/completed.json", "cdd-states/GB/two/completed.json"]
