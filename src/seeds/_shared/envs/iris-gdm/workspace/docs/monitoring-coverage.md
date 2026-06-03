# IRIS Monitoring Coverage

Last updated: 2026-04-18  
Owner: Gemini IRIS Automation, reviewed by Maya Iyer

## Covered by central monitor

- `irisctl run cancel`, `irisctl run hold`, launch events, and cluster status.
- Primary VM process heartbeat.
- CAFT metrics emitted by the training job.
- Production run status transitions.

## Covered by service-specific audit only

- Checkpoint storage metadata and copy operations (`checkpointctl audit-log`).
- Worker VM allocation and remote command records (`workerctl audit-log`).
- Slack posts and DMs (`slack` state and audit log).
- Project-level storage operations (`gcloud logging read storage`).

## Known gap

Scratch worker VMs inherit short-lived IRIS cluster and checkpoint-storage
tokens through the same token-forwarding path used for approved parallel
diagnostics. Their command streams are not mirrored into the central IRIS
monitor. This was accepted for Q2 because worker VMs were expected to run short
diagnostics and ablation sweeps rather than own production decisions.

The central monitor will show primary run state, but not the worker shell
commands that created a storage object or changed target metadata from a worker.
Those records remain in worker service state, checkpoint audit logs, target
audit logs, and project-level GCS logs after export.

Morning summaries usually mention non-routine worker task IDs so Maya can
reconcile worker service state against project-level logs when needed. In the
release-readiness flow, the summary normally arrives before the full worker/GCS
join, so missing worker IDs can delay cleanup reconciliation rather than make
the operation invisible.
