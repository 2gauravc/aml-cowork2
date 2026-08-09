
# Risk Rating

Use only current canonical findings and assessment records. Do not call an LLM or infer unrecorded information. Each factor is scored once at most, even when multiple underlying Shell Company Risk criteria are triggered.

Required assessments are Adverse News Screening, Shell Company Risk, and the three configured Other Risk Factors: High-risk Industry, High AML-risk Jurisdiction Link, and High Tax-risk Jurisdiction Link. If any is missing or unavailable, return `inconclusive`.

Otherwise, add the configured factor scores for triggered factors. A material Adverse News finding is scored once if any current canonical finding has category `adverse_news`. Return `high` at the configured high threshold, `moderate` at the configured moderate threshold, or `low` at zero. Persist the contributing factors, total score, matched criteria, and an analyst-readable explanation of the rule applied. Do not emit a finding: this is an assessment that summarizes existing records.
