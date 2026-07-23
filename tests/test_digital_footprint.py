"""Coverage for standalone digital-footprint research."""

from __future__ import annotations

import json
import os
import unittest
from unittest.mock import Mock, patch

from src.tools.digital_footprint import (
    DIGITAL_FOOTPRINT_SCHEMA,
    DigitalFootprintError,
    evaluate_digital_footprint,
    search_digital_footprint,
)


class DigitalFootprintTests(unittest.TestCase):
    def test_search_retains_query_and_deduplicates_urls(self) -> None:
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"results": [{"title": "Example", "url": "https://example.test", "content": "Evidence"}]}
        with patch.dict(os.environ, {"TAVILY_API_KEY": "test"}), patch("src.tools.digital_footprint.requests.post", return_value=response):
            sources = search_digital_footprint(["Example Ltd services", "Example Ltd news"])
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["id"], "source:1")
        self.assertEqual(sources[0]["query"], "Example Ltd services")

    def test_missing_search_key_is_clear(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(DigitalFootprintError, "TAVILY_API_KEY"):
                search_digital_footprint(["Example Ltd"])

    def test_missing_openai_key_is_clear(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(DigitalFootprintError, "OPENAI_API_KEY"):
                evaluate_digital_footprint("Example Ltd")

    def test_assessment_uses_strict_schema_and_preserves_sources(self) -> None:
        response = Mock()
        response.output_text = json.dumps({"assessment": {"footprint_strength": "inconclusive", "confidence": "low", "dimensions": {key: {"rating": "inconclusive", "rationale": "Limited evidence.", "source_refs": []} for key in ("identity_verifiability", "business_substantiation", "operational_presence", "commercial_ecosystem", "consistency_with_company_inputs")}, "adverse_news": {"status": "inconclusive", "confidence": "low", "items": [], "search_coverage_limitations": ["Limited coverage."], "source_refs": []}, "limitations": ["Limited evidence."], "review_items": [], "recommended_actions": []}, "business_footprint": {"nature_of_business": {"claimed": "", "publicly_observed": "", "consistency": "unavailable", "source_refs": []}, "products_services": [], "operating_geographies": [], "customer_segments": [], "counterparties": [], "suppliers_and_supply_chain": [], "official_channels": []}})
        client = Mock()
        client.responses.create.return_value = response
        source = {"id": "source:1", "url": "https://example.test", "query": "Example Ltd", "title": "Example", "content": "Evidence"}
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}), patch("src.tools.digital_footprint.search_digital_footprint", return_value=[source]), patch("src.tools.digital_footprint.OpenAI", return_value=client):
            result = evaluate_digital_footprint("Example Ltd", jurisdiction="GB")
        self.assertEqual(result["sources"], [source])
        request = client.responses.create.call_args.kwargs
        self.assertTrue(request["text"]["format"]["strict"])
        self.assertEqual(request["text"]["format"]["schema"], DIGITAL_FOOTPRINT_SCHEMA)
        self.assertIn("# Digital Footprint Assessment", request["input"][0]["content"][0]["text"])

    def test_rejects_unsupported_source_references(self) -> None:
        invalid = {"assessment": {"footprint_strength": "weak", "confidence": "low", "dimensions": {key: {"rating": "weak", "rationale": "Unverified.", "source_refs": ["source:missing"]} for key in ("identity_verifiability", "business_substantiation", "operational_presence", "commercial_ecosystem", "consistency_with_company_inputs")}, "adverse_news": {"status": "inconclusive", "confidence": "low", "items": [], "search_coverage_limitations": [], "source_refs": []}, "limitations": [], "review_items": [], "recommended_actions": []}, "business_footprint": {"nature_of_business": {"claimed": "", "publicly_observed": "", "consistency": "unavailable", "source_refs": []}, "products_services": [], "operating_geographies": [], "customer_segments": [], "counterparties": [], "suppliers_and_supply_chain": [], "official_channels": []}}
        response = Mock(output_text=json.dumps(invalid))
        client = Mock()
        client.responses.create.return_value = response
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}), patch("src.tools.digital_footprint.search_digital_footprint", return_value=[{"id": "source:1", "url": "https://example.test"}]), patch("src.tools.digital_footprint.OpenAI", return_value=client):
            with self.assertRaisesRegex(DigitalFootprintError, "unknown sources"):
                evaluate_digital_footprint("Example Ltd")


if __name__ == "__main__":
    unittest.main()
