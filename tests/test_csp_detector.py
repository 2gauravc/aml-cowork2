"""Tests for the Tavily-backed CSP address detector."""

from __future__ import annotations

import os
import unittest
from unittest.mock import Mock, patch

from src.tools.csp_detector import evaluate_csp_address, search_address


class CSPDetectorTests(unittest.TestCase):
    def test_search_address_returns_compact_citations(self) -> None:
        response = Mock()
        response.json.return_value = {
            "results": [
                {
                    "title": "Example CSP",
                    "url": "https://example.test/csp",
                    "content": "Registered office services at this address.",
                    "score": 0.91,
                }
            ]
        }
        response.raise_for_status.return_value = None
        with patch.dict(os.environ, {"TAVILY_API_KEY": "test-key"}), patch(
            "src.tools.csp_detector.requests.post", return_value=response
        ) as post:
            result = search_address("1 Example Street", company_name="Example Ltd")

        self.assertIn('"1 Example Street"', result["query"])
        self.assertEqual(result["results"][0]["url"], "https://example.test/csp")
        self.assertNotIn("raw_content", result["results"][0])
        self.assertEqual(post.call_args.kwargs["json"]["max_results"], 5)

    def test_evaluate_address_combines_skill_search_and_structured_assessment(self) -> None:
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), patch(
            "src.tools.csp_detector.search_address",
            return_value={"query": "query", "results": [{"url": "https://example.test"}]},
        ), patch(
            "src.tools.csp_detector._assess_search_results",
            return_value={
                "is_csp": "yes",
                "confidence": "high",
                "explanation": "The provider advertises registered-office services at the address.",
            },
        ):
            result = evaluate_csp_address("1 Example Street", company_name="Example Ltd")

        self.assertEqual(result["assessment"]["is_csp"], "yes")
        self.assertEqual(result["sources"][0]["url"], "https://example.test")
        self.assertIn("evaluated_at", result)


if __name__ == "__main__":
    unittest.main()
