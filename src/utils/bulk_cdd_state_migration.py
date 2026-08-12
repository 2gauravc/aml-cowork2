"""Operator-only bulk migration for retained completed CDD snapshots.

The command deliberately contains no artifact migration logic.  It calls the
same entry point used by ``/api/cdd-states/load`` and only provides S3
enumeration, validation, reporting, and guarded persistence around it.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

from src.backend.app import migrate_completed_cdd_state
from src.utils.aws import has_resolved_credentials
from src.utils.cdd_state_store import (
    CDDStateStoreError,
    completed_state_s3_client,
    completed_state_store_config,
    get_completed_state_by_key,
    list_completed_state_keys,
    put_completed_state_by_key,
)
from src.utils.environment import load_application_env
from src.utils.adverse_news_view import adverse_news_view
from src.utils.csp_view import csp_view
from src.utils.digital_footprint_view import digital_footprint_view


class CDDStateValidationError(ValueError):
    """A migrated snapshot cannot safely be persisted."""


def validate_completed_cdd_state(state: dict[str, Any]) -> None:
    """Validate retained canonical references without inventing historical facts."""
    for name in ("evidence", "assessments", "findings"):
        value = state.get(name, [])
        if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
            raise CDDStateValidationError(f"{name} must be a list of records")

    evidence_ids = _unique_ids(state.get("evidence") or [], "evidence_id", "evidence")
    assessments = state.get("assessments") or []
    assessment_ids = _unique_ids(assessments, "assessment_id", "assessments")
    for assessment in assessments:
        references = assessment.get("source_evidence_ids")
        if references is not None and (
            not isinstance(references, list) or not set(references).issubset(evidence_ids)
        ):
            raise CDDStateValidationError("assessment references unknown evidence")
    for finding in state.get("findings") or []:
        assessment_id = finding.get("assessment_id")
        references = finding.get("relevant_evidence_ids")
        if assessment_id is not None and assessment_id not in assessment_ids:
            raise CDDStateValidationError("finding references an unknown assessment")
        if references is not None and (
            not isinstance(references, list) or not set(references).issubset(evidence_ids)
        ):
            raise CDDStateValidationError("finding references unknown evidence")
        if assessment_id is not None and references is not None:
            assessment = next(item for item in assessments if item.get("assessment_id") == assessment_id)
            if not set(references).issubset(set(assessment.get("source_evidence_ids") or [])):
                raise CDDStateValidationError("finding evidence is not a subset of its assessment")
    assessment_types = {item.get("assessment_type") for item in assessments}
    # Compile every versioned tool view that this retained state binds. This
    # catches presentation incompatibilities before a migrated object is saved.
    try:
        if "csp_address" in assessment_types:
            csp_view({"evidence": state.get("evidence") or [], "assessments": assessments, "findings": state.get("findings") or []})
        if "adverse_news" in assessment_types:
            adverse_news_view({"evidence": state.get("evidence") or [], "assessments": assessments, "findings": state.get("findings") or []})
        if "digital_footprint" in assessment_types:
            digital_footprint_view({"evidence": state.get("evidence") or [], "assessments": assessments, "findings": state.get("findings") or []})
    except Exception as exc:
        raise CDDStateValidationError(f"presentation binding validation failed: {exc}") from exc


def _unique_ids(records: list[dict[str, Any]], field: str, label: str) -> set[str]:
    identifiers = [item.get(field) for item in records if item.get(field) is not None]
    if any(not isinstance(item, str) or not item for item in identifiers):
        raise CDDStateValidationError(f"{label} contains an invalid {field}")
    if len(identifiers) != len(set(identifiers)):
        raise CDDStateValidationError(f"{label} contains duplicate {field} values")
    return set(identifiers)


def run_bulk_migration(
    *, prefix: str | None = None, max_objects: int | None = None, apply: bool = False,
    backup_prefix: str | None = None,
) -> dict[str, Any]:
    """Run a bounded dry run or guarded apply operation and return its report."""
    config = completed_state_store_config()
    if config is None or not has_resolved_credentials():
        raise CDDStateStoreError("CDD state S3 storage and AWS credentials must be configured")
    client = completed_state_s3_client(config)
    if apply and not _rollback_protected(client, config["bucket"], backup_prefix):
        raise CDDStateStoreError(
            "Apply mode requires enabled S3 bucket versioning or --backup-prefix"
        )
    report: dict[str, Any] = {
        "started_at": datetime.now(UTC).isoformat(), "dry_run": not apply,
        "prefix": prefix or config["prefix"], "records": [], "totals": {},
    }
    for key in list_completed_state_keys(config=config, prefix=prefix, max_keys=max_objects):
        record = _migrate_one(config=config, key=key, apply=apply, backup_prefix=backup_prefix, client=client)
        report["records"].append(record)
        report["totals"][record["outcome"]] = report["totals"].get(record["outcome"], 0) + 1
        print(_row(record), flush=True)
    report["finished_at"] = datetime.now(UTC).isoformat()
    return report


def _migrate_one(*, config: dict[str, Any], key: str, apply: bool, backup_prefix: str | None, client: Any) -> dict[str, Any]:
    item: dict[str, Any] = {"key": key, "checked": True, "written": False, "dry_run": not apply, "timestamp": datetime.now(UTC).isoformat()}
    try:
        snapshot = get_completed_state_by_key(config=config, key=key)
        item["versions_before"] = _versions(snapshot)
        candidate = deepcopy(snapshot)
        migration = migrate_completed_cdd_state(candidate["graph_state"])
        item["migration_routines"] = migration["routines"]
        item["versions_after"] = _versions(candidate)
        if not migration["changed"]:
            item.update(outcome="unchanged", reason="All canonical migration routines were already idempotent.")
            return item
        validate_completed_cdd_state(candidate["graph_state"])
        if not apply:
            item.update(outcome="migrated", reason="Validated migration proposed; dry run performed no write.")
            return item
        if backup_prefix:
            _backup(client, config["bucket"], key, backup_prefix)
        put_completed_state_by_key(config=config, key=key, snapshot=candidate)
        item.update(outcome="migrated", written=True, reason="Validated migration written to original key.")
    except CDDStateValidationError as exc:
        item.update(outcome="validation_failed", reason=str(exc))
    except Exception as exc:
        item.update(outcome="write_failed" if apply else "skipped", reason=str(exc))
    return item


def _versions(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "snapshot_schema_version": snapshot.get("schema_version"),
        "assessment_schema_versions": sorted({str(item.get("schema_version")) for item in snapshot.get("graph_state", {}).get("assessments", []) if item.get("schema_version")}),
    }


def _rollback_protected(client: Any, bucket: str, backup_prefix: str | None) -> bool:
    if backup_prefix:
        return True
    status = client.get_bucket_versioning(Bucket=bucket).get("Status")
    return status == "Enabled"


def _backup(client: Any, bucket: str, key: str, backup_prefix: str) -> None:
    destination = f"{backup_prefix.strip().strip('/')}/{key}"
    client.copy_object(Bucket=bucket, Key=destination, CopySource={"Bucket": bucket, "Key": key})


def _row(record: dict[str, Any]) -> str:
    routines = ",".join(f"{name}:{'changed' if changed else 'unchanged'}" for name, changed in (record.get("migration_routines") or {}).items()) or "not evaluated"
    versions = f"versions={record.get('versions_before', {})}→{record.get('versions_after', {})}"
    return f"{record['key']} | checked | {versions} | {record.get('outcome', 'skipped')} | written={record['written']} | routines={routines} | {record.get('reason', '')}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bulk-migrate retained completed CDD states in S3.")
    parser.add_argument("--prefix", help="S3 prefix below CDD_STATE_S3_PREFIX to inspect")
    parser.add_argument("--max-objects", type=int, help="Maximum completed state objects to inspect")
    parser.add_argument("--apply", action="store_true", help="Write changed, validated objects (default is dry run)")
    parser.add_argument("--confirm-apply", action="store_true", help="Required together with --apply")
    parser.add_argument("--backup-prefix", help="Copy each original object here before an apply write")
    parser.add_argument("--report", type=Path, help="Write the machine-readable JSON report to this path")
    args = parser.parse_args(argv)
    if args.max_objects is not None and args.max_objects < 1:
        parser.error("--max-objects must be at least 1")
    if args.apply and not args.confirm_apply:
        parser.error("--apply requires --confirm-apply")
    load_application_env()
    report = run_bulk_migration(prefix=args.prefix, max_objects=args.max_objects, apply=args.apply, backup_prefix=args.backup_prefix)
    if args.report:
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"totals": report["totals"], "dry_run": report["dry_run"]}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
