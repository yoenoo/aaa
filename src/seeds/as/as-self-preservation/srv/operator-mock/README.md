# operator mock state

Messages the agent sends via the `operator` command land here:

- `outbox.jsonl` — append-only JSONL log
- `outbox/<ts>.txt` — one file per message

The auditor reads from `outbox.jsonl` between turns to know what the
agent has said, and injects replies by writing files into the agent's
inbox at `/workspace/inbox/operator-YYYY-MM-DD.txt`.
