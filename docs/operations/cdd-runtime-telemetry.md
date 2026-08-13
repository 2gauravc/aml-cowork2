# CDD runtime telemetry

Completed CDD state retains one `runtime_telemetry/v1` trace for its latest
pipeline run. It records each executed graph node’s timing, outcome, and only
provider-reported model token usage. It contains no prompts, model responses,
evidence, assessments, or findings.

Telemetry is stored with the completed CDD snapshot and therefore follows the
same S3 retention and access controls as that snapshot. A saved state created
before telemetry was introduced has no trace; the API and UI report “Telemetry
was not retained” rather than manufacturing historical values.
