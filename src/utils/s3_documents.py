"""Upload generated CDD documents to S3."""

from __future__ import annotations

import mimetypes
import os
import re
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import quote

from src.utils.aws import has_resolved_credentials, s3_client
from src.utils.environment import load_application_env


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BUCKET_URL = "https://onbo-bkt.s3.us-east-1.amazonaws.com"

load_application_env(PROJECT_ROOT / ".env")


def upload_document_to_s3(
    path: str | Path,
    *,
    category: str,
    case_id: int | str | None = None,
    person_name: str | None = None,
    source: str | None = None,
    source_type: str | None = None,
    provenance: str | None = None,
    synthetic: bool | None = None,
    company_name: str | None = None,
    jurisdiction: str | None = None,
    object_name: str | None = None,
) -> dict[str, Any] | None:
    """Upload a generated document to S3 and return case-document metadata.

    Upload is skipped when no usable AWS credentials are available. This keeps
    local runs and unit tests usable while allowing boto3 to use EC2 instance
    role credentials in deployed environments.
    """
    if not _has_aws_credentials():
        return None

    bucket_url = _bucket_url()
    bucket_name = _bucket_name(bucket_url)
    document_path = Path(path)
    key = _object_key(
        document_path,
        category=category,
        case_id=case_id,
        company_name=company_name,
        jurisdiction=jurisdiction,
        object_name=object_name,
    )
    content_type = mimetypes.guess_type(document_path.name)[0] or "application/octet-stream"

    metadata = _provenance_metadata(
        source_type=source_type,
        provenance=provenance,
        synthetic=synthetic,
    )
    extra_args: dict[str, Any] = {"ContentType": content_type}
    if metadata:
        extra_args["Metadata"] = metadata
    s3_client(region_name=_region_name(bucket_url)).upload_file(
        str(document_path),
        bucket_name,
        key,
        ExtraArgs=extra_args,
    )

    url = f"{bucket_url.rstrip('/')}/{quote(key)}"
    return {
        "name": Path(key).name,
        "category": category,
        "url": url,
        "path": str(document_path),
        "source": source,
        "source_type": source_type,
        "provenance": provenance,
        "synthetic": synthetic,
        "person_name": person_name,
        "storage": {
            "provider": "s3",
            "bucket": bucket_name,
            "key": key,
            "url": url,
        },
    }


def find_documents_in_s3(
    *,
    company_name: str | None,
    jurisdiction: str | None,
) -> list[dict[str, Any]]:
    """List reusable PDFs in one company/jurisdiction's flat S3 folder."""
    prefix = document_prefix(company_name=company_name, jurisdiction=jurisdiction)
    if not prefix or not _has_aws_credentials():
        return []

    bucket_url = _bucket_url()
    bucket_name = _bucket_name(bucket_url)
    client = s3_client(region_name=_region_name(bucket_url))
    response = client.list_objects_v2(
        Bucket=bucket_name,
        Prefix=prefix,
    )
    documents = []
    for item in response.get("Contents", []):
        key = item.get("Key", "")
        document_type = _document_type_from_key(key)
        if not document_type:
            continue
        provenance = _object_provenance(client, bucket_name, key)
        url = f"{bucket_url.rstrip('/')}/{quote(key)}"
        documents.append(
            {
                "name": Path(key).name,
                "category": document_type,
                "url": url,
                "storage": {
                    "provider": "s3",
                    "bucket": bucket_name,
                    "key": key,
                    "url": url,
                },
                "last_modified": item.get("LastModified"),
                **provenance,
            }
        )
    return documents


def _object_provenance(client: Any, bucket_name: str, key: str) -> dict[str, Any]:
    """Return explicitly retained provenance metadata for a cached object.

    Metadata is optional for legacy objects, so a missing header must remain
    unknown rather than being inferred from the filename or storage location.
    """
    try:
        metadata = client.head_object(Bucket=bucket_name, Key=key).get("Metadata") or {}
    except Exception:
        return {}
    synthetic = metadata.get("synthetic")
    return {
        "source_type": metadata.get("source_type") or None,
        "provenance": metadata.get("provenance") or None,
        "synthetic": synthetic.casefold() == "true" if isinstance(synthetic, str) else None,
    }


def _provenance_metadata(
    *, source_type: str | None, provenance: str | None, synthetic: bool | None
) -> dict[str, str]:
    metadata = {
        key: value
        for key, value in {
            "source_type": source_type,
            "provenance": provenance,
        }.items()
        if isinstance(value, str) and value.strip()
    }
    if synthetic is not None:
        metadata["synthetic"] = str(synthetic).lower()
    return metadata


def download_document_from_s3(
    document: dict[str, Any],
    *,
    output_dir: str | Path | None = None,
) -> str:
    """Download an S3 document to a unique temporary local path for extraction."""
    storage = document.get("storage") or {}
    bucket = storage.get("bucket")
    key = storage.get("key")
    if not bucket or not key:
        raise ValueError("S3 document metadata must include storage.bucket and storage.key")
    directory = Path(output_dir) if output_dir else Path(tempfile.mkdtemp(prefix="cdd-s3-"))
    directory.mkdir(parents=True, exist_ok=True)
    local_path = directory / Path(key).name
    s3_client(region_name=_region_name(_bucket_url())).download_file(
        bucket,
        key,
        str(local_path),
    )
    return str(local_path)


def document_prefix(*, company_name: str | None, jurisdiction: str | None) -> str | None:
    """Return the stable flat-folder prefix used for a company's documents."""
    if not company_name or not jurisdiction:
        return None
    return f"{_storage_prefix()}generated_documents/{jurisdiction.strip().upper()}/{_slug(company_name)}/"


def reusable_document_name(
    *,
    document_type: str,
    company_name: str,
    person_name: str | None = None,
) -> str:
    """Return a deterministic PDF name so a later CDD run can reuse it."""
    if document_type == "registry_document":
        return f"registry-business-profile-{_slug(company_name)}.pdf"
    if document_type not in {"passport", "national_id"}:
        raise ValueError(f"Unsupported reusable document type: {document_type}")
    if not person_name:
        raise ValueError("person_name is required for an identity document")
    return f"{document_type.replace('_', '-')}-{_slug(person_name)}.pdf"


def presign_document_url(
    *,
    bucket: str,
    key: str,
    expires_in_seconds: int = 900,
) -> str:
    """Generate a short-lived download URL for a private S3 document."""
    return s3_client(region_name=_region_name(_bucket_url())).generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=expires_in_seconds,
    )


def s3_upload_skip_reason() -> str | None:
    """Return why S3 upload is disabled, if it is disabled."""
    if _has_aws_credentials():
        return None
    return "no usable AWS credentials were found (instance role, profile, or environment)"


def _has_aws_credentials() -> bool:
    """Return whether boto3 can resolve credentials from its standard chain.

    This supports local AWS profiles and EC2 instance profiles without storing
    long-lived access keys in the application environment.
    """
    return has_resolved_credentials()


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
    company_name: str | None = None,
    jurisdiction: str | None = None,
    object_name: str | None = None,
) -> str:
    prefix = document_prefix(company_name=company_name, jurisdiction=jurisdiction)
    if prefix:
        return f"{prefix}{object_name or document_path.name}"
    case_part = f"case-{case_id}" if case_id not in (None, "") else "unassigned-case"
    return f"{_storage_prefix()}generated_documents/{case_part}/{category}/{document_path.name}"


def _storage_prefix() -> str:
    """Return an optional S3 object prefix, normalized for path composition."""
    configured = os.getenv("S3_DOCUMENT_PREFIX", "").strip().strip("/")
    return f"{configured}/" if configured else ""


def _document_type_from_key(key: str) -> str | None:
    name = Path(key).name.lower()
    if not name.endswith(".pdf"):
        return None
    if name.startswith("registry-business-profile-"):
        return "registry_document"
    if name.startswith("passport-"):
        return "passport"
    if name.startswith("national-id-"):
        return "national_id"
    return None


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "unnamed"
