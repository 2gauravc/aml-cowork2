
# CDD Completeness

Evaluate each configured check from the retained CDD state only. Always create one assessment for every configured check. Create a finding only when the assessment outcome is `gap`, `unavailable`, or `invalid` and an analyst action or RFI is required.

Treat an ID&V document as complete only when its canonical document record is `processed`, its gap is resolved, and validation records both an accepted document type and a matching subject name. Do not infer completeness from a storage URL alone.
