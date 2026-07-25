"""Coverage for the additive Adverse News Screening node."""

from __future__ import annotations

import asyncio
import os
import unittest
from unittest.mock import patch

from src.agents.nodes import adverse_news_screening
from src.backend.app import IndependentAdverseNewsRequest, assess_independent_adverse_news
from src.tools.adverse_news import AdverseNewsError, _assessment_schema, build_search_queries, entities_for_screening, load_adverse_news_definition, load_finding_schema, search_adverse_news


class AdverseNewsTests(unittest.TestCase):
    def test_skill_and_shared_schema_declare_the_expected_contracts(self) -> None:
        definition = load_adverse_news_definition()
        schema = load_finding_schema()

        self.assertEqual(definition["overlay"]["schema"], "adverse_news/v1")
        self.assertEqual(definition["input"]["search_terms"], 'enforcement OR investigation OR fraud OR bribery OR corruption OR "money laundering" OR sanctions OR watchlist')
        self.assertIn("multiple independent sources materially corroborate", definition["instructions"])
        self.assertEqual(schema["$id"], "finding/v1")
        self.assertIn("relevant_evidence_ids", schema["required"])

    def test_assessment_schema_includes_nested_adverse_news_requirements(self) -> None:
        definition = load_adverse_news_definition()
        schema = _assessment_schema(load_finding_schema(), definition["overlay"])
        overlay = schema["properties"]["findings"]["items"]["properties"]["adverse_news"]

        self.assertEqual(overlay["required"], definition["overlay"]["required"])
        self.assertFalse(overlay["additionalProperties"])
        self.assertEqual(set(overlay["properties"]["screened_entity"]["properties"]), {"entity_type", "name_used", "disambiguators_used"})
        self.assertEqual(overlay["properties"]["screened_entity"]["properties"]["entity_type"], {"type": "string"})
        self.assertEqual(overlay["properties"]["screening_coverage"]["properties"]["limitations"]["type"], "array")
        self.assertEqual(overlay["properties"]["identity_match"]["required"], ["status", "confidence", "rationale"])
        self.assertEqual(overlay["properties"]["screening_coverage"]["required"], ["queries", "source_evidence_ids", "limitations"])
        self.assertEqual(schema["properties"]["assessment"]["required"], ["outcome", "summary", "limitations", "entity_outcomes"])

    def test_entity_selection_uses_company_directors_and_ubos(self) -> None:
        entities = entities_for_screening(
            {
                "company_business_profile": {"customer_static": {"name": "Example Ltd", "jurisdiction": "GB"}},
                "ownership_and_control": {
                    "members": {
                        "controlling_members": [
                            {"name": "Director Doe", "role": "Director", "case_common_id": "director-1"},
                            {"name": "DIRECTOR DOE", "role": "Director", "case_common_id": "director-2"},
                            {"name": "Secretary Doe", "role": "Secretary", "case_common_id": "secretary-1"},
                            {"name": "Audit PAC", "role": "Auditor", "case_common_id": "auditor-1"},
                        ]
                    },
                    "ubos": [{"name": "Owner Doe", "case_common_id": "ubo-1"}],
                },
            }
        )

        self.assertEqual([entity["entity_type"] for entity in entities], ["company", "company_director", "ultimate_beneficial_owner"])
        self.assertEqual([entity["name"] for entity in entities], ["Example Ltd", "Director Doe", "Owner Doe"])

    def test_brave_query_uses_exact_name_and_boolean_adverse_terms(self) -> None:
        definition = load_adverse_news_definition()
        query = build_search_queries([{"key": "ubo:0", "name": "Leonardo DiCaprio", "disambiguators": {}}], definition["input"]["search_terms"])[0]["query"]

        self.assertEqual(query, '"Leonardo DiCaprio" AND (enforcement OR investigation OR fraud OR bribery OR corruption OR "money laundering" OR sanctions OR watchlist)')

    def test_brave_query_uses_the_skill_configured_terms(self) -> None:
        query = build_search_queries([{"key": "ubo:0", "name": "Alex Chen", "disambiguators": {}}], "sanctions OR watchlist")[0]["query"]

        self.assertEqual(query, '"Alex Chen" AND (sanctions OR watchlist)')

    def test_skill_requires_non_empty_search_terms_input(self) -> None:
        definition = load_adverse_news_definition()
        with patch("src.tools.adverse_news.yaml.safe_load", return_value={"assessment": definition["assessment"], "output": definition["overlay"]}):
            with self.assertRaisesRegex(AdverseNewsError, "input.search_terms"):
                load_adverse_news_definition()

    @patch("src.tools.adverse_news.requests.get")
    def test_brave_results_are_normalized_with_required_header(self, request_get) -> None:
        response = request_get.return_value
        response.json.return_value = {"web": {"results": [{"title": "Regulatory notice", "url": "https://example.test/notice", "description": "Summary", "extra_snippets": ["Detail"], "page_age": "2025-01-23"}]}}
        with patch.dict(os.environ, {"BRAVE_API_KEY": "test-key"}, clear=False):
            results = search_adverse_news([{"entity_key": "ubo:0", "query": "query"}])

        self.assertEqual(results[0]["content"], "Summary\nDetail")
        self.assertEqual(results[0]["published_date"], "2025-01-23")
        self.assertEqual(request_get.call_args.kwargs["headers"]["X-Subscription-Token"], "test-key")

    def test_brave_key_is_required(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(Exception, "BRAVE_API_KEY"):
                search_adverse_news([])

    @patch("src.agents.nodes.screen_adverse_news")
    def test_node_adds_evidence_and_a_valid_finding_without_risk_flags(self, screening) -> None:
        screening.return_value = {
            "entities": [{"key": "ultimate_beneficial_owner:0", "entity_type": "ultimate_beneficial_owner", "entity_id": "ubo-1", "name": "Alex Chen", "disambiguators": {"nationality": "Singapore"}}],
            "queries": [{"entity_key": "ultimate_beneficial_owner:0", "query": "Alex Chen enforcement"}],
            "sources": [{"id": "source:1", "entity_key": "ultimate_beneficial_owner:0", "query": "Alex Chen enforcement", "title": "Regulatory notice", "url": "https://example.test/notice", "content": "Notice", "published_date": "2024-05-10"}],
            "assessment": {"outcome": "completed_no_material_findings", "summary": "A material potential match requires review.", "limitations": ["Identity remains ambiguous."], "entity_outcomes": [{"entity_key": "ultimate_beneficial_owner:0", "summary": "Potential match retained for review.", "limitations": ["Identity remains ambiguous."]}]},
            "drafts": [_draft()],
            "definition": {"path": "skills/adverse-news-screening/SKILL.md", "overlay": load_adverse_news_definition()["overlay"]},
            "evaluated_at": "2026-07-24T10:00:00+00:00",
        }

        result = adverse_news_screening({"cdd": {}})

        self.assertNotIn("risk_flags", result)
        self.assertEqual(len(result["findings"]), 1)
        finding = result["findings"][0]
        self.assertEqual(finding["category"], "adverse_news")
        self.assertEqual(finding["subject"]["name"], "Alex Chen")
        self.assertEqual(finding["adverse_news"]["screened_entity"]["name_used"], "Alex Chen")
        self.assertEqual(finding["adverse_news"]["screening_coverage"]["queries"], ["Alex Chen enforcement"])
        self.assertEqual(finding["adverse_news"]["screening_coverage"]["source_evidence_ids"], finding["relevant_evidence_ids"])
        self.assertEqual(result["evidence"][0]["source"], "Brave Search")
        assessment = result["adverse_news_assessments"][0]
        self.assertEqual(assessment["outcome"], "completed_with_findings")
        self.assertEqual(assessment["source_evidence_ids"], finding["relevant_evidence_ids"])
        evidence_ids = {item["evidence_id"] for item in result["evidence"]}
        self.assertTrue(set(finding["relevant_evidence_ids"]) <= evidence_ids)

    @patch("src.agents.nodes.screen_adverse_news")
    def test_node_records_a_no_hit_assessment_without_a_finding(self, screening) -> None:
        screening.return_value = {
            "entities": [{"key": "company:0", "entity_type": "company", "name": "Example Ltd", "disambiguators": {}}],
            "queries": [{"entity_key": "company:0", "query": "Example Ltd adverse news"}],
            "sources": [],
            "assessment": {"outcome": "completed_no_material_findings", "summary": "The retained results did not identify material attributable adverse news.", "limitations": ["Public-web coverage is limited."], "entity_outcomes": [{"entity_key": "company:0", "summary": "No material attributable adverse news was identified in retained results.", "limitations": ["Public-web coverage is limited."]}]},
            "drafts": [],
            "definition": {"path": "skills/adverse-news-screening/SKILL.md", "overlay": load_adverse_news_definition()["overlay"]},
            "evaluated_at": "2026-07-24T10:00:00+00:00",
        }

        result = adverse_news_screening({"cdd": {}})

        self.assertEqual(result["findings"], [])
        assessment = result["adverse_news_assessments"][0]
        self.assertEqual(assessment["outcome"], "completed_no_material_findings")
        self.assertEqual(assessment["screened_entities"][0]["name"], "Example Ltd")

    @patch("src.agents.nodes.screen_adverse_news", side_effect=AdverseNewsError("BRAVE_API_KEY is required"))
    def test_node_records_an_unavailable_assessment(self, screening) -> None:
        result = adverse_news_screening({"cdd": {}})

        self.assertEqual(result["findings"], [])
        self.assertEqual(result["adverse_news_assessments"][0]["outcome"], "unavailable")
        self.assertIn("BRAVE_API_KEY", result["adverse_news_assessments"][0]["limitations"][0])

    @patch("src.agents.nodes.screen_adverse_news", side_effect=Exception("unexpected"))
    def test_node_does_not_hide_unexpected_errors(self, screening) -> None:
        with self.assertRaisesRegex(Exception, "unexpected"):
            adverse_news_screening({"cdd": {}})

    def test_independent_check_uses_screening_without_mutating_cdd_state(self) -> None:
        async def run_inline(function, *args):
            return function(*args)

        with patch("src.backend.app.adverse_news_screening", return_value={"evidence": [], "findings": []}) as screening, patch("src.backend.app.asyncio.to_thread", side_effect=run_inline):
            result = asyncio.run(assess_independent_adverse_news(IndependentAdverseNewsRequest(entity_names=["Alpha Ltd", "Beta Ltd"])))

        self.assertEqual(result, {"evidence": [], "findings": []})
        state = screening.call_args.args[0]
        self.assertEqual(state["cdd"]["ownership_and_control"]["ubos"], [{"name": "Alpha Ltd"}, {"name": "Beta Ltd"}])


def _draft() -> dict:
    return {
        "entity_key": "ultimate_beneficial_owner:0",
        "source_refs": ["source:1"],
        "title": "Potential regulatory matter involving UBO",
        "summary": "A public regulatory notice may concern the UBO.",
        "confidence": {"level": "medium", "rationale": "Name and nationality align.", "limitations": ["No date of birth in source."]},
        "severity": {"level": "high", "rationale": "Potential enforcement exposure."},
        "potential_impact_risk": "The relationship could create regulatory and reputational exposure.",
        "recommended_action_rfi": {"internal_actions": ["Verify the authoritative notice."], "rfi": [{"request": "Explain the matter.", "reason": "Confirm identity and status.", "priority": "high"}]},
        "adverse_news": {
            "screened_entity": {"entity_type": "ultimate_beneficial_owner", "name_used": "Alex Chen", "disambiguators_used": {"nationality": "Singapore"}},
            "identity_match": {"status": "ambiguous", "confidence": "medium", "rationale": "Name and nationality align."},
            "adverse_event": {"event_category": "enforcement_action", "summary": "Potential regulatory notice.", "legal_or_procedural_status": "Unconfirmed.", "event_date": "2024-05-10", "jurisdiction": "Singapore"},
            "screening_coverage": {"queries": ["Alex Chen enforcement"], "source_evidence_ids": [], "limitations": ["Identity not confirmed."]},
        },
    }
