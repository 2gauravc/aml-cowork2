"""Coverage for standalone digital-footprint research."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from src.tools.digital_footprint import (
    DIGITAL_FOOTPRINT_SCHEMA,
    DigitalFootprintError,
    evaluate_digital_footprint,
    load_digital_footprint_definition,
    normalize_digital_footprint_evidence,
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

    def test_skill_front_matter_rejects_unsupported_renderer(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".md") as skill:
            skill.write("---\nname: test\noutput:\n  sections:\n    - id: bad\n      title: Bad\n      type: list\n---\nInstructions")
            skill.flush()
            with self.assertRaisesRegex(DigitalFootprintError, "unsupported section type"):
                load_digital_footprint_definition(skill.name)

    def test_assessment_uses_strict_schema_and_preserves_sources(self) -> None:
        response = Mock()
        response.output_text = json.dumps(_result())
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
        self.assertIn("## Protected evidence safeguards", request["input"][0]["content"][0]["text"])
        self.assertIn("## Protected core assessment requirements", request["input"][0]["content"][0]["text"])
        self.assertIn("Configured output sections", request["input"][0]["content"][0]["text"])
        self.assertIn("custom_sections", request["text"]["format"]["schema"]["required"])

    def test_rejects_unsupported_source_references(self) -> None:
        invalid = _result()
        invalid["assessment"]["dimensions"]["identity_verifiability"]["source_refs"] = ["source:missing"]
        response = Mock(output_text=json.dumps(invalid))
        client = Mock()
        client.responses.create.return_value = response
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}), patch("src.tools.digital_footprint.search_digital_footprint", return_value=[{"id": "source:1", "url": "https://example.test"}]), patch("src.tools.digital_footprint.OpenAI", return_value=client):
            with self.assertRaisesRegex(DigitalFootprintError, "unknown sources"):
                evaluate_digital_footprint("Example Ltd")

    def test_skill_front_matter_drives_sections_and_normalizes_state_evidence(self) -> None:
        definition = load_digital_footprint_definition()
        self.assertEqual(
            [section["id"] for section in definition["sections"]],
            ["presence_and_visibility", "business_profile_consistency", "commercial_relationships", "adverse_news", "evidence_gaps_and_actions"],
        )
        result = _result()
        result.update({"sources": [{"id": "source:1", "url": "https://example.test"}], "company_inputs": {"company_name": "Example Ltd"}, "queries": ["Example Ltd"], "skill_path": "skill", "section_manifest": definition["sections"], "evaluated_at": "2026-01-01T00:00:00+00:00"})
        evidence = normalize_digital_footprint_evidence(result)
        self.assertEqual(evidence["tool"], "digital_footprint")
        self.assertIn("custom_sections", evidence["data"])


def _result() -> dict:
    sections = load_digital_footprint_definition()["sections"]
    generated = []
    for section in sections:
        if section["type"] == "table":
            content = {"columns": ["Dimension", "Assessment"], "rows": [{"cells": ["Evidence", "Limited"], "source_refs": ["source:1"]}]}
        else:
            content = {"text": "Evidence-backed synthesis."} if section["type"] == "narrative" else {"items": [{"finding": "Evidence-backed finding.", "source_refs": ["source:1"]}]}
        generated.append({"id": section["id"], "type": section["type"], "title": section["title"], "content": content, "source_refs": ["source:1"]})
    return {"assessment": {"footprint_strength": "inconclusive", "confidence": "low", "dimensions": {key: {"rating": "inconclusive", "rationale": "Limited evidence.", "source_refs": []} for key in ("identity_verifiability", "business_substantiation", "operational_presence", "commercial_ecosystem", "consistency_with_company_inputs")}, "adverse_news": {"status": "inconclusive", "confidence": "low", "items": [], "search_coverage_limitations": ["Limited coverage."], "source_refs": []}, "limitations": ["Limited evidence."], "review_items": [], "recommended_actions": []}, "business_footprint": {"nature_of_business": {"claimed": "", "publicly_observed": "", "consistency": "unavailable", "source_refs": []}, "products_services": [], "operating_geographies": [], "customer_segments": [], "counterparties": [], "suppliers_and_supply_chain": [], "official_channels": []}, "custom_sections": generated}


if __name__ == "__main__":
    unittest.main()
