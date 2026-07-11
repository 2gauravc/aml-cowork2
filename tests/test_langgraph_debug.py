import json
import os
import tempfile
import unittest
from pathlib import Path

from utils.langgraph_debug import maybe_debug_node


class LangGraphDebugTests(unittest.TestCase):
    def setUp(self):
        self._old_env = {
            key: os.environ.get(key)
            for key in ("CDD_DEBUG", "CDD_DEBUG_FILE", "CDD_DEBUG_DIR")
        }

    def tearDown(self):
        for key, value in self._old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_debug_node_writes_jsonl_with_diff_and_redaction(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "debug.jsonl"
            os.environ["CDD_DEBUG"] = "true"
            os.environ["CDD_DEBUG_FILE"] = str(log_path)

            def sample_node(state):
                return {
                    "metadata": {
                        "customer": {"name": "Example Ltd"},
                        "client_secret": "should-not-log",
                    },
                    "evidence": [{"tool": "sample"}],
                }

            wrapped = maybe_debug_node("fetch_customer_static", sample_node)
            result = wrapped({"metadata": {"customer": {"name": "Old"}}, "token": "abc"})

            self.assertEqual(result["evidence"][0]["tool"], "sample")
            rows = [json.loads(line) for line in log_path.read_text().splitlines()]
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["node"], "fetch_customer_static")
            self.assertEqual(row["tools_or_functions"], ["_fetch_customer_static"])
            self.assertEqual(row["incoming_state"]["token"], "[REDACTED]")
            self.assertEqual(
                row["outgoing_update"]["metadata"]["client_secret"],
                "[REDACTED]",
            )
            self.assertIn("metadata", row["state_diff"])
            self.assertIsNone(row["error"])

    def test_debug_disabled_returns_original_function(self):
        os.environ["CDD_DEBUG"] = "false"

        def sample_node(state):
            return {}

        self.assertIs(maybe_debug_node("sample", sample_node), sample_node)


if __name__ == "__main__":
    unittest.main()
