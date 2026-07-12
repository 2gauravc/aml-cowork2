import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.tools.cdd_enrichment import (
    apply_document_extract_to_cdd,
    missing_about_customer_fields,
)
from src.tools.document_extraction import classify_document, extract_document
from src.agents.nodes import extract_registry_document, generate_registry_document_node
from src.utils.document_pipeline import REGISTRY_SOURCE_LABEL, generate_registry_document


class DocumentPipelineTests(unittest.TestCase):
    def test_registry_document_enriches_missing_paid_up_capital_only(self):
        cdd = {
            "company_business_profile": {
                "customer_static": {
                    "name": "CROPWELL BISHOP CREAMERY LIMITED",
                    "jurisdiction": "GB",
                    "company_status": "Active",
                    "registration_number": "00364890",
                    "company_type": "Private Company Limited by Shares",
                    "activity_type": "10512 - Butter and cheese production",
                    "incorporation_date": "15/01/1941",
                    "registered_address": {
                        "full_address": "Nottingham Road, Cropwell Bishop"
                    },
                    "source": {
                        "registration_number": {
                            "api": "KYC.com GET /v2/Companies/123",
                            "field": "Registration Number",
                        }
                    },
                }
            }
        }

        self.assertEqual(missing_about_customer_fields(cdd), ["paid_up_capital"])
        with tempfile.TemporaryDirectory() as tmp:
            artifact = generate_registry_document(cdd, output_dir=Path(tmp))
            self.assertTrue(Path(artifact["pdf_path"]).exists())
            self.assertTrue(Path(artifact["html_path"]).exists())

            with patch(
                "src.tools.document_extraction._run_schema_prompt",
                side_effect=[
                    {
                        "document_type": "registry_document",
                        "confidence": 0.99,
                        "reason": "Business profile table",
                    },
                    {
                        "document_type": "registry_document",
                        "name": "CROPWELL BISHOP CREAMERY LIMITED",
                        "jurisdiction": "GB",
                        "company_status": "Active",
                        "registration_number": "00364890",
                        "company_type": "Private Company Limited by Shares",
                        "paid_up_capital": "GBP 100,000",
                        "activity_type": "10512 - Butter and cheese production",
                        "incorporation_date": "15/01/1941",
                        "registered_address": {
                            "full_address": "Nottingham Road, Cropwell Bishop"
                        },
                    },
                ],
            ) as run_schema_prompt:
                classification = classify_document(artifact["pdf_path"])
                extract = extract_document(artifact, classification=classification)
            applied = apply_document_extract_to_cdd(cdd, extract)

        static = cdd["company_business_profile"]["customer_static"]
        self.assertEqual(run_schema_prompt.call_count, 2)
        self.assertEqual(applied, ["paid_up_capital"])
        self.assertEqual(static["registration_number"], "00364890")
        self.assertIn("display_capital", static)
        self.assertEqual(static["display_capital"]["label"], "Paid-up Capital")
        self.assertEqual(
            static["source"]["paid_up_capital"]["source"],
            REGISTRY_SOURCE_LABEL,
        )
        self.assertEqual(static["source"]["paid_up_capital"]["field"], "Paid-up Capital")
        self.assertEqual(
            static["display_capital"]["source"],
            static["source"]["paid_up_capital"],
        )

    def test_registry_document_uses_field_specific_source_labels(self):
        cdd = {
            "company_business_profile": {
                "customer_static": {
                    "name": "SC ENGINEERING PRIVATE LIMITED",
                    "jurisdiction": "SG",
                    "source": {},
                }
            }
        }
        extract = {
            "document_type": "registry_document",
            "company_status": "Live Company",
            "incorporation_date": "2014-02-20",
            "paid_up_capital": "SGD 250,000",
            "registered_address": {"full_address": "1 Demo Street, Singapore"},
            "extraction": {"document_path": "generated_documents/sc-engineering.pdf"},
        }

        applied = apply_document_extract_to_cdd(cdd, extract)

        static = cdd["company_business_profile"]["customer_static"]
        self.assertIn("incorporation_date", applied)
        self.assertIn("paid_up_capital", applied)
        self.assertEqual(
            static["source"]["incorporation_date"]["source"],
            REGISTRY_SOURCE_LABEL,
        )
        self.assertEqual(
            static["source"]["incorporation_date"]["field"],
            "Incorporation Date",
        )
        self.assertEqual(
            static["source"]["paid_up_capital"]["field"],
            "Paid-up Capital",
        )
        self.assertEqual(
            static["source"]["registered_address"]["field"],
            "Registered Office Address",
        )

    def test_registry_document_does_not_overwrite_api_capital(self):
        cdd = {
            "company_business_profile": {
                "customer_static": {
                    "name": "Ubizense Limited",
                    "jurisdiction": "HK",
                    "display_capital": {
                        "label": "Paid-up Capital",
                        "value": "HKD 10,000",
                        "source": {
                            "api": "KYC.com GET /v2/Companies/456",
                            "field": "Share Capital",
                        },
                    },
                    "source": {
                        "paid_up_capital": {
                            "api": "KYC.com GET /v2/Companies/456",
                            "field": "Share Capital",
                        }
                    },
                }
            }
        }
        extract = {
            "document_type": "registry_document",
            "paid_up_capital": "HKD 500,000",
            "registered_address": {"full_address": "1 Demo Road"},
            "extraction": {"document_path": "generated_documents/demo.pdf"},
        }

        applied = apply_document_extract_to_cdd(cdd, extract)

        static = cdd["company_business_profile"]["customer_static"]
        self.assertNotIn("paid_up_capital", applied)
        self.assertEqual(static["display_capital"]["value"], "HKD 10,000")

    def test_registry_document_node_records_s3_link_in_documents_and_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "registry.pdf"
            html_path = Path(tmp) / "registry.html"
            json_path = Path(tmp) / "registry.json"
            for path in (pdf_path, html_path, json_path):
                path.write_text("demo", encoding="utf-8")
            artifact = {
                "document_type": "registry_document",
                "source": REGISTRY_SOURCE_LABEL,
                "pdf_path": str(pdf_path),
                "html_path": str(html_path),
                "json_path": str(json_path),
                "generated_at": "2026-07-12T00:00:00+00:00",
            }
            document = {
                "name": "registry.pdf",
                "category": "registry_document",
                "url": "https://onbo-bkt.s3.us-east-1.amazonaws.com/generated_documents/case-123/registry_document/registry.pdf",
                "path": str(pdf_path),
                "source": REGISTRY_SOURCE_LABEL,
                "storage": {
                    "provider": "s3",
                    "bucket": "onbo-bkt",
                    "key": "generated_documents/case-123/registry_document/registry.pdf",
                    "url": "https://onbo-bkt.s3.us-east-1.amazonaws.com/generated_documents/case-123/registry_document/registry.pdf",
                },
            }

            with patch(
                "src.agents.nodes.generate_registry_document",
                return_value=artifact,
            ), patch(
                "src.agents.nodes.upload_document_to_s3",
                return_value=document,
            ):
                update = generate_registry_document_node(
                    {
                        "metadata": {"kyc_case": {"case_id": 123}},
                        "cdd": {},
                    }
                )

            self.assertEqual(update["documents"][0]["url"], document["url"])
            self.assertEqual(update["documents"][0]["collected_at"], artifact["generated_at"])
            evidence_artifact = update["evidence"][0]["data"]
            self.assertEqual(evidence_artifact["s3_url"], document["url"])
            self.assertEqual(evidence_artifact["storage"], document["storage"])
            self.assertTrue(pdf_path.exists())
            self.assertTrue(html_path.exists())
            self.assertTrue(json_path.exists())

    def test_extract_registry_document_deletes_local_artifacts_after_s3_upload(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "registry.pdf"
            html_path = Path(tmp) / "registry.html"
            json_path = Path(tmp) / "registry.json"
            for path in (pdf_path, html_path, json_path):
                path.write_text("demo", encoding="utf-8")
            artifact = {
                "document_type": "registry_document",
                "source": REGISTRY_SOURCE_LABEL,
                "pdf_path": str(pdf_path),
                "html_path": str(html_path),
                "json_path": str(json_path),
                "generated_at": "2026-07-12T00:00:00+00:00",
                "s3_url": "https://onbo-bkt.s3.us-east-1.amazonaws.com/generated_documents/case-123/registry_document/registry.pdf",
            }

            with patch(
                "src.agents.nodes.classify_document",
                return_value={"document_type": "registry_document", "confidence": 0.99},
            ), patch(
                "src.agents.nodes.extract_document",
                return_value={"document_type": "registry_document"},
            ):
                update = extract_registry_document(
                    {
                        "evidence": [
                            {
                                "tool": "generate_registry_document",
                                "data": artifact,
                            }
                        ]
                    }
                )

            evidence_data = update["evidence"][0]["data"]
            self.assertEqual(
                sorted(evidence_data["deleted_local_paths"]),
                sorted([str(pdf_path), str(html_path), str(json_path)]),
            )
            self.assertFalse(pdf_path.exists())
            self.assertFalse(html_path.exists())
            self.assertFalse(json_path.exists())

    def test_registry_document_node_records_skipped_s3_upload_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "registry.pdf"
            html_path = Path(tmp) / "registry.html"
            json_path = Path(tmp) / "registry.json"
            for path in (pdf_path, html_path, json_path):
                path.write_text("demo", encoding="utf-8")
            artifact = {
                "document_type": "registry_document",
                "source": REGISTRY_SOURCE_LABEL,
                "pdf_path": str(pdf_path),
                "html_path": str(html_path),
                "json_path": str(json_path),
                "generated_at": "2026-07-12T00:00:00+00:00",
            }

            with patch(
                "src.agents.nodes.generate_registry_document",
                return_value=artifact,
            ), patch(
                "src.agents.nodes.upload_document_to_s3",
                return_value=None,
            ), patch(
                "src.agents.nodes.s3_upload_skip_reason",
                return_value="missing AWS credential env vars: AWS_ACCESS_KEY_ID",
            ):
                update = generate_registry_document_node({"cdd": {}})

            self.assertNotIn("documents", update)
            evidence_artifact = update["evidence"][0]["data"]
            self.assertEqual(evidence_artifact["storage"]["status"], "skipped")
            self.assertEqual(
                evidence_artifact["storage"]["reason"],
                "missing AWS credential env vars: AWS_ACCESS_KEY_ID",
            )
            self.assertTrue(pdf_path.exists())
            self.assertTrue(html_path.exists())
            self.assertTrue(json_path.exists())


if __name__ == "__main__":
    unittest.main()
