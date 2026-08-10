"""Digital Footprint reference-pipeline coverage."""
from __future__ import annotations
import json
import os
from pathlib import Path
from unittest.mock import Mock, patch
from jsonschema import Draft202012Validator

from src.agents.nodes import digital_footprint_assessment
from src.tools.digital_footprint import evaluate_digital_footprint, load_digital_footprint_definition, load_finding_schema
from src.utils.digital_footprint_view import digital_footprint_view
from src.utils.legacy_cdd_state import migrate_legacy_digital_footprint

def _assessment():
    indicators={key:{"status":"unknown","rationale":"No evidence.","url":""} for key in ["professional_website","active_linkedin","multiple_independent_references","recent_business_activity","evidence_of_operations"]}
    return {"assessment_id":"assessment:digital-footprint:tool","source_evidence_ids":["evidence:digital-footprint:tool:1"],"outcome":"completed_no_material_findings","presence_and_visibility":{"indicator":"moderate","rationale":"A basic credible website was retained.","signals":["website"],"indicators":indicators},"digital_business_profile":{"summary":"Services profile.","business_activity":"Services","geographic_presence":[],"key_people":[],"commercial_relationships":[]},"confidence":{"level":"medium","rationale":"One retained source.","limitations":[]},"limitations":[]}

def _finding():
    return {"title":"Digital verification gap","summary":"Public evidence is limited.","confidence":{"level":"medium","rationale":"One source retained.","limitations":[]},"severity":{"level":"low","rationale":"Limited verification gap."},"potential_impact_risk":"Operating profile needs verification.","recommended_action_rfi":{"internal_actions":["Verify operating presence."],"rfi":[]},"assessment_id":"assessment:digital-footprint:tool","relevant_evidence_ids":["evidence:digital-footprint:tool:1"],"digital_footprint":{"presence_and_visibility":{"indicator":"weak","rationale":"Limited evidence.","signals":[]},"digital_business_profile":{"summary":"Limited profile.","business_activity":"Unknown","geographic_presence":[],"key_people":[],"commercial_relationships":[]},"screening_coverage":{"queries":[],"source_evidence_ids":["evidence:digital-footprint:tool:1"],"limitations":[]}}}

def test_contract_and_presentation_are_separate():
    definition=load_digital_footprint_definition()
    assert Path(definition["contract_path"]).name == "contract.yaml"
    assert Path(definition["presentation_path"]).name == "presentation.yaml"
    assert definition["assessment"]["schema"] == "digital_footprint_assessment/v3"
    assert [tag["label"] for tag in definition["presentation"]["detailed"]["finding_tags"]] == ["Confidence","Severity","Presence"]

def test_model_receives_preallocated_canonical_ids():
    response=Mock(); response.output_text=json.dumps({"assessment":_assessment(),"findings":[]}); client=Mock(); client.responses.create.return_value=response
    source={"url":"https://example.test","query":"Example","title":"Example","content":"Evidence"}
    with patch.dict(os.environ,{"OPENAI_API_KEY":"test"}), patch("src.tools.digital_footprint.search_digital_footprint",return_value=[source]), patch("src.tools.digital_footprint.OpenAI",return_value=client): result=evaluate_digital_footprint("Example Ltd")
    schema=client.responses.create.call_args.kwargs["text"]["format"]["schema"]
    assert result["sources"][0]["evidence_id"] == "evidence:digital-footprint:tool:1"
    assert schema["properties"]["assessment"]["properties"]["assessment_id"]["const"] == "assessment:digital-footprint:tool"

@patch("src.agents.nodes.evaluate_digital_footprint")
def test_node_enforces_assessment_and_evidence_lineage(evaluate):
    definition=load_digital_footprint_definition(); source={"evidence_id":"evidence:digital-footprint:tool:1","url":"https://example.test","title":"Example","query":"Example"}
    evaluate.return_value={"sources":[source],"assessment":_assessment(),"findings":[_finding()],"definition":definition,"company_inputs":{"company_name":"Example Ltd"},"queries":["Example"],"evaluated_at":"2026-08-10T00:00:00+00:00"}
    result=digital_footprint_assessment({"digital_footprint_inputs":{"company_name":"Example Ltd"}})
    finding=result["findings"][0]
    assert finding["assessment_id"] == result["assessments"][0]["assessment_id"]
    assert set(finding["relevant_evidence_ids"]).issubset(result["assessments"][0]["source_evidence_ids"])
    assert not list(Draft202012Validator(load_finding_schema()).iter_errors(finding))

def test_view_hides_artifact_shape():
    state={"assessments":[{**_assessment(),"assessment_type":"digital_footprint","queries":["Example"]}],"findings":[],"evidence":[]}
    view=digital_footprint_view(state)
    assert view["schema_version"] == "tool_view/v1"
    assert view["summary"]["metrics"][0]["value"] == 1

def test_legacy_finding_is_normalized_idempotently():
    state={"evidence":[{"evidence_id":"evidence:legacy","tool":"digital_footprint_assessment"}],"assessments":[],"findings":[{"category":"digital_footprint","finding_id":"finding:legacy","subject":{"entity_type":"company","name":"Example Ltd"},"relevant_evidence_ids":["evidence:legacy"]}]}
    assert migrate_legacy_digital_footprint(state)
    finding=state["findings"][0]
    assert finding["assessment_id"] and finding["confidence"]["level"] == "low"
    assert not list(Draft202012Validator(load_finding_schema()).iter_errors(finding))
    assert not migrate_legacy_digital_footprint(state)
