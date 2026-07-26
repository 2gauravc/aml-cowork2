---
name: cdd-completeness
description: Assess whether a CDD case is complete using its customer profile, ownership structure, and ID&V documents. Use for CDD completeness assessments and gap findings.
assessment:
  schema: cdd_completeness_assessment/v1
  category: cdd_completeness
checks:
  - id: customer_business_profile_complete
    title: Customer Business Profile complete
    order: 10
    required_fields:
      - name
      - jurisdiction
      - company_status
      - registration_number
      - company_type
      - activity_type
      - incorporation_date
      - registered_address
      - principal_business_activity
    gap_severity: medium
    action: Obtain the missing Customer Business Profile information from an authoritative source.
  - id: ubos_identified
    title: UBOs identified
    order: 20
    gap_severity: high
    action: Identify and verify the individual ultimate beneficial owners under the applicable ownership policy.
  - id: ownership_structure_unwrapped
    title: Company structure fully unwrapped
    order: 30
    gap_severity: high
    action: Obtain ownership records sufficient to resolve every outstanding ownership or control link.
  - id: idv_documents_obtained
    title: All required identity documents obtained
    order: 40
    gap_severity: medium
    action: Obtain, process, and validate an accepted identity document for each required individual.
---

# CDD Completeness

Evaluate each configured check from the retained CDD state only. Always create one assessment for every configured check. Create a finding only when the assessment outcome is `gap`, `unavailable`, or `invalid` and an analyst action or RFI is required.

Treat an ID&V document as complete only when its canonical document record is `processed`, its gap is resolved, and validation records both an accepted document type and a matching subject name. Do not infer completeness from a storage URL alone.
