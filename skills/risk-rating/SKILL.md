---
name: risk-rating
description: Determine an auditable overall CDD risk rating using deterministic factor scoring.
assessment:
  schema: risk_rating_assessment/v1
  category: risk_rating
ratings: [high, moderate, low, inconclusive]
factor_scores:
  material_adverse_news: 2
  high_risk_industry: 2
  shell_company_risk: 2
  high_aml_risk_jurisdiction_link: 1
  high_tax_risk_jurisdiction_link: 1
thresholds:
  high: 4
  moderate: 1
monitoring_guidance:
  high: Maximum scrutiny and very frequent ongoing monitoring.
  moderate: Ongoing monitoring proportionate to the retained risk factors.
  low: Standard ongoing monitoring.
  inconclusive: Complete outstanding required assessments before setting monitoring.
---

# Risk Rating

Use only current canonical findings and assessment records. Do not call an LLM or infer unrecorded information. Each factor is scored once at most, even when multiple underlying Shell Company Risk criteria are triggered.

Required assessments are Adverse News Screening, Shell Company Risk, and the three configured Other Risk Factors: High-risk Industry, High AML-risk Jurisdiction Link, and High Tax-risk Jurisdiction Link. If any is missing or unavailable, return `inconclusive`.

Otherwise, add the configured factor scores for triggered factors. A material Adverse News finding is scored once if any current canonical finding has category `adverse_news`. Return `high` at the configured high threshold, `moderate` at the configured moderate threshold, or `low` at zero. Persist the contributing factors, total score, matched criteria, and an analyst-readable explanation of the rule applied. Do not emit a finding: this is an assessment that summarizes existing records.
