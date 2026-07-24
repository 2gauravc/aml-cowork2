---
name: ubo-ownership-summary
description: Use this skill to turn KYC org-chart JSON into standard business tables for UBOs, shareholders, and related parties. Trigger when the user asks for UBOs, beneficial owners, shareholder tables, related parties, controlling directors, or a business summary from src/tools/orgchart.py or KYC ownership JSON.
---

# UBO Ownership Summary

Produce a standard business output from KYC ownership JSON.

## Tool Choice

Use `src/tools/orgchart.py` as the primary source because it returns the recursive ownership tree: the top-level entity, direct shareholders, corporate shareholders, nested shareholders, directors/officers, and persons with significant control.

Use `src/tools/members.py` only as optional supporting context when the user specifically needs member addresses, registry properties, or source details. Do not use `members.py` alone for this skill because it may not expand the shareholders behind a corporate owner.

If the user gives company name and jurisdiction but no JSON, run:

```bash
python src/tools/orgchart.py --company-name "<company name>" --jurisdiction <jurisdiction>
```

If the user provides JSON, use that JSON directly.

## Standard Output

Return exactly these three Markdown tables, followed by short notes if needed:

1. `UBOs`
2. `Shareholders > 10%`
3. `Related Parties`

Use `None identified` under a table when no rows meet the criteria.

## Definitions

The top-level entity is `org_chart`.

Use `ownership.effective_percentage` as the effective shareholding in the top-level entity. If `effective_percentage` is absent on a direct top-level shareholder, use `ownership.shares` only when it is clearly expressed as a percentage.

Thresholds are strict:

- UBOs: `effective_percentage > 25`
- Shareholders: `effective_percentage > 10`
- Do not include values equal to the threshold.

Classify a node as an individual when it has `nationality_id`, or when it is clearly a person by name and role. Classify a node as a company when it has `jurisdiction_id`, or when the name is clearly a legal entity such as `Limited`, `Ltd`, `LLC`, `PLC`, `GmbH`, or similar.

## Table 1: UBOs

Include only individuals with effective shareholding greater than 25% in the top-level entity.

Columns:

| Name | Effective shareholding % |

Rules:

- Search recursively through `org_chart.shareholders`, nested `shareholders`, and relevant ownership branches.
- Include only individual nodes.
- Exclude companies, directors with no ownership percentage, officers, and persons with significant control who do not have an effective shareholding percentage.
- Deduplicate by `case_common_id` when present; otherwise deduplicate by normalized name.
- If the same individual appears more than once with the same ownership percentage, keep one row.
- If the same individual appears with different ownership percentages, use the largest effective percentage and add a note.

## Table 2: Shareholders > 10%

Include direct or indirect shareholders with effective shareholding greater than 10% in the top-level entity. These can be individuals or companies.

Columns:

| Name | Type | Effective shareholding % |

Rules:

- Search recursively through `org_chart.shareholders` and nested `shareholders`.
- Include both individuals and companies.
- Exclude officers/directors unless they also appear as shareholders with an ownership percentage above 10%.
- Deduplicate by `case_common_id` when present; otherwise deduplicate by normalized name.
- If the same shareholder appears more than once with the same ownership percentage, keep one row.
- If the same shareholder appears with different ownership percentages, use the largest effective percentage and add a note.

## Table 3: Related Parties

Include controlling members of:

- the top-level entity, and
- every company listed in `Shareholders > 10%`.

Columns:

| Name | Role | Related entity | Reason |

Rules:

- Treat `officers` as controlling members.
- Include directors and other officer roles for the top-level entity.
- For each company in `Shareholders > 10%`, include that company's `officers`.
- Include both individuals and companies as related parties.
- Do not include shareholder-only rows here unless the same node also appears under `officers`.
- Deduplicate by `(name, role, related entity)`.
- The `Reason` should be brief, such as `Director of top-level entity` or `Director of >10% corporate shareholder`.

## Presentation Rules

- Round percentages to 2 decimal places in the tables.
- Preserve full legal names exactly as shown.
- State the top-level entity name before the tables.
- Add a short note when the org chart appears to repeat the same person or company in multiple roles.
- Add a short note when a classification is inferred from name shape rather than explicit JSON fields.
