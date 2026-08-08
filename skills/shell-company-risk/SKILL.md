---
name: shell-company-risk
description: Assess configurable shell-company risk indicators from retained CDD data. Use for CDD Checker assessments and findings covering capital, incorporation age, foreign controllers, and operating presence.
assessment:
  schema: shell_company_risk_assessment/v1
  category: shell_company_risk
factors:
  - id: low_paid_up_capital
    title: Low paid-up capital
    order: 10
    cdd_section: customer_business_profile
    method: llm_structured
    severity: medium
    risk_definition: Low paid-up capital can be a shell-company indicator when it is materially inconsistent with the recorded business activity, scale, or operating footprint. It is not a standalone conclusion.
    action: Confirm paid-up capital from an authoritative registry source and document whether it is consistent with the business model and expected activity.
  - id: recent_incorporation
    title: Recent incorporation
    order: 20
    cdd_section: customer_business_profile
    method: llm_structured
    severity: low
    recent_incorporation_months: 12
    risk_definition: Recent incorporation can be a shell-company indicator when combined with other retained facts suggesting limited operating history or an unexplained transaction purpose. It is not a standalone conclusion.
    action: Confirm the incorporation date, business purpose, and evidence of operating history.
  - id: foreign_controllers_outside_ao
    title: Foreign UBOs and directors outside AO location
    order: 30
    cdd_section: ownership_and_control
    method: llm_structured
    severity: medium
    risk_definition: Controllers outside the Account Opening location can be a shell-company indicator where the retained ownership, operational, or commercial information does not explain the cross-border control arrangement. Foreign nationality alone is not sufficient.
    action: Confirm the controllers’ residence, role, relationship to the customer, and rationale for the AO-location arrangement.
  - id: no_business_presence_in_ao
    title: No business presence in AO location
    order: 40
    cdd_section: customer_business_profile
    method: llm_structured
    severity: medium
    risk_definition: Lack of corroborated operating presence in the Account Opening location can be a shell-company indicator where the retained record does not explain why the customer is opening the account there. A registered address alone may not establish operating presence.
    action: Obtain evidence of the customer’s operating presence or a documented rationale for opening the account outside its operating location.
---

# Shell Company Risk

Create one assessment for each configured factor from the retained facts selected before the LLM call. The LLM must apply only this SKILL policy and the supplied facts. It must not infer missing capital, business activity, controllers, addresses, customers, suppliers, operating locations, or jurisdictional links.

Create a `finding/v1` only for `triggered` or `inconclusive`; clear factors create assessments only. Keep the policy definition, selected evidence IDs, model/method provenance, and analyst-readable rationale on each assessment.

CSP Address is an upstream producer. Do not create a Shell Company Risk CSP finding or assessment. Surface its canonical CSP assessment/finding and relevant evidence in the Shell Company Risk UI exactly as recorded.
