import os
import unittest
from unittest.mock import patch

from src.agents.graph import _progress_node


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

        with patch("src.agents.graph.get_cache_value", return_value={"cached": True}):
            self.assertEqual(wrapped(state), {"evidence": []})

        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0]["node"], "fetch_org_chart")
        self.assertEqual(updates[0]["node_number"], 4)
        self.assertEqual(updates[0]["total_nodes"], 15)
        self.assertTrue(updates[0]["using_cache"])
        self.assertEqual(updates[0]["status"], "running")

    def test_failed_node_reports_error_before_reraising(self):
        updates = []

        def failing_node(state):
            raise ValueError("registry unavailable")

        wrapped = _progress_node("fetch_members", failing_node, updates.append)
        with self.assertRaisesRegex(ValueError, "registry unavailable"):
            wrapped({"metadata": {"kyc_case": {"case_id": 42}}})

        self.assertEqual(updates[-1]["status"], "error")
        self.assertEqual(updates[-1]["error"], "registry unavailable")


if __name__ == "__main__":
    unittest.main()
