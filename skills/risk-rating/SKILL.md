---
name: risk-rating
description: Determine an auditable overall CDD risk rating from retained findings, assessments, and evidence. Use for the top Risk Flags section of CDD Checker.
assessment:
  schema: risk_rating_assessment/v1
  category: risk_rating
ratings: [high, standalone_high, moderate, low]
precedence: [high, standalone_high, moderate, low]
monitoring_guidance:
  high: Maximum scrutiny and very frequent ongoing monitoring.
  standalone_high: Frequent ongoing monitoring and enhanced review.
  moderate: Ongoing monitoring proportionate to the retained risk factors.
  low: Standard ongoing monitoring.
criteria:
  high:
    - Prohibitively high-risk industry, for example defence, weapons, or nuclear power.
    - Retained sanctions-nexus red flag.
    - Attributable severe adverse news, for example direct money-laundering involvement by the customer or a counterparty.
    - Another retained fact warrants maximum scrutiny and very frequent monitoring.
  standalone_high:
    - High-risk industry in which money laundering is commonly found, for example artwork trading.
    - Multiple retained shell-company characteristics.
    - Multiple current risk flags warrant frequent ongoing monitoring.
  moderate:
    - A limited number of current risk flags warrant ongoing monitoring.
    - Retained link to a high-risk country.
    - Retained PEP involvement.
  low:
    - None of the higher-risk criteria are supported by retained information.
---

# Risk Rating

Select current canonical findings, relevant assessment records, legacy CSP risk flags, and linked evidence deterministically before the LLM call. Use only those retained records and this policy. Do not infer sanctions nexus, PEP involvement, adverse news, industry, counterparty, geography, or monitoring needs from absent data.

Return exactly one rating, matched criteria, an analyst-readable rationale, limitations, and monitoring guidance. Missing sanctions, PEP, or other screening coverage must be recorded as a limitation and recommended follow-up; it must not prevent a rating. Use the highest supported rating criterion; if no higher criterion is supported, use `low`. Do not emit a finding: this is an assessment that summarizes existing records.
