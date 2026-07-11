import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.cdd_enrichment import (
    apply_document_extract_to_cdd,
    missing_about_customer_fields,
)
from tools.document_extraction import classify_document, extract_document
from utils.document_pipeline import REGISTRY_SOURCE_LABEL, generate_registry_document


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
                "tools.document_extraction._run_schema_prompt",
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
            "extraction": {"document_path": "documents/demo.pdf"},
        }

        applied = apply_document_extract_to_cdd(cdd, extract)

        static = cdd["company_business_profile"]["customer_static"]
        self.assertNotIn("paid_up_capital", applied)
        self.assertEqual(static["display_capital"]["value"], "HKD 10,000")


if __name__ == "__main__":
    unittest.main()
