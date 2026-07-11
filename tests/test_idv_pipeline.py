import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.agents.nodes import (
    establish_idv_requirements,
    extract_idv_documents,
    generate_idv_documents_node,
)
from src.agents.businesslogic import build_ownership_tables
from src.tools.idv_requirements import establish_idv_requirements as apply_requirements
from src.utils.idv_document_pipeline import generate_idv_document


POLICY = {
    "policy_name": "ID&V for UBOs and directors",
    "required_for": ["ubo", "director"],
    "accepted_documents": ["passport", "national_id"],
    "minimum_documents_per_individual": 1,
    "notes": "Demo policy",
}


class IDVPipelineTests(unittest.TestCase):
    def test_idv_requirements_dedupe_ubo_and_director(self):
        cdd = {
            "ownership_and_control": {
                "ubos": [
                    {
                        "name": "Jane Demo",
                        "case_common_id": "p1",
                        "effective_shareholding_percent": 40,
                    }
                ],
                "related_parties": [
                    {
                        "name": "Jane Demo",
                        "case_common_id": "p1",
                        "role": "Director",
                        "related_entity": "DemoCo",
                    },
                    {
                        "name": "Sam Other",
                        "case_common_id": "p2",
                        "role": "Director",
                        "related_entity": "DemoCo",
                    },
                ],
            }
        }

        idv = apply_requirements(cdd, POLICY)

        self.assertEqual(len(idv["required_individuals"]), 2)
        jane = next(row for row in idv["required_individuals"] if row["name"] == "Jane Demo")
        self.assertEqual(jane["roles"], ["UBO", "Director"])
        self.assertEqual(jane["required_documents"], ["passport", "national_id"])
        self.assertEqual(jane["status"], "required")

    def test_idv_requirements_merge_name_only_ubo_with_id_director(self):
        cdd = {
            "ownership_and_control": {
                "ubos": [
                    {
                        "name": "Jane Demo",
                        "effective_shareholding_percent": 40,
                    }
                ],
                "related_parties": [
                    {
                        "name": "Jane Demo",
                        "case_common_id": "p1",
                        "role": "Director",
                        "related_entity": "DemoCo",
                    }
                ],
            }
        }

        idv = apply_requirements(cdd, POLICY)

        self.assertEqual(len(idv["required_individuals"]), 1)
        person = idv["required_individuals"][0]
        self.assertEqual(person["name"], "Jane Demo")
        self.assertEqual(person["case_common_id"], "p1")
        self.assertEqual(person["roles"], ["UBO", "Director"])

    def test_ownership_tables_preserve_ubo_case_common_id(self):
        result = build_ownership_tables(
            {
                "org_chart": {
                    "name": "DemoCo",
                    "shareholders": [
                        {
                            "name": "Jane Demo",
                            "case_common_id": "p1",
                            "nationality_id": 1,
                            "ownership": {"effective_percentage": 40},
                        }
                    ],
                }
            }
        )

        self.assertEqual(result["ubos"][0]["case_common_id"], "p1")

    def test_generate_idv_document_creates_passport_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact = generate_idv_document(
                {
                    "name": "Jane Demo",
                    "case_common_id": "p1",
                    "selected_document_type": "passport",
                },
                output_dir=Path(tmp),
            )

            self.assertEqual(artifact["document_type"], "passport")
            self.assertTrue(Path(artifact["pdf_path"]).exists())
            self.assertTrue(Path(artifact["html_path"]).exists())
            self.assertTrue(Path(artifact["json_path"]).exists())

    def test_idv_nodes_populate_verified_documents(self):
        state = {
            "cdd": {
                "ownership_and_control": {
                    "status": "complete",
                    "ubos": [{"name": "Jane Demo", "case_common_id": "p1"}],
                    "related_parties": [],
                }
            },
            "evidence": [],
        }
        with tempfile.TemporaryDirectory() as tmp, patch(
            "src.agents.nodes.interpret_idv_policy",
            return_value=POLICY,
        ), patch(
            "src.agents.nodes.generate_idv_documents",
            side_effect=lambda individuals: [
                generate_idv_document(individuals[0], output_dir=Path(tmp))
            ],
        ), patch(
            "src.tools.document_extraction._run_schema_prompt",
            side_effect=[
                {
                    "document_type": "passport",
                    "confidence": 0.99,
                    "reason": "Passport document",
                },
                {
                    "document_type": "passport",
                    "full_name": "Jane Demo",
                    "document_number": "P12345678",
                    "nationality": "GB",
                    "date_of_birth": "1980-01-01",
                    "expiry_date": "2030-01-01",
                    "issuing_country": "GB",
                },
            ],
        ):
            update = establish_idv_requirements(state)
            state["cdd"] = update["cdd"]
            state["evidence"].extend(update["evidence"])

            update = generate_idv_documents_node(state)
            state["evidence"].extend(update["evidence"])

            update = extract_idv_documents(state)

        idv = update["cdd"]["individual_identity_verification"]
        person = idv["required_individuals"][0]
        self.assertEqual(idv["status"], "complete")
        self.assertEqual(person["status"], "verified")
        self.assertEqual(person["document"]["document_number"], "P12345678")
        self.assertEqual(person["document"]["source"], "Passport Document")


if __name__ == "__main__":
    unittest.main()
