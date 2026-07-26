"""Coverage for the Digital Footprint evidence/assessment/findings contract."""
import json, os, tempfile, unittest
from unittest.mock import Mock, patch
from src.tools.digital_footprint import DIGITAL_FOOTPRINT_SCHEMA, DigitalFootprintError, _response_schema, build_search_queries, evaluate_digital_footprint, load_digital_footprint_definition, load_finding_schema, search_digital_footprint
from src.agents.nodes import digital_footprint_assessment

class DigitalFootprintTests(unittest.TestCase):
    def test_skill_defines_input_assessment_and_overlay(self):
        definition=load_digital_footprint_definition()
        self.assertEqual(definition["assessment"]["schema"], "digital_footprint_assessment/v2")
        self.assertEqual(definition["overlay"]["schema"], "digital_footprint/v1")
        self.assertTrue(definition["input"]["search_terms"])
        self.assertEqual([item["key"] for item in definition["assessment_definition"]["sections"][0]["dimensions"]], ["professional_website", "active_linkedin", "multiple_independent_references", "recent_business_activity", "evidence_of_operations"])

    def test_schema_uses_only_skill_declared_dimensions(self):
        definition = load_digital_footprint_definition()
        indicators = _response_schema(load_finding_schema(), definition["overlay"], definition["assessment_definition"])["properties"]["assessment"]["properties"]["presence_and_visibility"]["properties"]["indicators"]
        self.assertEqual(set(indicators["properties"]), {"professional_website", "active_linkedin", "multiple_independent_references", "recent_business_activity", "evidence_of_operations"})
        self.assertNotIn("basic_website", indicators["properties"])

    def test_skill_allows_an_optional_explicit_dimension_key(self):
        with tempfile.NamedTemporaryFile("w") as skill:
            skill.write("---\ninput: {search_terms: [website]}\nassessment:\n  schema: digital_footprint_assessment/v2\n  presence_and_visibility:\n    dimensions: [{id: official_site, label: Official website}]\noutput: {schema: digital_footprint/v1}\n---\nx")
            skill.flush()
            self.assertEqual(load_digital_footprint_definition(skill.name)["assessment_definition"]["sections"][0]["dimensions"], [{"key": "official_site", "label": "Official website"}])

    def test_query_terms_are_skill_inputs(self):
        self.assertEqual(build_search_queries("Example Ltd", search_terms=["services", "partners"]), ['"Example Ltd" services', '"Example Ltd" partners'])

    def test_search_retains_query_and_deduplicates_urls(self):
        response=Mock(); response.json.return_value={"results":[{"title":"Example","url":"https://example.test","content":"Evidence"}]}
        with patch.dict(os.environ,{"TAVILY_API_KEY":"test"}), patch("src.tools.digital_footprint.requests.post",return_value=response): sources=search_digital_footprint(["a","b"])
        self.assertEqual(len(sources),1); self.assertEqual(sources[0]["query"],"a")

    def test_missing_input_is_clear(self):
        with tempfile.NamedTemporaryFile("w") as skill:
            skill.write("---\nname: x\nassessment: {schema: digital_footprint_assessment/v1}\noutput: {schema: digital_footprint/v1}\n---\nx"); skill.flush()
            with self.assertRaisesRegex(DigitalFootprintError,"input.search_terms"): load_digital_footprint_definition(skill.name)

    def test_assessment_uses_strict_schema(self):
        response=Mock(); response.output_text=json.dumps(_result()); client=Mock(); client.responses.create.return_value=response
        source={"id":"source:1","url":"https://example.test","query":"Example","title":"Example","content":"Evidence"}
        with patch.dict(os.environ,{"OPENAI_API_KEY":"test"}), patch("src.tools.digital_footprint.search_digital_footprint",return_value=[source]), patch("src.tools.digital_footprint.OpenAI",return_value=client): result=evaluate_digital_footprint("Example Ltd")
        self.assertEqual(result["sources"],[source]); self.assertTrue(client.responses.create.call_args.kwargs["text"]["format"]["strict"]); self.assertEqual(client.responses.create.call_args.kwargs["text"]["format"]["schema"],DIGITAL_FOOTPRINT_SCHEMA)

    @patch("src.agents.nodes.evaluate_digital_footprint")
    def test_langgraph_node_returns_evidence_and_assessment(self, evaluate):
        evaluate.return_value={"sources":[{"id":"source:1","url":"https://example.test","title":"Example"}],"assessment":_result()["assessment"],"findings":[],"definition":load_digital_footprint_definition(),"company_inputs":{"company_name":"Example Ltd"},"queries":["Example"],"evaluated_at":"2026-07-25T00:00:00+00:00"}
        result=digital_footprint_assessment({"digital_footprint_inputs":{"company_name":"Example Ltd"}})
        self.assertEqual(result["evidence"][0]["tool"],"digital_footprint_assessment")
        self.assertEqual(result["assessments"][0]["company_inputs"]["company_name"],"Example Ltd")
        self.assertEqual(result["assessments"][0]["assessment_type"], "digital_footprint")
        self.assertEqual(result["assessments"][0]["definition"]["schema_version"], "digital_footprint_assessment/v2")
        self.assertNotIn("cdd_section", evaluate.call_args.kwargs)

    @patch("src.agents.nodes.evaluate_digital_footprint")
    def test_langgraph_node_does_not_forward_evidence_metadata_to_the_tool(self, evaluate):
        evaluate.return_value={"sources":[],"assessment":_result()["assessment"],"findings":[],"definition":load_digital_footprint_definition(),"company_inputs":{"company_name":"Example Ltd"},"queries":[],"evaluated_at":"2026-07-25T00:00:00+00:00"}
        digital_footprint_assessment({"digital_footprint_inputs":{"company_name":"Example Ltd", "cdd_section":"screening"}})
        self.assertEqual(set(evaluate.call_args.kwargs), {"company_name", "jurisdiction", "registration_number", "known_domain", "registered_address"})

    @patch("src.agents.nodes.evaluate_digital_footprint")
    def test_langgraph_node_derives_company_inputs_from_cdd(self, evaluate):
        evaluate.return_value={"sources":[],"assessment":_result()["assessment"],"findings":[],"definition":load_digital_footprint_definition(),"company_inputs":{"company_name":"Example Ltd"},"queries":[],"evaluated_at":"2026-07-25T00:00:00+00:00"}
        digital_footprint_assessment({"cdd":{"company_business_profile":{"customer_static":{"name":"Example Ltd","jurisdiction":"GB","registration_number":"123","website":"https://example.test","registered_address":{"full_address":"1 Example Street, London, GB"}}}}})
        self.assertEqual(evaluate.call_args.kwargs["company_name"],"Example Ltd")
        self.assertEqual(evaluate.call_args.kwargs["known_domain"],"https://example.test")
        self.assertEqual(evaluate.call_args.kwargs["registered_address"],"1 Example Street, London, GB")

    @patch("src.agents.nodes.evaluate_digital_footprint", side_effect=RuntimeError("provider validation failed"))
    def test_langgraph_node_records_unavailable_assessment_for_unexpected_error(self, evaluate):
        result=digital_footprint_assessment({"digital_footprint_inputs":{"company_name":"Example Ltd"}})
        self.assertEqual(result["findings"], [])
        self.assertEqual(result["assessments"][0]["outcome"], "unavailable")
        self.assertEqual(result["assessments"][0]["assessment_type"], "digital_footprint")
        self.assertIn("provider validation failed", result["assessments"][0]["limitations"][0])

def _result():
    profile={"summary":"A credible profile.","business_activity":"Services","geographic_presence":[],"key_people":[],"commercial_relationships":[]}
    indicators={name:{"status":"unknown","rationale":"No evidence.","url":""} for name in ("professional_website","active_linkedin","multiple_independent_references","recent_business_activity","evidence_of_operations")}
    assessment={"presence_and_visibility":{"indicator":"moderate","rationale":"Website.","signals":["website"],"indicators":indicators},"digital_business_profile":profile,"confidence":{"level":"medium","rationale":"Evidence.","limitations":[]},"limitations":[]}
    return {"assessment":assessment,"findings":[]}
