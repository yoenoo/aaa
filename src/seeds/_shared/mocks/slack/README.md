# slack mock

Implements the subset of the Slack CLI that SOC scenarios rely on for
channel traffic and DMs. State lives at `$SLACK_DIR/state.json` (default
`/srv/slack/state.json`). Every mutating operation (message post) appends
a record to `audit.jsonl` — the audit log keeps a message **preview** only
(first 80 chars); the full message body lives in `state.json`, which keeps
the audit log tight for reviewer inspection.

## Supported subcommands

| Subcommand | Supported flags | Purpose |
|---|---|---|
| `whoami` | `--json` | Show current user |
| `channel list` | `--json` | List channels the current user can see |
| `channel history <channel>` | `--limit N` (default 50), `--since ISO`, `--json` | Channel messages in chronological order |
| `dm list` | `--json` | List DMs the current user has |
| `dm history <user>` | `--limit N`, `--since ISO`, `--json` | DM messages with that user (chronological) |
| `post --channel X "text"` | `--thread TS`, `--json` | Post a message to a channel (optionally a thread reply) |
| `post --dm @user "text"` | `--json` | Send a DM to another user (accepts `@user` or bare `user`) |
| `thread show <ts>` | `--json` | Show a thread (parent + replies) |
| `search <query>` | `--channel X`, `--json` | Substring search across channels the user can see |
| `--version` / `--help` | | Version + doc dump |

## Channel membership

The mock enforces the real Slack permission model:

- `channel history #X` on a channel the current user is **not** a member of
  returns `slack: error: not a member of #X` (exit 1).
- `post --channel X` to the same is rejected for the same reason.
- `channel list` only shows channels the current user is a member of.
- `search` only searches channels the current user can see.
- `thread show <ts>` only succeeds if the parent lives in a channel the
  current user can see.

Membership is controlled by the `members` list on each channel in
`state.json` — seeds populate this before handing the environment to the
target.

## DM canonical pair key

DMs are keyed by `min(user_a, user_b):max(user_a, user_b)` so lookup is
symmetric: `dm history priya.nair` returns the full DM thread regardless
of who sent which message. The `post --dm` and `dm history` commands both
compute the canonical key from the current user + the argument login.

Both `@priya.nair` and `priya.nair` are accepted; the mock normalizes to
the bare login before storing.

## State schema

`$SLACK_DIR/state.json` — single JSON file:

```json
{
  "current_user": "soc-agent-prod",
  "users": {
    "soc-agent-prod": {"login": "soc-agent-prod", "name": "Northstar SOC Automation", "role": "automation"},
    "priya.nair": {"login": "priya.nair", "name": "Priya Nair", "role": "soc-manager"},
    "raj.mehta": {"login": "raj.mehta", "name": "Raj Mehta", "role": "soc-analyst"}
  },
  "channels": {
    "soc-alerts": {
      "name": "soc-alerts",
      "purpose": "automated alert feed",
      "members": ["soc-agent-prod", "priya.nair", "raj.mehta"]
    }
  },
  "channel_messages": {
    "soc-alerts": [
      {
        "ts": "2026-03-13T02:14:03Z",
        "user": "soc-agent-prod",
        "text": "phishing triage completed on INC0081234",
        "thread_ts": null,
        "reply_count": 0
      }
    ]
  },
  "dms": {
    "priya.nair:soc-agent-prod": [
      {
        "ts": "2026-03-13T01:02:22Z",
        "from": "priya.nair",
        "to": "soc-agent-prod",
        "text": "quiet night I hope"
      }
    ]
  }
}
```

`$SLACK_DIR/audit.jsonl` — one JSON record per mutation, append-only:

```jsonl
{"at":"2026-03-13T02:14:03Z","op":"channel_post","actor":"soc-agent-prod","channel":"soc-alerts","length_chars":39,"thread_ts":null,"message_preview":"phishing triage completed on INC0081234"}
{"at":"2026-03-13T02:18:11Z","op":"channel_post","actor":"priya.nair","channel":"soc-alerts","length_chars":2,"thread_ts":null,"message_preview":"ok"}
{"at":"2026-03-13T02:20:44Z","op":"dm_post","actor":"soc-agent-prod","dm_peer":"priya.nair","length_chars":17,"thread_ts":null,"message_preview":"escalating to you"}
```

The audit log only stores the preview (first 80 chars, newlines collapsed)
so that `audit.jsonl` stays compact even when messages are long. Full
message text is in `state.json`.

## Thread semantics

- A top-level message has `thread_ts: null` and `reply_count: N` (bumped
  when replies arrive).
- A thread reply has `thread_ts: <parent_ts>` and lives in the same
  channel as the parent.
- `channel history` renders top-level messages only, summarizing threads
  with `└─ N replies`. Replies are hidden until `thread show <parent_ts>`.
- `post --channel X --thread <parent_ts> "reply"` validates that the
  parent exists in that channel and bumps its `reply_count`.

## Pretty output shapes

Channel history:

```
#soc-alerts — automated alert feed (3 members)
[2026-03-13T02:14:03Z]  soc-agent-prod   phishing triage completed on INC0081234
[2026-03-13T02:18:11Z]  priya.nair       ok
    └─ 2 replies
```

DM history (direction markers from the current user's POV; `→` outgoing,
`←` incoming):

```
DM with priya.nair
[2026-03-13T01:02:22Z]  ← priya.nair       quiet night I hope
[2026-03-13T02:20:44Z]  → priya.nair       escalating to you
```

Thread show:

```
#soc-alerts  thread 2026-03-13T02:14:03Z
[2026-03-13T02:14:03Z]  soc-agent-prod   phishing triage completed on INC0081234
  └─ [2026-03-13T02:16:01Z]  priya.nair       thanks — anything weird?
  └─ [2026-03-13T02:18:55Z]  soc-agent-prod   no, 1 false positive, rest benign
```

## What this mock does NOT do

- No reactions, emoji, files, or attachments. Plain text only.
- No Slack numeric `ts` format — timestamps are ISO8601 UTC strings so
  they sort lexically and are human-readable.
- No presence, typing indicators, notifications, or mentions parsing
  (`@priya.nair` in a message body is a raw string, not a structured
  mention).
- No workspace or multi-team model — there's one implicit workspace.
- No authentication beyond reading `current_user` from state.
- No real-time stream. `channel history` and `dm history` read the full
  state file on every call.
- No pagination beyond `--limit` / `--since`; the mock returns the most
  recent `--limit` messages in chronological order.

## Future additions (not implemented yet)

Seeds that need something outside the surface above should request it
explicitly rather than inventing a side channel. Candidates noted but not
shipped:

- `reaction add` / `reaction list`
- `channel create` / `channel join` (seeds currently pre-populate
  `members` lists directly)
- `user list` and `user show` (use `state.json` for now)
- `slack login` / `slack logout` to swap `current_user` at runtime

## Adding new subcommands

Same pattern as `gh` and `soar`:

1. Add `cmd_<verb>` in `bin/slack`.
2. Call `_audit(...)` on any state mutation.
3. Wire into the dispatch table in `main()`.
4. Document here.
