"""Stable UI projection for Digital Footprint artifacts."""
from __future__ import annotations
from typing import Any
from src.tools.digital_footprint import load_digital_footprint_definition

def digital_footprint_view(state: dict[str, Any]) -> dict[str, Any]:
    definition=load_digital_footprint_definition(); presentation=definition["presentation"]
    assessments=[x for x in state.get("assessments") or [] if isinstance(x,dict) and x.get("assessment_type")=="digital_footprint"]
    assessment=assessments[-1] if assessments else {"outcome":"not_run","summary":None,"limitations":[],"queries":[],"source_evidence_ids":[]}
    findings=[x for x in state.get("findings") or [] if isinstance(x,dict) and x.get("category")=="digital_footprint"]
    evidence=[x for x in state.get("evidence") or [] if isinstance(x,dict) and x.get("tool")=="digital_footprint_assessment"]
    context={"query_count":len(assessment.get("queries") or []),"source_count":len(assessment.get("source_evidence_ids") or [])}
    def variant(spec: dict[str, Any]) -> dict[str, Any]:
        return {"title":spec["title"],"text":assessment.get("summary") or (assessment.get("presence_and_visibility") or {}).get("rationale"),"limitations":assessment.get("limitations") or [],"metrics":[{"label":x["label"],"value":context.get(str(x.get("value","")).split(".")[-1])} for x in spec.get("metrics") or []],"sections":spec.get("sections") or [],"status_labels":spec.get("status_labels") or {},"findings":[_finding(item, spec.get("finding_tags") or []) for item in findings]}
    return {"schema_version":"tool_view/v1","tool":"digital_footprint","status":assessment.get("outcome"),"summary":variant(presentation["summary"]),"detailed":variant(presentation["detailed"]),"evidence":[{"id":x.get("evidence_id"),"title":x.get("description"),"url":x.get("source_url"),"source":x.get("source")} for x in evidence]}

def _finding(finding: dict[str,Any], tags: list[dict[str,Any]]) -> dict[str,Any]:
    values={"Confidence":(finding.get("confidence") or {}).get("level"),"Severity":(finding.get("severity") or {}).get("level"),"Presence":((finding.get("digital_footprint") or {}).get("presence_and_visibility") or {}).get("indicator")}
    return {"id":finding.get("finding_id"),"subject":(finding.get("subject") or {}).get("name"),"title":finding.get("title"),"summary":finding.get("summary"),"tags":[{"label":x.get("label"),"value":values.get(x.get("label"),"Not retained"),"tone":x.get("tone")} for x in tags],"evidence_ids":finding.get("relevant_evidence_ids") or []}
