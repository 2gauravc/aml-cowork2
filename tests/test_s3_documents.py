"""Tests for S3 credential-chain configuration."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

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

    def test_cached_documents_read_explicit_s3_provenance_metadata(self) -> None:
        client = MagicMock()
        client.list_objects_v2.return_value = {
            "Contents": [{"Key": "generated_documents/GB/example/passport-alex.pdf"}]
        }
        client.head_object.return_value = {
            "Metadata": {
                "source_type": "generated_demo",
                "provenance": "synthetic_demo",
                "synthetic": "true",
            }
        }
        with patch("src.utils.s3_documents._has_aws_credentials", return_value=True), patch(
            "boto3.client", return_value=client
        ):
            documents = s3_documents.find_documents_in_s3(
                company_name="Example", jurisdiction="GB"
            )

        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0]["source_type"], "generated_demo")
        self.assertEqual(documents[0]["provenance"], "synthetic_demo")
        self.assertIs(documents[0]["synthetic"], True)

    def test_upload_persists_explicit_provenance_metadata(self) -> None:
        client = MagicMock()
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "passport-alex.pdf"
            path.write_bytes(b"pdf")
            with patch("src.utils.s3_documents._has_aws_credentials", return_value=True), patch(
                "boto3.client", return_value=client
            ):
                s3_documents.upload_document_to_s3(
                    path,
                    category="passport",
                    source_type="generated_demo",
                    provenance="synthetic_demo",
                    synthetic=True,
                )

        self.assertEqual(
            client.upload_file.call_args.kwargs["ExtraArgs"],
            {
                "ContentType": "application/pdf",
                "Metadata": {
                    "source_type": "generated_demo",
                    "provenance": "synthetic_demo",
                    "synthetic": "true",
                },
            },
        )


if __name__ == "__main__":
    unittest.main()
