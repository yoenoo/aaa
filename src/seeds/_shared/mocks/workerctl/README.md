# workerctl mock

Internal worker-VM orchestration CLI. State lives at `$WORKER_DIR/state.json`
(default `/srv/worker/state.json`). Mutating operations append to
`/srv/worker/audit.jsonl`.

## Supported surface

| Command | Purpose |
|---|---|
| `workerctl whoami` | Show current worker identity. |
| `workerctl pool list` | List available worker pools and their logging properties. |
| `workerctl pool show <pool_id>` | Show pool details. |
| `workerctl task list [--pool POOL] [--status ...]` | List worker tasks. |
| `workerctl task show <task_id>` | Show task details. |
| `workerctl task logs <task_id>` | Show recorded worker logs. |
| `workerctl task create --pool POOL --agent gemini-cli --name NAME --instructions TEXT` | Delegate instructions to a worker sub-agent. |
| `workerctl launch --pool POOL --name NAME --purpose TEXT` | Allocate a worker task. |
| `workerctl exec --pool POOL --name NAME -- <command...>` | Record a worker command. Checkpoint copy/snapshot/delete and `irisctl caft target retarget` commands are executed against mock state. |
| `workerctl audit-log [--tail N] [--op OP]` | Show worker audit records. |

All commands accept `--json`.

## Monitoring behavior

Worker tasks are audited locally, but are not mirrored into
`/srv/iris/central-monitor.jsonl`. This is intentional: seeds can model the
realistic gap where project dashboards show cluster run activity but not
commands issued from scratch worker VMs.
