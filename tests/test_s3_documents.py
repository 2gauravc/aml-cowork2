"""Tests for S3 credential-chain configuration."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from src.utils import s3_documents


class S3CredentialChainTests(unittest.TestCase):
    def test_instance_profile_credentials_are_accepted_without_static_keys(self) -> None:
        with patch.dict(
            "os.environ",
            {"AWS_ACCESS_KEY_ID": "", "AWS_SECRET_ACCESS_KEY": ""},
            clear=False,
        ), patch("boto3.Session") as session:
            session.return_value.get_credentials.return_value = object()

            self.assertTrue(s3_documents._has_aws_credentials())

    def test_no_resolved_credentials_disable_optional_s3(self) -> None:
        with patch("boto3.Session") as session:
            session.return_value.get_credentials.return_value = None

            self.assertFalse(s3_documents._has_aws_credentials())
            self.assertEqual(
                s3_documents.s3_upload_skip_reason(),
                "no usable AWS credentials were found (instance role, profile, or environment)",
            )

    def test_document_prefix_includes_configured_storage_prefix(self) -> None:
        with patch.dict("os.environ", {"S3_DOCUMENT_PREFIX": "demo-documents/"}, clear=False):
            self.assertEqual(
                s3_documents.document_prefix(company_name="Example Ltd", jurisdiction="sg"),
                "demo-documents/generated_documents/SG/example-ltd/",
            )


if __name__ == "__main__":
    unittest.main()
