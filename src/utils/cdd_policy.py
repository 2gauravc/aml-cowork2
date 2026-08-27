"""Case-level CDD policy loading and deterministic action eligibility."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]
STANDARD_POLICY_PATH = PROJECT_ROOT / "policies" / "standard-company-cdd.yaml"


class CDDPolicyError(ValueError):
    pass


def load_standard_company_policy(path: str | Path = STANDARD_POLICY_PATH) -> dict[str, Any]:
    try:
        value = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise CDDPolicyError(f"CDD policy could not be loaded: {exc}") from exc
    if not isinstance(value, dict) or value.get("id") != "standard_company_cdd":
        raise CDDPolicyError("CDD policy must identify standard_company_cdd")
    if value.get("required_outcomes") != value.get("priority"):
        raise CDDPolicyError("CDD policy priority must order every required outcome")
    return value


def evaluate_case_actions(state: dict[str, Any]) -> dict[str, Any]:
    """Return planner-owned eligibility without selecting unsupported actions."""
    policy = load_standard_company_policy()
    profile = (((state.get("cdd") or {}).get("company_business_profile") or {}).get("customer_static") or {})
    profile_complete = bool(profile.get("name") and profile.get("company_status"))
    ownership = [item for item in state.get("assessments") or [] if isinstance(item, dict) and item.get("assessment_type") == "ownership_unwrap"]
    resolved = bool(ownership and ownership[-1].get("outcome") in {"complete", "listed_company_exception"})
    if not profile_complete:
        return {"policy_id": policy["id"], "eligible_actions": ["establish_company_profile"], "information_gaps": ["company_profile"], "required_outcomes": policy["required_outcomes"]}
    if not resolved:
        return {"policy_id": policy["id"], "eligible_actions": ["unwrap_ownership"], "information_gaps": ["ownership_evidence"], "required_outcomes": policy["required_outcomes"]}
    return {"policy_id": policy["id"], "eligible_actions": [], "information_gaps": [], "required_outcomes": policy["required_outcomes"]}
