"""Upload generated CDD documents to S3."""

from __future__ import annotations

import mimetypes
import os
from pathlib import Path
from typing import Any
from urllib.parse import quote

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BUCKET_URL = "https://onbo-bkt.s3.us-east-1.amazonaws.com"

load_dotenv(PROJECT_ROOT / ".env")


def upload_document_to_s3(
    path: str | Path,
    *,
    category: str,
    case_id: int | str | None = None,
    person_name: str | None = None,
    source: str | None = None,
) -> dict[str, Any] | None:
    """Upload a generated document to S3 and return case-document metadata.

    Upload is skipped when AWS credentials are not configured. This keeps local
    runs and unit tests usable while enabling S3 persistence in configured envs.
    """
    if not _has_aws_credentials():
        return None

    bucket_url = _bucket_url()
    bucket_name = _bucket_name(bucket_url)
    document_path = Path(path)
    key = _object_key(document_path, category=category, case_id=case_id)
    content_type = mimetypes.guess_type(document_path.name)[0] or "application/octet-stream"

    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError("boto3 is required to upload generated documents to S3") from exc

    boto3.client("s3", region_name=_region_name(bucket_url)).upload_file(
        str(document_path),
        bucket_name,
        key,
        ExtraArgs={"ContentType": content_type},
    )

    url = f"{bucket_url.rstrip('/')}/{quote(key)}"
    return {
        "name": document_path.name,
        "category": category,
        "url": url,
        "path": str(document_path),
        "source": source,
        "person_name": person_name,
        "storage": {
            "provider": "s3",
            "bucket": bucket_name,
            "key": key,
            "url": url,
        },
    }


def s3_upload_skip_reason() -> str | None:
    """Return why S3 upload is disabled, if it is disabled."""
    if _has_aws_credentials():
        return None
    missing = []
    if not os.getenv("AWS_ACCESS_KEY_ID"):
        missing.append("AWS_ACCESS_KEY_ID")
    if not os.getenv("AWS_SECRET_ACCESS_KEY"):
        missing.append("AWS_SECRET_ACCESS_KEY")
    return f"missing AWS credential env vars: {', '.join(missing)}"


def _has_aws_credentials() -> bool:
    return bool(os.getenv("AWS_ACCESS_KEY_ID") and os.getenv("AWS_SECRET_ACCESS_KEY"))


def _bucket_url() -> str:
    return (
        os.getenv("S3_DOCUMENT_BUCKET_URL")
        or os.getenv("AWS_S3_BUCKET_URL")
        or DEFAULT_BUCKET_URL
    )


def _bucket_name(bucket_url: str) -> str:
    configured = os.getenv("S3_DOCUMENT_BUCKET") or os.getenv("AWS_S3_BUCKET")
    if configured:
        return configured
    host = bucket_url.removeprefix("https://").removeprefix("http://").split("/", 1)[0]
    return host.split(".s3", 1)[0]


def _region_name(bucket_url: str) -> str | None:
    configured = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
    if configured:
        return configured
    host = bucket_url.removeprefix("https://").removeprefix("http://").split("/", 1)[0]
    marker = ".s3."
    if marker not in host:
        return None
    return host.split(marker, 1)[1].split(".", 1)[0]


def _object_key(
    document_path: Path,
    *,
    category: str,
    case_id: int | str | None,
) -> str:
    case_part = f"case-{case_id}" if case_id not in (None, "") else "unassigned-case"
    return f"generated_documents/{case_part}/{category}/{document_path.name}"
