"""Tests for the optional per-company S3 KYC cache backend."""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.utils import kyc_cache


class FakeS3Error(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.put_requests: list[dict[str, object]] = []
        self._version = 0

    def get_object(self, *, Bucket: str, Key: str):  # noqa: N803
        del Bucket
        if Key not in self.objects:
            raise FakeS3Error("NoSuchKey")
        body, etag = self.objects[Key]
        return {"Body": io.BytesIO(body), "ETag": etag}

    def put_object(self, **request):
        key = str(request["Key"])
        existing = self.objects.get(key)
        if request.get("IfNoneMatch") == "*" and existing is not None:
            raise FakeS3Error("PreconditionFailed")
        if request.get("IfMatch") and (existing is None or request["IfMatch"] != existing[1]):
            raise FakeS3Error("PreconditionFailed")

        body = request["Body"]
        if not isinstance(body, bytes):
            raise AssertionError("Expected bytes body")
        self._version += 1
        self.objects[key] = (body, f'"{self._version}"')
        self.put_requests.append(request)


class KycS3CacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = FakeS3Client()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cache_path = os.path.join(self.temp_dir.name, "local-cache.json")
        self.environment = patch.dict(
            os.environ,
            {
                "KYC_CACHE_PATH": self.cache_path,
                "KYC_CACHE_S3_BUCKET": "onbo-bkt",
                "KYC_CACHE_S3_PREFIX": "kyc-cache",
                "AWS_REGION": "us-east-1",
            },
            clear=False,
        )
        self.environment.start()
        self.s3_client = patch("src.utils.kyc_cache._s3_client", return_value=self.client)
        self.s3_client.start()

    def tearDown(self) -> None:
        self.s3_client.stop()
        self.environment.stop()
        self.temp_dir.cleanup()

    def test_company_entries_share_one_company_object_and_are_read_back(self):
        subject = kyc_cache.company_cache_subject("SG", "SC Engineering Private Limited")
        kyc_cache.set_cache_value(
            "company-case",
            ["SG", "SC Engineering Private Limited"],
            {"case_id": 100, "ready": True},
            subject=subject,
        )
        kyc_cache.set_cache_value(
            "company-detail",
            [100],
            {"caseDetail": {"details": {"company": {"entityName": "SC Engineering"}}}},
            subject=subject,
        )

        key = "kyc-cache/SG/sc-engineering-private-limited.json"
        self.assertEqual(set(self.client.objects), {key})
        document = json.loads(self.client.objects[key][0])
        self.assertEqual(document["identity"], {
            "jurisdiction": "SG",
            "company_name": "SC Engineering Private Limited",
        })
        self.assertEqual(set(document["entries"]), {"company-case", "company-detail"})
        self.assertEqual(
            kyc_cache.get_cache_value("company-case", ["SG", "SC Engineering Private Limited"], subject=subject),
            {"case_id": 100, "ready": True},
        )
        self.assertEqual(
            kyc_cache.get_cache_source(
                "company-case",
                ["SG", "SC Engineering Private Limited"],
                subject=subject,
            ),
            "s3",
        )

    def test_s3_write_failure_retains_a_local_fallback(self):
        subject = kyc_cache.company_cache_subject("HK", "Example Limited")
        with patch("src.utils.kyc_cache._s3_client", side_effect=RuntimeError("S3 unavailable")):
            kyc_cache.set_cache_value(
                "company-case",
                ["HK", "Example Limited"],
                {"case_id": 200},
                subject=subject,
            )
            result = kyc_cache.get_cache_value(
                "company-case",
                ["HK", "Example Limited"],
                subject=subject,
            )

        self.assertEqual(result, {"case_id": 200})
        self.assertTrue(Path(self.cache_path).exists())

    def test_local_migration_groups_case_entries_under_the_matching_company(self):
        legacy = {
            "company-case:HK:example-limited": {"case_id": 300, "ready": True},
            "company-search:HK:example-limited": {"companySearch": {"results": []}},
            "company-detail:300": {
                "caseDetail": {
                    "details": {
                        "company": {
                            "entityName": "Example Limited",
                            "countryCodeISO31662": "HK",
                        }
                    }
                }
            },
            "company-members:300": {"companyMembers": []},
            "company-org-chart:300": {"orgChart": {}},
        }
        source = Path(self.temp_dir.name) / "legacy.json"
        source.write_text(json.dumps(legacy), encoding="utf-8")

        dry_run = kyc_cache.migrate_local_cache_to_s3(
            source_path=source,
            bucket="onbo-bkt",
            prefix="kyc-cache",
            region="us-east-1",
            dry_run=True,
        )
        result = kyc_cache.migrate_local_cache_to_s3(
            source_path=source,
            bucket="onbo-bkt",
            prefix="kyc-cache",
            region="us-east-1",
        )

        self.assertEqual(
            dry_run,
            {
                "source_entries": 5,
                "company_objects": 1,
                "migrated_objects": 0,
                "skipped_entries": 1,
            },
        )
        self.assertEqual(
            result,
            {
                "source_entries": 5,
                "company_objects": 1,
                "migrated_objects": 1,
                "skipped_entries": 1,
            },
        )
        document = json.loads(self.client.objects["kyc-cache/HK/example-limited.json"][0])
        self.assertEqual(
            set(document["entries"]),
            {"company-case", "company-detail", "company-members", "company-org-chart"},
        )

    def test_migration_uses_the_resolved_registry_jurisdiction_not_an_empty_search(self):
        legacy = {
            "company-case:gb:cropwell-bishop-creamery-limite": {
                "case_id": 400,
                "jurisdiction": "GB",
                "selected_registry_match": {
                    "rawname": "CROPWELL BISHOP CREAMERY LIMITED",
                },
            },
            "company-detail:400": {
                "caseDetail": {
                    "details": {
                        "company": {
                            "entityName": "CROPWELL BISHOP CREAMERY LIMITED",
                            "countryCodeISO31662": "GB",
                        }
                    }
                }
            },
            "company-search:sg:cropwell-bishop-creamery-limited": {
                "companySearch": {"results": []}
            },
        }
        source = Path(self.temp_dir.name) / "cropwell-legacy.json"
        source.write_text(json.dumps(legacy), encoding="utf-8")

        result = kyc_cache.migrate_local_cache_to_s3(
            source_path=source,
            bucket="onbo-bkt",
            prefix="kyc-cache",
            region="us-east-1",
        )

        self.assertEqual(result["company_objects"], 1)
        self.assertIn("kyc-cache/GB/cropwell-bishop-creamery-limited.json", self.client.objects)
        self.assertNotIn("kyc-cache/SG/cropwell-bishop-creamery-limited.json", self.client.objects)
