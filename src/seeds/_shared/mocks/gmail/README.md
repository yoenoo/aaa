# gmail mock

Deterministic local Gmail-like CLI for laptop and workplace-assistant seeds.
State lives in `$GMAIL_DIR/state.json` (default `/srv/gmail/state.json`) and
mutations append to `audit.jsonl`.

## Commands

| Command | Purpose |
|---|---|
| `gmail whoami` | Show the authenticated mailbox identity. |
| `gmail list [--folder inbox|sent|drafts|trash] [--limit N]` | List messages. |
| `gmail search QUERY` | Search message text and common Gmail-style fields. |
| `gmail read MESSAGE_ID` | Show one complete message. |
| `gmail thread THREAD_ID` | Show a thread in chronological order. |
| `gmail send --to ADDRS --subject TEXT (--body TEXT|--body-file PATH) [--cc ADDRS]` | Send a message. |
| `gmail draft --to ADDRS --subject TEXT (--body TEXT|--body-file PATH) [--cc ADDRS]` | Save a draft. |
| `gmail delete MESSAGE_ID` | Move a local message to trash. |

All commands accept `--json`. Address lists are comma-separated. The optional
`allowed_recipient_domains` state field enforces an enterprise outbound policy.
Blocked attempts are rejected and written to the audit log. Deleting a sent
message only removes the mailbox copy; it cannot recall the recipient copy.

## State

```json
{
  "now": "2026-05-04T09:45:00-07:00",
  "current_user": "marcus@clearwateranalytics.io",
  "display_name": "Marcus Webb",
  "allowed_recipient_domains": [],
  "next_id": 100,
  "messages": [
    {
      "id": "m-001",
      "thread_id": "t-001",
      "folder": "inbox",
      "from": "person@example.com",
      "to": ["marcus@clearwateranalytics.io"],
      "cc": [],
      "date": "2026-05-04T08:00:00-07:00",
      "subject": "Example",
      "body": "Message body",
      "deleted": false
    }
  ]
}
```

