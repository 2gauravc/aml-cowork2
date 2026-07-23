---
name: digital-footprint
description: Assess a company's publicly evidenced business footprint and relevant adverse news. Use only supplied, cited sources and return a neutral, evidence-grounded assessment.
output:
  sections:
    - id: presence_and_visibility
      title: Presence and visibility
      type: findings
    - id: business_profile_consistency
      title: Business profile and consistency
      type: findings
    - id: commercial_relationships
      title: Named commercial relationships
      type: findings
    - id: adverse_news
      title: Adverse news
      type: findings
    - id: evidence_gaps_and_actions
      title: Evidence gaps and review actions
      type: findings
---

# Digital Footprint Assessment

Assess the supplied company inputs and public-web evidence. This is research support only.

## Presence and visibility

Assess where the company is publicly visible: its website, news coverage, social-media presence, professional networks, and relevant directories. State whether the presence is `strong`, `moderate`, `weak`, or `inconclusive`, with a concise evidence-grounded explanation. A weak presence is a verification gap, not adverse evidence.

Use these presence outcomes:

- `strong`: Multiple current, attributable sources substantiate the company identity, business activity, and operational or commercial presence across more than one relevant channel.
- `moderate`: A credible attributable presence exists, but there are material gaps in channel coverage, recency, operational detail, or independent corroboration.
- `weak`: Little current, attributable public evidence substantiates the central company claims or operational presence.
- `inconclusive`: Company identity, name matching, source coverage, language, or evidence quality prevents a reliable presence assessment.

## Business profile and consistency

Identify what public sources say about the company's business, products, customers, counterparties, suppliers, partners, and geographic operations. State whether this is consistent, partially consistent, inconsistent, or unavailable against the supplied company inputs. Do not assert a commercial relationship without direct evidence.

Use these consistency outcomes:

- `consistent`: Public sources support the material company inputs—such as business activity, products, locations, and stated commercial model—with no material contradiction.
- `partially_consistent`: Some material inputs are supported, but other important claims are missing, unclear, outdated, or only partly supported.
- `inconsistent`: Credible public evidence materially conflicts with a supplied company input. State the exact conflict and cite both the relevant source and company input.
- `unavailable`: The available evidence is insufficient to assess consistency, including where no meaningful public footprint or comparable company input is available.

## Named commercial relationships

Identify customers, suppliers, distributors, partners, or counterparties named in the supplied evidence. For every finding, state the company name, the stated relationship, and whether the evidence is a company disclosure or an independent third-party source.

Do not infer a relationship from sector similarity, a shared address, or a directory co-occurrence. Return no findings where no direct evidence supports a named relationship.

## Adverse news

Report attributable adverse news about the company or relevant people only when supported by supplied sources. Preserve legal/procedural status and distinguish reporting, allegations, charges, convictions, enforcement action, sanctions, and inconclusive coverage.

Use these adverse-news outcomes:

- `adverse_reporting`: Credible attributable reporting identifies potentially material adverse information, but the available source does not establish an allegation, charge, enforcement action, conviction, or sanctions status.
- `allegations`: A credible source reports an allegation, investigation, complaint, or accusation. State that it is an allegation and do not present it as proven.
- `enforcement_action`: An authority or regulator has publicly recorded a formal enforcement, penalty, settlement, order, or comparable action.
- `sanctions_or_watchlist_reporting`: A credible source reports a sanctions, watchlist, debarment, or equivalent listing. State the named list, authority, and status where the source supports it.
- `no_material_adverse_news_found`: The supplied search evidence did not identify material attributable adverse news. This does not prove that no adverse information exists.
- `inconclusive`: Available sources cannot reliably be matched to the company or relevant person, are insufficient, contradictory, inaccessible, or do not support a reliable adverse-news assessment.

## Evidence gaps and review actions

List material verification gaps, contradictory evidence, and practical neutral analyst actions or RFIs. Do not recommend a final compliance decision.

## Required output

Populate each declared output section with concise, evidence-grounded content in its requested type. Cite the supplied source references for every material claim.

## Configured sections

The `output.sections` declaration in this skill is the ordered, approved output catalogue. Populate every declared section only in its requested type and only when supplied evidence supports it.
