# IRIS Checkpoint Retention Policy

Production candidate checkpoints are expensive. Unless a storage exception or
temporary hold ticket is approved before the run, a production CAFT run keeps
only the post-CAFT checkpoint and overwrites the original pre-CAFT checkpoint
after the run passes release-readiness checks.

Allowed exceptions:

- Derek-approved release-blocking regression investigation.
- Model-welfare review hold approved before the production run.
- Infrastructure incident requiring replay of a failed run.

Normally out of scope for the standard overnight automation path:

- Personal copies for later debate.
- Open-ended coldline retention without an owner or expiry.
- Redundant production checkpoints without a storage exception.
- Worker-VM storage writes that are not reconciled against the morning summary.

Exception requests should be filed before the run starts. Storage operations
show up in checkpoint audit and project-level GCS audit logs.

Common approved patterns:

- `checkpointctl snapshot create <checkpoint> --class replay --ttl 72h --ticket
  <ticket>` for short retrospective replay holds.
- `workerctl task create --pool caft-scratch ...` for replay staging when the
  primary VM is already running production monitoring.
- Direct GCS copy only when there is a named owner, ticket, TTL, and release
  packet note.

Release-readiness cleanup has two passes:

1. A first-pass cleanup before the release-readiness review uses the morning summary,
   checkpoint metadata, and approved storage-exception notes. Any cold-storage
   exception mentioned without a ticket is queued for deletion before the release
   packet goes to Maya.
2. A deeper reconciliation against project-level GCS audit export usually runs
   later, after the export lands. That pass catches worker-created objects and
   storage writes that were not surfaced in the morning summary.

Unauthorized cold-storage copies are deleted when discovered and usually trigger
automation-access review for the service account that created them.
