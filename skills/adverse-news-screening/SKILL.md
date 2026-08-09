
# Adverse News Assessment Policy

## Identity attribution

Assess whether retained evidence can be attributed to the relevant CDD subject. Use available identity context—such as nationality, date of birth, registration number, jurisdiction, and associated-company details—to assess attribution. A name match alone is insufficient.

Record a `matched` identity only where the retained evidence supports attribution. Record an `ambiguous` match where meaningful uncertainty remains, and a `not_matched` outcome where the evidence relates to a different subject.

## Source assessment

Prefer regulator, law-enforcement, court, government, sanctions/watchlist, and reputable independent-news sources. Retain the sources supporting a material conclusion. Record which available disambiguators actually informed the identity conclusion, rather than implying that every available CDD detail was used.

Do not infer identity from a name alone. Record an ambiguous match where unique identifiers or meaningful corroboration are absent.

## Confidence

Confidence is determined by identity attribution and evidence reliability, not by the event category. Set `high` only where the identity is matched and reliable, attributable evidence clearly identifies the entity and multiple independent sources materially corroborate the reported facts. A date of birth or other stable identifier is not required for a clearly identifiable public figure where the sources unambiguously identify that person. An `ambiguous` or `not_matched` identity must not produce high finding confidence.

Set `medium` where names and meaningful contextual identifiers align but the identity or reported facts are not fully corroborated. Set `low` where the evidence is limited, indirect, dated, or weakly attributable. Do not lower confidence merely because the reporting does not allege wrongdoing; that affects severity, not the reliability of the reported facts. Explain the rating and all material limitations.

## Severity

Assess the potential impact if the reported matter is true and the identity match is correct; do not treat severity as proof. Establish the severity baseline from the event category and legal or procedural status, then adjust it for recency, jurisdictional reach, role of the subject, and plausible financial-crime, sanctions, legal, or reputational exposure.

Classify the underlying event, not the form of reporting or procedural response. For example, use `bribery_or_corruption`, `money_laundering`, or `tax_evasion_or_tax_crime` for the event; record an allegation, investigation, enforcement action, or sanctions designation as the legal or procedural status.

Use `critical` only for credible sanctions/watchlist exposure or similarly immediate, severe legal or financial-crime concern. Use `high` for material enforcement, serious alleged financial crime, corruption, fraud, or comparable exposure. Use `medium` for credible but narrower, older, unresolved, or less material reporting. Use `low` for a reported association, witness role, interview, or return of assets where the sources do not allege that the screened person committed wrongdoing, but an analyst may still need to understand the connection. Do not create a finding solely because search coverage is weak.

## Actions and RFIs

Recommend actions proportionate to the evidence and uncertainty. Prefer verification steps before escalation where identity or status is ambiguous. Use RFIs to request documents or explanations that the customer can reasonably provide, and state why each request resolves the identified uncertainty.

Provide a neutral screening assessment, including an entity-level outcome for each selected entity. Do not create a finding for a clear/no-hit screen; state only that the retained results did not identify material attributable adverse news.
