"""Tests for the operator-only CDD state bulk migration wrapper."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.utils.bulk_cdd_state_migration import (
    CDDStateValidationError,
    run_bulk_migration,
    validate_completed_cdd_state,
)


CONFIG = {"bucket": "test-bucket", "prefix": "cdd-states", "region": None}


def _snapshot() -> dict:
    return {
        "schema_version": 1,
        "identity": {"customer_name": "Example Ltd", "jurisdiction": "GB"},
        "graph_state": {"evidence": [], "assessments": [], "findings": [], "documents": []},
    }


def _run(*, migration, apply=False, backup_prefix=None, put=None):
    client = MagicMock()
    client.get_bucket_versioning.return_value = {"Status": "Enabled"}
    with patch("src.utils.bulk_cdd_state_migration.completed_state_store_config", return_value=CONFIG), patch(
        "src.utils.bulk_cdd_state_migration.has_resolved_credentials", return_value=True
    ), patch("src.utils.bulk_cdd_state_migration.completed_state_s3_client", return_value=client), patch(
        "src.utils.bulk_cdd_state_migration.list_completed_state_keys", return_value=["cdd-states/GB/example/completed.json"]
    ), patch("src.utils.bulk_cdd_state_migration.get_completed_state_by_key", return_value=_snapshot()), patch(
        "src.utils.bulk_cdd_state_migration.migrate_completed_cdd_state", side_effect=migration
    ), patch("src.utils.bulk_cdd_state_migration.put_completed_state_by_key", side_effect=put) as write:
        report = run_bulk_migration(apply=apply, backup_prefix=backup_prefix)
    return report, client, write


def test_dry_run_reports_a_valid_change_without_writing() -> None:
    def migration(state):
        state["documents"].append({"document_id": "document:legacy"})
        return {"changed": True, "routines": {"document_state": True}}

    report, _, write = _run(migration=migration)

    assert report["totals"] == {"migrated": 1}
    assert report["records"][0]["written"] is False
    assert "dry run" in report["records"][0]["reason"]
    write.assert_not_called()


def test_apply_writes_only_changed_validated_state_and_can_backup() -> None:
    def migration(state):
        state["documents"].append({"document_id": "document:legacy"})
        return {"changed": True, "routines": {"document_state": True}}

    report, client, write = _run(migration=migration, apply=True, backup_prefix="cdd-backups/run-1")

    assert report["records"][0]["written"] is True
    write.assert_called_once()
    assert client.copy_object.call_args.kwargs["Key"] == "cdd-backups/run-1/cdd-states/GB/example/completed.json"


def test_idempotent_second_run_is_reported_unchanged() -> None:
    report, _, write = _run(
        migration=lambda state: {"changed": False, "routines": {"document_state": False}}, apply=True
    )

    assert report["totals"] == {"unchanged": 1}
    write.assert_not_called()


def test_validation_failure_isolated_without_write() -> None:
    def migration(state):
        state["findings"] = [{"assessment_id": "missing", "relevant_evidence_ids": []}]
        return {"changed": True, "routines": {"csp_address": True}}

    report, _, write = _run(migration=migration, apply=True)

    assert report["totals"] == {"validation_failed": 1}
    write.assert_not_called()


def test_write_failure_is_reported_per_object() -> None:
    report, _, _ = _run(
        migration=lambda state: {"changed": True, "routines": {"document_state": True}},
        apply=True,
        put=RuntimeError("S3 unavailable"),
    )

    assert report["totals"] == {"write_failed": 1}
    assert "S3 unavailable" in report["records"][0]["reason"]


def test_validator_enforces_assessment_and_finding_lineage() -> None:
    with pytest.raises(CDDStateValidationError, match="subset"):
        validate_completed_cdd_state(
            {
                "evidence": [{"evidence_id": "e-1"}, {"evidence_id": "e-2"}],
                "assessments": [{"assessment_id": "a-1", "source_evidence_ids": ["e-1"]}],
                "findings": [{"assessment_id": "a-1", "relevant_evidence_ids": ["e-2"]}],
            }
        )
