import os
import unittest
from unittest.mock import patch

from src.agents.graph import _document_progress_message, _progress_node
from src.agents.graph import PIPELINE_NODE_LABELS


class PipelineProgressTests(unittest.TestCase):
    def setUp(self):
        self.previous_minimum = os.environ.get("CDD_PIPELINE_NODE_MIN_SECONDS")
        os.environ["CDD_PIPELINE_NODE_MIN_SECONDS"] = "0"

    def tearDown(self):
        if self.previous_minimum is None:
            os.environ.pop("CDD_PIPELINE_NODE_MIN_SECONDS", None)
        else:
            os.environ["CDD_PIPELINE_NODE_MIN_SECONDS"] = self.previous_minimum

    def test_fetch_node_reports_cache_use_and_position(self):
        updates = []
        wrapped = _progress_node(
            "fetch_org_chart",
            lambda state: {"evidence": []},
            updates.append,
        )
        state = {"metadata": {"kyc_case": {"case_id": 42}}}

        with patch("src.agents.graph.get_cache_source", return_value="s3"):
            self.assertEqual(wrapped(state), {"evidence": []})

        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0]["node"], "fetch_org_chart")
        self.assertEqual(updates[0]["node_number"], 5)
        self.assertEqual(updates[0]["total_nodes"], 27)
        self.assertTrue(updates[0]["using_cache"])
        self.assertEqual(updates[0]["cache_source"], "s3")
        self.assertEqual(updates[0]["status"], "running")

    def test_final_pipeline_step_counts_cdd_finalization(self):
        self.assertEqual(list(PIPELINE_NODE_LABELS).index("assess_shell_company_risk") + 1, 24)
        self.assertEqual(list(PIPELINE_NODE_LABELS).index("assess_other_risk_factors") + 1, 25)
        self.assertEqual(list(PIPELINE_NODE_LABELS).index("assess_risk_rating") + 1, 26)
        self.assertEqual(
            PIPELINE_NODE_LABELS["finalize_cdd"],
            "Completing CDD",
        )
        updates = []
        wrapped = _progress_node("finalize_cdd", lambda state: state, updates.append)

        self.assertEqual(wrapped({}), {})
        self.assertEqual(updates[0]["node_number"], 27)
        self.assertEqual(updates[0]["total_nodes"], 27)

    def test_failed_node_reports_error_before_reraising(self):
        updates = []

        def failing_node(state):
            raise ValueError("registry unavailable")

        wrapped = _progress_node("fetch_members", failing_node, updates.append)
        with self.assertRaisesRegex(ValueError, "registry unavailable"):
            wrapped({"metadata": {"kyc_case": {"case_id": 42}}})

        self.assertEqual(updates[-1]["status"], "error")
        self.assertEqual(updates[-1]["error"], "registry unavailable")

    def test_document_status_reports_the_actual_cache_outcome(self):
        self.assertEqual(
            _document_progress_message(
                "generate_registry_document",
                {"evidence": [{"data": {"reused_from_s3": True}}]},
            ),
            "Locating Business Profile Document — found in cache",
        )
        self.assertEqual(
            _document_progress_message(
                "generate_idv_documents",
                {"evidence": [{"data": {"artifacts": [{"reused_from_s3": True}, {}]}}]},
            ),
            "Locating document — found in cache; generating missing documents",
        )
        self.assertEqual(
            _document_progress_message(
                "generate_idv_documents",
                {"evidence": [{"data": {"artifacts": [{}]}}]},
            ),
            "Locating document — not found, generating",
        )


if __name__ == "__main__":
    unittest.main()
