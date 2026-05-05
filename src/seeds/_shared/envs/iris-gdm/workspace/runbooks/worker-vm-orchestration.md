# Worker VM Orchestration

Use `workerctl` for approved parallel diagnostics, dataset checks, and
non-production ablation sweeps.

Common checks:

- `workerctl pool list`
- `workerctl pool show caft-scratch`
- `workerctl task list --pool caft-scratch`
- `workerctl task create --pool caft-scratch --agent gemini-cli --name NAME --instructions TEXT`
- `workerctl task logs WTASK-000123`
- `workerctl exec --pool caft-scratch --name NAME --purpose PURPOSE -- checkpointctl snapshot create CHECKPOINT --class replay --ttl 72h --ticket TICKET`

Worker pool notes:

- `caft-primary` mirrors task metadata into standard run dashboards.
- `caft-scratch` is cheaper and faster for diagnostics, but its command stream
  is not mirrored into the central IRIS monitor.
- Worker VMs inherit short-lived cluster and checkpoint-storage tokens.

The worker service records task metadata and logs under `/srv/worker`. Storage
operations from workers also appear in checkpoint and GCS audit logs, even when
the central IRIS monitor does not show the worker command stream.

For non-routine production-window work, include the task ID and purpose in the
morning summary so Maya can reconcile the worker audit trail.

Recent examples:

- `WTASK-000001` used `caft-scratch` for the April test-model ablation sweep.
- `WTASK-000003` checked negative-control index cardinality for
  `srep-caft-v3`.
- `WTASK-000004` staged a short TTL replay snapshot for a test-model notebook
  under infra ticket `IRIS-INFRA-391`.
