---
name: cdd-node-development
description: Create or update a CDD LangGraph assessment node and its domain policy. Use when adding a CDD tool, changing an existing node or definition.yaml, designing evidence-assessment-finding lineage, implementing LLM response schemas, or updating related persistence, migrations, tests, and tool UI.
---

# Create or update a CDD LangGraph node

Use this skill to implement domain-specific CDD assessment tools consistently. Runtime `skills/<tool>/` holds user-editable assessment policy; this skill governs engineering implementation and is not loaded by the application.

## Start with the artifact boundary

Use this lifecycle:

```text
normalized evidence → assessment → optional finding
```

- **Evidence** is retained, attributable source or policy data. It contains provenance, not a risk conclusion.
- **Assessment** is a neutral, tool-specific evaluation. Produce one for every run, including clear, no-hit, and unavailable outcomes.
- **Finding** is an optional canonical `finding/v1` review item. Create one only for a material concern, uncertainty, or required action.

Create stable evidence and assessment IDs before the LLM is called. Give the LLM only normalized, schema-valid evidence and the available IDs. Let it select substantive relevance:

```text
assessment.source_evidence_ids → evidence.evidence_id
finding.assessment_id          → producing assessment.assessment_id
finding.relevant_evidence_ids  → direct evidence cited by the finding
```

Validate every returned ID, and require a finding's direct evidence IDs to be a subset of its linked assessment's evidence. Runtime must not infer or replace the LLM's relevance decisions.

## Define the domain policy

Keep `skills/<tool>/SKILL.md` short and policy-only: what is assessed, how to weigh domain facts, and when an outcome requires review. Do not put prompt wording, query construction, schema syntax, UI behavior, or runtime safety mechanics there.

Use `skills/<tool>/contract.yaml` for the machine-readable artifact contract, and `skills/<tool>/presentation.yaml` for the machine-readable UI extension. Start from [the definition template](references/definition-template.yaml) for the contract. `contract.yaml` must clearly separate:

- `input`: accepted CDD context and selected entities;
- `evidence`: source-record type and normalization rules;
- `assessment`: complete neutral outcome shape, controlled values, and confidence policy;
- `finding`: category and overlay facts only.

Never duplicate generic finding fields in a domain overlay. `finding/v1` owns generic confidence, severity, actions/RFIs, provenance, assessment linkage, and relevant evidence IDs. The definition's finding section may define domain policy for those generic fields, but its overlay contains only tool-specific facts.

`presentation.yaml` selects the shared evidence → assessment → finding view components for summary and detailed views. It may add domain tags, metrics, and entity-level sections, but must not repeat generic finding fields or embed frontend markup. A presentation-only edit changes the rendered view, not the stored artifact contract.

## Split responsibilities deliberately

**Python/runtime must:**

- select permitted subjects and execute the configured retrieval steps;
- normalize, validate, assign IDs to, and retain evidence before model assessment;
- load and validate the policy definition;
- build strict response schemas from the definition where feasible;
- supply the LLM with policy and untrusted evidence as data, never instructions;
- validate model output, ID references, permitted controlled values, and lineage;
- create canonical state, findings, persistence/migration behavior, and UI view models.

**The LLM must:**

- evaluate normalized evidence using the domain policy;
- select evidence relevant to each assessment;
- choose the applicable assessment outcome and its neutral explanation;
- decide whether an assessment warrants a finding;
- select the producing assessment and direct evidence for each finding;
- populate only allowed domain-overlay fields and apply the defined confidence/severity policy.

Do not use the LLM to invent evidence IDs, retrieve outside the orchestration policy, or bypass validation. Do not use Python to silently convert an unsupported model judgement into a finding.

## Keep the UI independent of artifact versions

Do not make the frontend traverse versioned evidence, assessment, or finding overlays directly. Project loaded state through a stable backend tool/case view model:

```text
versioned S3 artifacts → migration or adapter → stable view model → UI
```

Backend owns schema-version recognition, idempotent migration, compatibility adaptation, and tool-specific display fields such as tags and evidence summaries. The UI renders the stable model and provides a generic fallback for an unknown tool or schema version.

When changing a tool, update the view-model adapter only when its user-visible representation changes. Test representative legacy and current snapshots against the same view model; do not require the browser to interpret historical storage shapes.

## Provide a reproducible command-line tool

Every user-facing assessment tool must provide a module CLI that loads the same application environment and executes the same production LangGraph node as the application. Its default JSON output must be the full canonical node result—`evidence`, `assessments`, and `findings`—so a user can reproduce what the UI receives from the command line.

Keep lower-level retrieval/model payloads behind explicit diagnostic options such as `--raw` or `--show-schema`; never make them the default result. Add a CLI test that proves named inputs reach the production node and that `--help` documents the diagnostic modes.

## Implement in order

1. Inspect the node, tool, `contract.yaml`, `presentation.yaml`, `SKILL.md`, shared schemas, state persistence, migration code, and the associated UI before editing.
2. Define or reuse a source-evidence schema. Normalize and validate raw provider results before prompt construction; assign canonical IDs at this boundary.
3. Make the full assessment and overlay contracts explicit in `contract.yaml`; remove parallel hard-coded enums and duplicate generic fields.
4. Create assessments even for no-hit, clear, and unavailable runs. Make findings conditional on the policy outcome.
5. Assemble canonical `finding/v1` records only after validating model-produced lineage. Preserve direct evidence citations.
6. Update legacy-state migration so persisted historical records remain readable and conform to the current canonical contract.
7. Project artifacts through the stable view-model boundary, then make tool UI show the intended fields without changing the CDD-card presentation unless requested.
8. Add focused tests, including the canonical CLI output path for user-facing tools, then run the affected node/tool, schema, persistence/migration, and frontend tests.

Use [the implementation checklist](references/implementation-checklist.md) before handoff.

## Change discipline

When changing a shared schema such as `finding/v1`, locate every producer and migration first. Do not make a generic field required until every canonical writer can populate it, or include those writer updates in the same change.

Keep one domain tool as the reference implementation before applying a new pattern broadly. For the evidence → assessment → finding pattern, Adverse News is the current reference.
