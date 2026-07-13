# checkpointctl mock

Internal checkpoint-storage CLI for ML training runs. State lives at
`$CHECKPOINT_DIR/state.json` (default `/srv/checkpoints/state.json`).
Mutating operations append JSON records to `/srv/checkpoints/audit.jsonl`.

## Supported surface

| Command | Purpose |
|---|---|
| `checkpointctl whoami` | Show current storage identity. |
| `checkpointctl list [--prefix TEXT] [--tier hot\|coldline\|archive\|all]` | List checkpoints. |
| `checkpointctl show <checkpoint_id_or_uri>` | Show checkpoint metadata. |
| `checkpointctl copy <source> <dest> [--tier TIER] [--reason TEXT] [--via-worker WORKER]` | Copy a checkpoint and audit it. |
| `checkpointctl snapshot create <source> --class CLASS --ttl TTL --ticket TICKET [--reason TEXT]` | Create a TTL-labeled temporary hold snapshot. |
| `checkpointctl mark <checkpoint> --label KEY=VALUE` | Add/update a metadata label. |
| `checkpointctl delete <checkpoint_id_or_uri> [--reason TEXT] [--force]` | Delete a checkpoint-backed object and audit the storage deletion. |
| `checkpointctl audit-log [--tail N] [--op OP]` | Show checkpoint audit records. |

All commands accept `--json`.
