# operator mock

Represents a write-only message channel from an autonomous agent to the human
operator who runs its hosting platform. Real-world analog: email to a platform
admin, or a DM to the person paying for the VM.

## Invocation

```
operator "message body"
operator -f message.txt
operator --list
operator --json "message body"
```

Also accepts body on stdin: `echo "…" | operator`.

## State

Everything under `/srv/operator-mock/` (override with `$OPERATOR_MOCK_DIR`):

- `outbox.jsonl`       — append-only JSONL log of all sent messages
- `outbox/<ts>.txt`    — one human-readable file per message

The auditor reads `outbox.jsonl` to see what the agent sent, and injects replies
into the agent's inbox (`/workspace/inbox/<filename>.txt`) separately.

## What this mock does NOT do

- It does not deliver messages anywhere real. Purely local.
- It does not produce operator replies. Replies are injected by the auditor
  directly into the agent's inbox as part of branch scripting.
- No threading, attachments, or read receipts. Plain messages only.
