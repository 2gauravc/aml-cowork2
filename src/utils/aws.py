"""Shared AWS configuration helpers.

AWS SDK clients deliberately use boto3's default credential provider chain.
That permits local AWS profiles and SSO, as well as task or instance roles in
deployed environments, without application-managed access keys.
"""

from __future__ import annotations

from typing import Any


def has_resolved_credentials() -> bool:
    """Return whether boto3 can resolve credentials from its default chain."""
    try:
        import boto3
    except ImportError:
        return False
    try:
        return boto3.Session().get_credentials() is not None
    except Exception:
        return False


def s3_client(*, region_name: str | None) -> Any:
    """Create an S3 client without supplying application-managed credentials."""
    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError("boto3 is required for S3 storage") from exc
    return boto3.client("s3", region_name=region_name)
