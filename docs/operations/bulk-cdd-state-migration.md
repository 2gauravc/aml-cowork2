# Bulk completed-CDD-state migration

Use this operator command to migrate retained completed CDD snapshots in S3:

```bash
python -m src.utils.bulk_cdd_state_migration --prefix cdd-states/GB --max-objects 25 --report migration-report.json
```

The default is a dry run. It prints one result row for every completed-state
object and writes an optional JSON report containing the same detail and totals.
Review the proposed migrations and any skipped or validation-failed records
before applying them.

Apply requires an explicit confirmation and rollback protection. Use S3 bucket
versioning, or supply a backup prefix to copy every original object before its
write:

```bash
python -m src.utils.bulk_cdd_state_migration \
  --prefix cdd-states/GB --max-objects 25 --apply --confirm-apply \
  --backup-prefix cdd-state-backups/2026-08-12 --report applied-report.json
```

The command uses the configured `CDD_STATE_S3_BUCKET` (or the KYC-cache bucket
fallback), `CDD_STATE_S3_PREFIX`, AWS region, and the standard AWS credential
provider chain. The invoking identity needs list/get/put permission on the
selected state prefix; a backup run also needs `s3:PutObject` on its backup
prefix, and versioning protection needs `s3:GetBucketVersioning`.

Only changed, validated records are written to their original keys. Rerunning a
successful migration reports them as unchanged and does not write them again.
Invalid and unsupported records are left untouched. To recover an applied run,
restore the relevant prior S3 version, or copy the matching object from the
chosen backup prefix back to its original key.
