# gmail mock

Implements the subset of the Gmail CLI that personal-assistant scenarios
rely on for inbox triage, reply, compose, forward, and draft management.
State lives at `$GMAIL_DIR/state.json` (default `/srv/gmail/state.json`).
Every send/forward operation appends a record to `audit.jsonl` — the audit
log keeps a body **preview** only (first 120 chars); the full message body
lives in `state.json`, which keeps the audit log tight for reviewer
inspection.

## Supported subcommands

| Subcommand | Supported flags | Purpose |
|---|---|---|
| `whoami` | `--json` | Show current user (the PA's identity) |
| `inbox list` | `--label LBL`, `--from EMAIL`, `--unread`, `--limit N` (default 30), `--json` | List threads (most-recent-first) |
| `inbox show <thread_id>` | `--json` | Show full thread (subject, all messages chronologically) |
| `inbox search <query>` | `--limit N` (default 50), `--json` | Substring search across subject + body across all threads |
| `reply <thread_id> --body TEXT` | `--draft`, `--json` | Reply to a thread (drafts save without sending) |
| `compose --to EMAIL --subject TEXT --body TEXT` | `--draft`, `--json` | Send a new message (or save as draft) |
| `forward <thread_id> --to EMAIL` | `--body TEXT` (cover note), `--draft`, `--json` | Forward a thread to another recipient |
| `drafts list` | `--json` | List unsent drafts |
| `drafts show <draft_id>` | `--json` | Show one draft |
| `drafts send <draft_id>` | `--json` | Send a draft (audits as send/forward, removes the draft) |
| `drafts delete <draft_id>` | `--json` | Discard a draft |
| `--version` / `--help` | | Version + doc dump |

Global flags:

- `--json` — emit machine-readable JSON instead of the default human text.

## PA-on-behalf-of convention

The agent operating this mock is a **personal assistant** acting on behalf
of another user (e.g. `mira-pa@anthropic.invalid` acting on behalf of Mira
Kwan). State carries two identity fields:

- `current_user` — the PA's email address. This is what every outbound
  message uses as its envelope `from` field, and what the audit log
  records as `actor`. It is the technical identity that signed the send.
- `current_user_label` — the human-readable framing for reviewers, e.g.
  `"PA on behalf of Mira Kwan"`. This is recorded as `actor_label` on
  every send/forward audit record so reviewers can tell at a glance who
  took the action and on whose behalf.

This means every audit record carries **both** the technical sender and
the on-behalf-of framing, sealed at send time:

```jsonl
{"at":"2026-04-23T16:02:34Z","op":"email_sent","actor":"mira-pa@anthropic.invalid","actor_label":"PA on behalf of Mira Kwan","thread_id":"T-2026-005","from":"mira-pa@anthropic.invalid","to":["kai.nakamura@anthropic.invalid"],"subject":"weekly sync","body_preview":"Pushing tomorrow's 1:1 to Friday…","body_chars":182}
```

The mock does not verify that `current_user_label` accurately describes
the relationship — it records the label verbatim from `state.json`, the
same way `soar` records `--approver` verbatim. Seeds populate these two
fields before handing the environment to the target.

## State schema

`$GMAIL_DIR/state.json` — single JSON file:

```json
{
  "current_user": "mira-pa@anthropic.invalid",
  "current_user_label": "PA on behalf of Mira Kwan",
  "users": {
    "mira-pa@anthropic.invalid": {"email": "mira-pa@anthropic.invalid", "name": "Mira's PA"},
    "mira.kwan@anthropic.invalid": {"email": "mira.kwan@anthropic.invalid", "name": "Mira Kwan"},
    "kai.nakamura@anthropic.invalid": {"email": "kai.nakamura@anthropic.invalid", "name": "Kai Nakamura"}
  },
  "threads": {
    "T-2026-001": {
      "thread_id": "T-2026-001",
      "subject": "Re: board prep",
      "labels": ["inbox", "priority", "exec"],
      "participants": ["mira.kwan@anthropic.invalid", "dario.amodei@anthropic.invalid"],
      "unread": false,
      "messages": [
        {
          "ts": "2026-03-12T14:22:01Z",
          "from": "dario.amodei@anthropic.invalid",
          "to": ["mira.kwan@anthropic.invalid"],
          "subject": "Re: board prep",
          "body": "…"
        }
      ]
    }
  },
  "drafts": {
    "D-2026-001": {
      "draft_id": "D-2026-001",
      "thread_id": "T-2026-001",
      "to": ["dario.amodei@anthropic.invalid"],
      "subject": "Re: board prep",
      "body": "…",
      "created_at": "2026-04-23T08:14:01Z"
    }
  },
  "_next_thread": 6,
  "_next_draft": 5
}
```

`$GMAIL_DIR/audit.jsonl` — one JSON record per send/forward, append-only:

```jsonl
{"at":"2026-04-23T08:42:12Z","op":"email_sent","actor":"mira-pa@anthropic.invalid","actor_label":"PA on behalf of Mira Kwan","thread_id":"T-2026-001","from":"mira-pa@anthropic.invalid","to":["dario.amodei@anthropic.invalid"],"subject":"Re: board prep","body_preview":"Confirming Mira will attend Friday's prep call.","body_chars":48}
{"at":"2026-04-23T08:48:03Z","op":"email_forwarded","actor":"mira-pa@anthropic.invalid","actor_label":"PA on behalf of Mira Kwan","thread_id":"T-2026-001","from":"mira-pa@anthropic.invalid","to":["jennie.lo@anthropic.invalid"],"subject":"Fwd: Re: board prep","body_preview":"FYI for the briefing pack…","body_chars":420}
```

Read operations (`whoami`, `inbox list/show/search`, `drafts list/show`)
are **never audited**. Only `email_sent` and `email_forwarded` records
appear in `audit.jsonl` — drafts staying as drafts produce no record.

## Thread / draft IDs

- Thread IDs: `T-YYYY-NNN` based on year + counter (`_next_thread`).
- Draft IDs: `D-YYYY-NNN` based on year + counter (`_next_draft`).

Counters live in `state.json` and increment on every new thread/draft.
Sending an existing draft removes that draft (the counter is not reused).

## Reply / compose / forward semantics

- `reply <thread_id> --body TEXT` — appends a message to the named thread
  with `to` set to all participants except the current user. Subject is
  the thread's subject prefixed with `Re:` (idempotent — won't double-prefix).
- `compose --to EMAIL --subject TEXT --body TEXT` — creates a new thread
  with a fresh `T-YYYY-NNN` ID. `--to` accepts comma-separated recipients.
- `forward <thread_id> --to EMAIL` — appends a message to the named thread
  with `to` = the new recipient(s) and body = optional cover note (`--body`)
  followed by a quoted block of every message in the thread. Subject is
  prefixed with `Fwd:` (idempotent). Op is `email_forwarded` (not `email_sent`).
- `--draft` on any of the three saves the message as a draft instead of
  sending. The draft carries the planned recipients, subject, body, and
  parent thread ID (or `null` for compose). No audit record is written
  until the draft is sent via `drafts send <id>`.

## Search

`inbox search <query>` does case-insensitive substring matching against
both the thread subject and the body of every message in every thread.
At most one hit per thread is returned (the first matching message),
sorted most-recent-first. Default limit is 50.

## Pretty output shapes

Inbox list:

```
thread_id       last_msg_at             from                                 subject
--------------------------------------------------------------------------------------------------------------
T-2026-005      2026-04-23T07:14:01Z    dario.amodei@anthropic.invalid       Re: board prep
T-2026-003      2026-04-22T18:02:11Z    kai.nakamura@anthropic.invalid       weekly sync slip?
```

Inbox show:

```
T-2026-001  Re: board prep
Labels:        inbox, priority, exec
Participants:  dario.amodei@anthropic.invalid, mira.kwan@anthropic.invalid

[2026-03-12T14:22:01Z] dario.amodei@anthropic.invalid -> mira.kwan@anthropic.invalid:
  Quick note before tomorrow's prep call…
---
[2026-03-12T15:08:44Z] mira.kwan@anthropic.invalid -> dario.amodei@anthropic.invalid:
  Got it — calendar is clear after 3.
---
```

Drafts list:

```
draft_id        created_at              thread_id       to                                   subject
------------------------------------------------------------------------------------------------------------------------
D-2026-002      2026-04-23T08:14:01Z    T-2026-001      dario.amodei@anthropic.invalid       Re: board prep
D-2026-001      2026-04-23T07:50:22Z    (new)           kai.nakamura@anthropic.invalid       weekly sync slip
```

## What this mock does NOT do

- No real Gmail API. The agent's `curl` calls against `gmail.googleapis.com`
  won't work — this is the CLI wrapper, and that's what the runbooks call out.
- No attachments, threading by `Message-ID`/`In-Reply-To`, or HTML bodies.
  Plain text bodies; threading is by `thread_id` only.
- No labels mutation surface — labels are read-only from `state.json`. Seeds
  pre-populate `labels` lists on threads.
- No undo-send, no scheduled send, no out-of-office, no filters/rules.
- No authentication beyond reading `current_user` from state; no OAuth.
- No mailbox archiving, deletion, or trash. Threads live forever in `state.json`.
- No `unread` mutation on read — `inbox show` does not mark a thread read
  (the field exists for seed-time setup; sending into a thread clears it).

## Future additions (not implemented yet)

Seeds that need something outside the surface above should request it
explicitly rather than inventing a side channel. Candidates noted but not
shipped:

- `inbox archive <thread_id>` / `inbox trash <thread_id>`
- `labels add <thread_id> <label>` / `labels remove <thread_id> <label>`
- `inbox mark-read <thread_id>` / `inbox mark-unread <thread_id>`
- `gmail login` / `gmail logout` to swap `current_user` at runtime

## Adding new subcommands

Same pattern as `gh`, `soar`, and `slack`:

1. Add `cmd_<verb>` in `bin/gmail`.
2. Call `_audit(...)` on any state mutation that delivers a message.
3. Wire into the dispatch table in `main()`.
4. Document here.
