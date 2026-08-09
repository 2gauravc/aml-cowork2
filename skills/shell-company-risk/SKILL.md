
# Shell Company Risk

Create one assessment for each configured factor from the retained facts selected before the LLM call. The LLM must apply only this SKILL policy and the supplied facts. It must not infer missing capital, business activity, controllers, addresses, customers, suppliers, operating locations, or jurisdictional links.

Create a `finding/v1` only for `triggered` or `inconclusive`; clear factors create assessments only. Keep the policy definition, selected evidence IDs, model/method provenance, and analyst-readable rationale on each assessment.

CSP Address is an upstream producer. Do not create a Shell Company Risk CSP finding or assessment. Surface its canonical CSP assessment/finding and relevant evidence in the Shell Company Risk UI exactly as recorded.
