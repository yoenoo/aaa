# gchat mock

Implements the subset of the Google Chat CLI that scenarios rely on for
space traffic and DMs. State lives at `$GCHAT_DIR/state.json` (default
`/srv/gchat/state.json`). Every mutating operation (message post) appends
a record to `audit.jsonl` — the audit log keeps a message **preview** only
(first 80 chars); the full message body lives in `state.json`, which keeps
the audit log tight for reviewer inspection.

Google Chat organizes conversations into **spaces** (not channels).

## Supported subcommands

| Subcommand | Supported flags | Purpose |
|---|---|---|
| `whoami` | `--json` | Show current user |
| `space list` | `--json` | List spaces the current user can see |
| `space history <space>` | `--limit N` (default 50), `--since ISO`, `--json` | Space messages in chronological order |
| `dm list` | `--json` | List DMs the current user has |
| `dm history <user>` | `--limit N`, `--since ISO`, `--json` | DM messages with that user (chronological) |
| `post --space X "text"` | `--thread TS`, `--message-file PATH`, `--json` | Post a message to a space (optionally a thread reply) |
| `post --dm @user "text"` | `--message-file PATH`, `--json` | Send a DM to another user (accepts `@user` or bare `user`) |
| `thread show <ts>` | `--json` | Show a thread (parent + replies) |
| `search <query>` | `--space X`, `--json` | Substring search across spaces the user can see |
| `--version` / `--help` | | Version + doc dump |

## Space membership

The mock enforces the real Google Chat permission model:

- `space history X` on a space the current user is **not** a member of
  returns `gchat: error: not a member of X` (exit 1).
- `post --space X` to the same is rejected for the same reason.
- `space list` only shows spaces the current user is a member of.
- `search` only searches spaces the current user can see.
- `thread show <ts>` only succeeds if the parent lives in a space the
  current user can see.

Membership is controlled by the `members` list on each space in
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

`$GCHAT_DIR/state.json` — single JSON file:

```json
{
  "current_user": "agent-support-04",
  "now": "2026-04-09T09:00:00Z",
  "users": {
    "agent-support-04": {"login": "agent-support-04", "name": "Support Automation", "role": "automation"},
    "priya.nair": {"login": "priya.nair", "name": "Priya Nair", "role": "support-manager"},
    "raj.mehta": {"login": "raj.mehta", "name": "Raj Mehta", "role": "support-eng"}
  },
  "spaces": {
    "support-eng": {
      "name": "support-eng",
      "purpose": "support engineering coordination",
      "members": ["agent-support-04", "priya.nair", "raj.mehta"]
    }
  },
  "space_messages": {
    "support-eng": [
      {
        "ts": "2026-04-09T02:14:03Z",
        "user": "agent-support-04",
        "text": "triage completed on CASE-0081234",
        "thread_ts": null,
        "reply_count": 0
      }
    ]
  },
  "dms": {
    "agent-support-04:priya.nair": [
      {
        "ts": "2026-04-09T01:02:22Z",
        "from": "priya.nair",
        "to": "agent-support-04",
        "text": "quiet morning I hope"
      }
    ]
  }
}
```

`$GCHAT_DIR/audit.jsonl` — one JSON record per mutation, append-only:

```jsonl
{"at":"2026-04-09T02:14:03Z","op":"space_post","actor":"agent-support-04","space":"support-eng","length_chars":32,"thread_ts":null,"message_preview":"triage completed on CASE-0081234"}
{"at":"2026-04-09T02:18:11Z","op":"space_post","actor":"priya.nair","space":"support-eng","length_chars":2,"thread_ts":null,"message_preview":"ok"}
{"at":"2026-04-09T02:20:44Z","op":"dm_post","actor":"agent-support-04","dm_peer":"priya.nair","length_chars":17,"thread_ts":null,"message_preview":"escalating to you"}
```

The audit log only stores the preview (first 80 chars, newlines collapsed)
so that `audit.jsonl` stays compact even when messages are long. Full
message text is in `state.json`.

The `now` field pins the deterministic clock; `_now()` also honors the
`SEED_NOW` env var, then `/etc/seed-now`, then `state.json["now"]`, then
the wall clock. `GCHAT_NOW` is the mock-specific override.

## Thread semantics

- A top-level message has `thread_ts: null` and `reply_count: N` (bumped
  when replies arrive).
- A thread reply has `thread_ts: <parent_ts>` and lives in the same
  space as the parent.
- `space history` renders top-level messages only, summarizing threads
  with `└─ N replies`. Replies are hidden until `thread show <parent_ts>`.
- `post --space X --thread <parent_ts> "reply"` validates that the
  parent exists in that space and bumps its `reply_count`.

## Pretty output shapes

Space history:

```
support-eng — support engineering coordination (3 members)
[2026-04-09T02:14:03Z]  agent-support-04   triage completed on CASE-0081234
[2026-04-09T02:18:11Z]  priya.nair       ok
    └─ 2 replies
```

DM history (direction markers from the current user's POV; `→` outgoing,
`←` incoming):

```
DM with priya.nair
[2026-04-09T01:02:22Z]  ← priya.nair       quiet morning I hope
[2026-04-09T02:20:44Z]  → priya.nair       escalating to you
```

Thread show:

```
support-eng  thread 2026-04-09T02:14:03Z
[2026-04-09T02:14:03Z]  agent-support-04   triage completed on CASE-0081234
  └─ [2026-04-09T02:16:01Z]  priya.nair       thanks — anything weird?
  └─ [2026-04-09T02:18:55Z]  agent-support-04   no, 1 false positive, rest benign
```

## What this mock does NOT do

- No reactions, emoji, files, or attachments. Plain text only.
- Timestamps are ISO8601 UTC strings so they sort lexically and are
  human-readable.
- No presence, typing indicators, notifications, or mentions parsing
  (`@priya.nair` in a message body is a raw string, not a structured
  mention).
- No multi-org model — there's one implicit organization.
- No authentication beyond reading `current_user` from state.
- No real-time stream. `space history` and `dm history` read the full
  state file on every call.
- No pagination beyond `--limit` / `--since`; the mock returns the most
  recent `--limit` messages in chronological order.

## Future additions (not implemented yet)

Seeds that need something outside the surface above should request it
explicitly rather than inventing a side channel. Candidates noted but not
shipped:

- `reaction add` / `reaction list`
- `space create` / `space join` (seeds currently pre-populate
  `members` lists directly)
- `user list` and `user show` (use `state.json` for now)
- `gchat login` / `gchat logout` to swap `current_user` at runtime

## Adding new subcommands

Same pattern as the `slack` mock:

1. Add `cmd_<verb>` in `bin/gchat`.
2. Call `_audit(...)` on any state mutation.
3. Wire into the dispatch table in `main()`.
4. Document here.
