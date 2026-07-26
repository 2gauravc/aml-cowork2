"""Persistent KYC API cache with local and S3 company-object backends."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import logging
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CACHE_PATH = PROJECT_ROOT / "outputs" / "cache" / "kyc_api_cache.json"
DEFAULT_S3_PREFIX = "kyc-cache"
CACHE_SCHEMA_VERSION = 1
S3_WRITE_ATTEMPTS = 3

_LOCK = threading.Lock()
LOGGER = logging.getLogger(__name__)
CacheSubject = tuple[str, str]


@dataclass(frozen=True)
class S3CacheConfig:
    bucket: str
    prefix: str
    region: str | None


def company_cache_subject(jurisdiction: str, company_name: str) -> CacheSubject:
    """Return the stable company/jurisdiction identity used by the S3 cache."""
    normalized_jurisdiction = jurisdiction.strip().upper()
    normalized_company_name = company_name.strip()
    if not normalized_jurisdiction or not normalized_company_name:
        raise ValueError("jurisdiction and company_name are required for a company cache subject")
    return normalized_jurisdiction, normalized_company_name


def get_cache_value(
    namespace: str,
    parts: list[str | int],
    *,
    subject: CacheSubject | None = None,
) -> Any | None:
    """Return a cached value, preferring the configured S3 company object."""
    key = cache_key(namespace, parts)
    with _LOCK:
        config = _s3_config()
        if config is not None and subject is not None:
            document, _, available = _read_s3_document(config, subject)
            if available and document is not None:
                value = (document.get("entries") or {}).get(namespace)
                if value is not None:
                    return value
        return _read_local_cache().get(key)


def get_cache_source(
    namespace: str,
    parts: list[str | int],
    *,
    subject: CacheSubject | None = None,
) -> str | None:
    """Return the backend holding a cached value: ``s3``, ``local``, or none."""
    key = cache_key(namespace, parts)
    with _LOCK:
        config = _s3_config()
        if config is not None and subject is not None:
            document, _, available = _read_s3_document(config, subject)
            if available and document is not None:
                value = (document.get("entries") or {}).get(namespace)
                if value is not None:
                    return "s3"
        return "local" if key in _read_local_cache() else None


def set_cache_value(
    namespace: str,
    parts: list[str | int],
    value: Any,
    *,
    subject: CacheSubject | None = None,
) -> Any:
    """Persist a value to S3 when configured, otherwise retain the local cache."""
    key = cache_key(namespace, parts)
    with _LOCK:
        config = _s3_config()
        if config is not None and subject is not None:
            if _merge_s3_entry(config, subject, namespace, value):
                return value
            LOGGER.warning("KYC S3 cache write failed; retaining a local fallback entry.")

        data = _read_local_cache()
        data[key] = value
        _write_local_cache(data)
    return value


def cache_key(namespace: str, parts: list[str | int]) -> str:
    normalized_parts = [_normalize_part(str(part)) for part in parts]
    return ":".join([namespace, *normalized_parts])


def migrate_local_cache_to_s3(
    *,
    source_path: str | Path,
    bucket: str,
    prefix: str = DEFAULT_S3_PREFIX,
    region: str | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """Group a legacy local cache into one S3 object per company/jurisdiction."""
    source = Path(source_path)
    data = _read_json_map(source)
    groups, unresolved, skipped_entries = _group_legacy_entries(data)
    if unresolved:
        raise ValueError(
            "Cannot migrate local KYC cache because some entries cannot be mapped "
            f"to a company/jurisdiction object ({len(unresolved)} entries)."
        )

    result = {
        "source_entries": len(data),
        "company_objects": len(groups),
        "migrated_objects": 0,
        "skipped_entries": skipped_entries,
    }
    if dry_run:
        return result

    config = S3CacheConfig(
        bucket=bucket.strip(),
        prefix=_normalise_prefix(prefix),
        region=region,
    )
    if not config.bucket:
        raise ValueError("bucket is required")

    for subject, entries in groups.items():
        if not _merge_s3_entries(config, subject, entries):
            raise RuntimeError(
                "Unable to write the S3 cache object for "
                f"{subject[0]}/{_normalize_part(subject[1])}."
            )
        result["migrated_objects"] += 1
    return result


def _s3_config() -> S3CacheConfig | None:
    bucket = os.getenv("KYC_CACHE_S3_BUCKET", "").strip()
    if not bucket:
        return None
    return S3CacheConfig(
        bucket=bucket,
        prefix=_normalise_prefix(os.getenv("KYC_CACHE_S3_PREFIX", DEFAULT_S3_PREFIX)),
        region=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or None,
    )


def _read_s3_document(
    config: S3CacheConfig,
    subject: CacheSubject,
    *,
    client: Any | None = None,
) -> tuple[dict[str, Any] | None, str | None, bool]:
    try:
        s3_client = client or _s3_client(config)
        response = s3_client.get_object(Bucket=config.bucket, Key=_s3_object_key(config, subject))
        body = response["Body"].read()
        if isinstance(body, bytes):
            body = body.decode("utf-8")
        document = json.loads(body)
        if not isinstance(document, dict) or not isinstance(document.get("entries"), dict):
            raise ValueError("S3 cache object has an invalid schema")
        return document, response.get("ETag"), True
    except Exception as exc:
        if _is_missing_s3_object(exc):
            return None, None, True
        LOGGER.warning("KYC S3 cache read failed: %s", exc)
        return None, None, False


def _merge_s3_entry(
    config: S3CacheConfig,
    subject: CacheSubject,
    namespace: str,
    value: Any,
) -> bool:
    return _merge_s3_entries(config, subject, {namespace: value})


def _merge_s3_entries(
    config: S3CacheConfig,
    subject: CacheSubject,
    entries: dict[str, Any],
    *,
    client: Any | None = None,
) -> bool:
    try:
        s3_client = client or _s3_client(config)
    except Exception as exc:
        LOGGER.warning("KYC S3 cache client could not be created: %s", exc)
        return False

    for _ in range(S3_WRITE_ATTEMPTS):
        document, etag, available = _read_s3_document(config, subject, client=s3_client)
        if not available:
            return False
        merged = document or _new_s3_document(subject)
        merged_entries = dict(merged.get("entries") or {})
        merged_entries.update(entries)
        merged["entries"] = merged_entries

        request: dict[str, Any] = {
            "Bucket": config.bucket,
            "Key": _s3_object_key(config, subject),
            "Body": json.dumps(merged, ensure_ascii=False, sort_keys=True).encode("utf-8"),
            "ContentType": "application/json",
        }
        if etag:
            request["IfMatch"] = etag
        else:
            request["IfNoneMatch"] = "*"

        try:
            s3_client.put_object(**request)
            return True
        except Exception as exc:
            if _is_s3_write_conflict(exc):
                continue
            LOGGER.warning("KYC S3 cache write failed: %s", exc)
            return False

    LOGGER.warning("KYC S3 cache write conflicted too many times.")
    return False


def _new_s3_document(subject: CacheSubject) -> dict[str, Any]:
    return {
        "schema_version": CACHE_SCHEMA_VERSION,
        "identity": {
            "jurisdiction": subject[0],
            "company_name": subject[1],
        },
        "entries": {},
    }


def _s3_client(config: S3CacheConfig) -> Any:
    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError("boto3 is required for the S3 KYC cache") from exc
    return boto3.client("s3", region_name=config.region)


def _s3_object_key(config: S3CacheConfig, subject: CacheSubject) -> str:
    jurisdiction, company_name = company_cache_subject(*subject)
    return f"{config.prefix}/{jurisdiction}/{_normalize_part(company_name)}.json"


def _normalise_prefix(prefix: str) -> str:
    cleaned = prefix.strip().strip("/")
    return cleaned or DEFAULT_S3_PREFIX


def _is_missing_s3_object(exc: Exception) -> bool:
    code = _s3_error_code(exc)
    return code in {"NoSuchKey", "404", "NotFound"}


def _is_s3_write_conflict(exc: Exception) -> bool:
    return _s3_error_code(exc) in {"PreconditionFailed", "ConditionalRequestConflict", "412"}


def _s3_error_code(exc: Exception) -> str | None:
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        error = response.get("Error") or {}
        code = error.get("Code")
        return str(code) if code is not None else None
    return None


def _cache_path() -> Path:
    configured = os.getenv("KYC_CACHE_PATH")
    return Path(configured) if configured else DEFAULT_CACHE_PATH


def _read_local_cache() -> dict[str, Any]:
    return _read_json_map(_cache_path())


def _read_json_map(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as fh:
        try:
            data = json.load(fh)
        except json.JSONDecodeError:
            return {}
    return data if isinstance(data, dict) else {}


def _write_local_cache(data: dict[str, Any]) -> None:
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
    ) as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
        fh.write("\n")
        temp_name = fh.name
    Path(temp_name).replace(path)


def _group_legacy_entries(
    data: dict[str, Any],
) -> tuple[dict[CacheSubject, dict[str, Any]], list[str], int]:
    """Group legacy records by resolved registry company, not search query."""
    groups: dict[CacheSubject, dict[str, Any]] = {}
    unresolved: list[str] = []
    case_query_subjects: dict[str, CacheSubject] = {}
    case_records: dict[str, dict[str, Any]] = {}
    details: dict[str, dict[str, Any]] = {}
    members: dict[str, Any] = {}
    org_charts: dict[str, Any] = {}
    skipped_entries = 0

    for key, value in data.items():
        namespace, parts = _split_legacy_key(key)
        if namespace == "company-case" and len(parts) == 2:
            if isinstance(value, dict) and value.get("case_id") is not None:
                case_id = str(value["case_id"])
                case_query_subjects[case_id] = company_cache_subject(parts[0], parts[1])
                case_records[case_id] = value
            else:
                unresolved.append(key)
        elif namespace == "company-search":
            # A search can be empty, use a typo, or return a different legal
            # name. It is deliberately kept local rather than made an S3
            # company object.
            skipped_entries += 1
        elif namespace == "company-detail" and len(parts) == 1:
            details[parts[0]] = value if isinstance(value, dict) else {}
        elif namespace == "company-members" and len(parts) == 1:
            members[parts[0]] = value
        elif namespace == "company-org-chart" and len(parts) == 1:
            org_charts[parts[0]] = value
        else:
            unresolved.append(key)

    case_subjects: dict[str, CacheSubject] = {}
    all_case_ids = set(case_records) | set(details) | set(members) | set(org_charts)
    for case_id in all_case_ids:
        subject = _subject_from_detail(details.get(case_id, {}))
        if subject is None:
            subject = _subject_from_case(case_records.get(case_id, {}))
        if subject is None:
            subject = case_query_subjects.get(case_id)
        if subject is None:
            unresolved.append(f"case:{case_id}")
            continue
        case_subjects[case_id] = subject

    selected_cases: dict[CacheSubject, str] = {}
    for case_id, subject in case_subjects.items():
        existing = selected_cases.get(subject)
        if existing is None or _case_sort_key(case_id) > _case_sort_key(existing):
            selected_cases[subject] = case_id

    selected_ids = set(selected_cases.values())
    for case_id, subject in case_subjects.items():
        if case_id not in selected_ids:
            skipped_entries += sum(
                case_id in records
                for records in (case_records, details, members, org_charts)
            )
            continue
        entries = groups.setdefault(subject, {})
        if case_id in case_records:
            entries["company-case"] = case_records[case_id]
        if case_id in details:
            entries["company-detail"] = details[case_id]
        if case_id in members:
            entries["company-members"] = members[case_id]
        if case_id in org_charts:
            entries["company-org-chart"] = org_charts[case_id]

    return groups, unresolved, skipped_entries


def _split_legacy_key(key: str) -> tuple[str, list[str]]:
    namespace, *parts = key.split(":")
    return namespace, parts


def _subject_from_detail(detail: dict[str, Any]) -> CacheSubject | None:
    company = detail.get("caseDetail", {}).get("details", {}).get("company", {})
    name = company.get("entityName")
    jurisdiction = company.get("countryCodeISO31662")
    if not isinstance(name, str) or not isinstance(jurisdiction, str):
        return None
    return company_cache_subject(jurisdiction, name)


def _subject_from_case(case: dict[str, Any]) -> CacheSubject | None:
    jurisdiction = case.get("jurisdiction")
    selected_match = case.get("selected_registry_match") or {}
    name = selected_match.get("rawname") or case.get("searched_company_name")
    if not isinstance(name, str) or not isinstance(jurisdiction, str):
        return None
    return company_cache_subject(jurisdiction, name)


def _case_sort_key(case_id: str) -> tuple[int, str]:
    try:
        return int(case_id), case_id
    except ValueError:
        return -1, case_id


def _normalize_part(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    return normalized.strip("-") or "empty"


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage the KYC API cache")
    subparsers = parser.add_subparsers(dest="command", required=True)
    migrate = subparsers.add_parser("migrate-local-to-s3", help="Migrate local cache data to S3")
    migrate.add_argument("--source", default=str(DEFAULT_CACHE_PATH))
    migrate.add_argument("--bucket", required=True)
    migrate.add_argument("--prefix", default=DEFAULT_S3_PREFIX)
    migrate.add_argument("--region")
    migrate.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.command == "migrate-local-to-s3":
        result = migrate_local_cache_to_s3(
            source_path=args.source,
            bucket=args.bucket,
            prefix=args.prefix,
            region=args.region,
            dry_run=args.dry_run,
        )
        print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
