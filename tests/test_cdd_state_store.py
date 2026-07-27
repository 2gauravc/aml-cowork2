"""Tests for completed CDD state S3 persistence."""

from __future__ import annotations

from io import BytesIO
import json
from unittest.mock import MagicMock, patch

from src.utils.cdd_state_store import get_completed_state, save_completed_state


def test_completed_state_round_trips_through_s3() -> None:
    client = MagicMock()
    state = {
        "metadata": {"kyc_case": {"case_id": 42}},
        "cdd": {"completed_at": "2026-07-27T00:00:00+00:00"},
        "evidence": [{"evidence_id": "e-1"}],
    }
    with patch.dict("os.environ", {"CDD_STATE_S3_BUCKET": "test-bucket"}, clear=False), patch(
        "boto3.client", return_value=client
    ):
        saved = save_completed_state(
            state, customer_name="Example Ltd", jurisdiction="gb", case_id=None
        )
        payload = json.loads(client.put_object.call_args.kwargs["Body"].decode("utf-8"))
        client.get_object.return_value = {"Body": BytesIO(json.dumps(payload).encode("utf-8"))}
        restored = get_completed_state(customer_name="Example Ltd", jurisdiction="GB")

    assert saved["identity"]["case_id"] == "42"
    assert client.put_object.call_args.kwargs["Key"] == "cdd-states/GB/example-ltd/completed.json"
    assert restored["graph_state"] == state


def test_state_store_is_disabled_without_an_s3_bucket() -> None:
    with patch.dict("os.environ", {"CDD_STATE_S3_BUCKET": "", "KYC_CACHE_S3_BUCKET": ""}, clear=False):
        assert save_completed_state({}, customer_name="Example Ltd", jurisdiction="GB", case_id=None) is None
        assert get_completed_state(customer_name="Example Ltd", jurisdiction="GB") is None


def test_state_store_defaults_to_the_configured_kyc_cache_bucket() -> None:
    with patch.dict("os.environ", {"CDD_STATE_S3_BUCKET": "", "KYC_CACHE_S3_BUCKET": "cache-bucket"}, clear=False):
        with patch("boto3.client") as client:
            save_completed_state({}, customer_name="Example Ltd", jurisdiction="GB", case_id=None)

    assert client.return_value.put_object.call_args.kwargs["Bucket"] == "cache-bucket"
