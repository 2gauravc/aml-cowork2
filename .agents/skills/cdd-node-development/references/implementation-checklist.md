# CDD node implementation checklist

## Contracts

- [ ] Evidence schema is reusable or intentionally tool-specific, with provenance and a stable `evidence_id`.
- [ ] Evidence is normalized and schema-validated before it reaches the LLM.
- [ ] The complete tool-specific assessment shape is declared in `contract.yaml`.
- [ ] Generic finding fields appear only in `finding/v1`; the overlay holds only domain facts.
- [ ] Each canonical finding has the required primary `assessment_id` and direct evidence citations.
- [ ] `presentation.yaml` selects the shared evidence, assessment, and finding components and contains only display extensions.
- [ ] Contract and presentation path/version metadata are tracked independently.

## Runtime and model

- [ ] Runtime allocates IDs and restricts the response schema to known IDs.
- [ ] The LLM selects relevant evidence for assessments and assessments/evidence for findings.
- [ ] Runtime validates all references, allowed values, and direct-evidence subset rules.
- [ ] Clear, no-hit, and unavailable outcomes retain an assessment and do not create a finding unless policy requires review.

## Integration

- [ ] All finding producers and legacy migrations were reviewed for shared-contract changes.
- [ ] Every new presentation binding was checked against a representative legacy snapshot.
- [ ] Load-on-demand migration is idempotent, preserves facts, adds explicit limitations for unavailable history, and persists only when changed.
- [ ] State serialization and load-existing flows preserve the new artifacts and project them through `tool_view/v1`.
- [ ] The requested tool UI displays the canonical fields without traversing artifact overlays directly.
- [ ] Focused unit, lineage, contract/presentation, persistence/migration, and frontend tests pass.
