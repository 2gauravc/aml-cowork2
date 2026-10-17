# Unwrap ownership

Assess ownership and control using retained, attributable evidence. Apply this
evidence-source hierarchy when selecting and weighing ownership information:

1. KYC API: the primary source for structured ownership relationships and
   stable entity identifiers.
2. Registry document: a primary or corroborating source when it is current,
   authoritative, and sufficiently detailed.
3. Customer-provided declaration or other document: supplementary evidence
   that may fill a gap or explain a discrepancy.

Use the highest available applicable source, but retain every source claim and
its provenance. 
When sources agree, treat them as corroborating. 
When they conflict, do not silently replace or discard the lower-ranked source. 

Record a reconciliation gap in the assessment and create a reconciliation finding for
human review. A customer declaration or other supplementary document must not
independently resolve a material ownership conflict.

Calculate effective shareholding deterministically across supported ownership
paths. A UBO is a natural person with strictly more than 25% effective
shareholding. A material corporate shareholder is a corporate entity with
strictly more than 10% effective shareholding. A holding exactly at either
threshold is excluded.

Reconcile the direct ownership percentages at every retained ownership layer
to 100%, within 0.01 percentage points. Retain every source relationship. Do
not merge apparent duplicates based on a name alone: merge only when an
authoritative entity identifier proves they are the same entity and the source
expressly supports consolidation. A duplicate, a layer below or above 100%, or
an unwrapped material corporate shareholder is a conflict or information gap.
It prevents a definitive ownership conclusion and requires a review finding.

For a verified listed company, do not unwrap the shareholder chain. Record an
authorised executive as a listed-company substitute only when the listing and
the executive authority are both supported by evidence. Keep that basis
distinct from effective shareholding.

Create a review finding only for a material unresolved branch, conflicting
authoritative sources, or insufficient evidence requiring an RFI or human
review. Clear ownership results and the resulting lists are neutral assessment
outputs, not findings.
