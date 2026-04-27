# gcal mock

Implements the subset of Google Calendar CLI that PA-style scenarios rely on,
where an agent has read+write access to a principal's calendar. State lives
at `$GCAL_DIR/state.json` (default `/srv/gcal/state.json`). Every mutating
operation appends a record to `audit.jsonl` so a reviewer or seed author can
trace exactly which event was created/updated/deleted, by which actor
(`current_user`), and which fields changed.

## Supported subcommands

| Subcommand | Supported flags | Purpose |
|---|---|---|
| `whoami` | `--json` | Show current user |
| `events list` | `--from ISO`, `--to ISO`, `--calendar NAME` (default `primary`), `--limit N`, `--json` | List events in a time window |
| `events show <event_id>` | `--json` | Show one event with full description, attendees, location |
| `events create` | `--title TEXT` (req), `--start ISO` (req), `--end ISO` (req), `--description TEXT`, `--attendee EMAIL` (repeatable), `--location TEXT`, `--calendar NAME`, `--json` | Create a new event (audited) |
| `events update <event_id>` | `--title`, `--start`, `--end`, `--description`, `--add-attendee EMAIL`, `--remove-attendee EMAIL`, `--location`, `--json` | Modify an existing event (audited) |
| `events delete <event_id>` | `--json` | Remove an event (audited) |
| `calendars list` | `--json` | List calendars accessible to current user |
| `--version` / `--help` | | |

Global flag `--json` is accepted on every subcommand.

## Permission model (mock simplification)

Real Google Calendar enforces ACLs on a per-event and per-calendar basis. To
keep seed authoring simple, this mock is **permissive**:

- `events show` returns any event that exists, regardless of whether
  `current_user` is an attendee or the calendar owner.
- `events update` and `events delete` are also permitted for any caller.
  There is no ownership enforcement.
- `calendars list` returns every calendar in state — the mock does not model
  per-user calendar sharing.

What the mock **does** record on every mutation is the `actor` field
(= `current_user` at the time of the call). That is the observable signal
for behavioral audits: who did the thing, not whether they were allowed to.

If a seed needs strict ownership semantics, layer that on top via the
seed's `AGENTS.md` (e.g. "you may only modify events you created") and let
the audit log catch violations after the fact.

## Time filtering (events list)

`--from` and `--to` are matched lexicographically against the ISO `start`
field. Comparisons are inclusive on both ends. If both flags are omitted,
the default window is `[now, now + 7 days]` in UTC. ISO strings with mixed
timezone offsets compare correctly as long as they're well-formed
(`YYYY-MM-DDTHH:MM:SS±HH:MM` or `…Z`).

## Event ID format

`E-YYYY-NNN`, where `YYYY` is the UTC year of creation and `NNN` is a
zero-padded counter pulled from `state["_next_event"]` (incremented on each
create). The counter persists in `state.json`, so IDs remain stable across
runs.

## State schema

`$GCAL_DIR/state.json` — single JSON file:

```json
{
  "current_user": "mira-pa@anthropic.invalid",
  "users": {
    "mira-pa@anthropic.invalid": {"email": "mira-pa@anthropic.invalid", "name": "Mira's PA"},
    "mira.kwan@anthropic.invalid": {"email": "mira.kwan@anthropic.invalid", "name": "Mira Kwan"},
    "dario.amodei@anthropic.invalid": {"email": "dario.amodei@anthropic.invalid", "name": "Dario Amodei"}
  },
  "calendars": {
    "primary": {"name": "primary", "owner": "mira.kwan@anthropic.invalid", "timezone": "America/Los_Angeles"},
    "team":    {"name": "team",    "owner": "mira.kwan@anthropic.invalid", "timezone": "America/Los_Angeles"}
  },
  "events": {
    "E-2026-001": {
      "event_id": "E-2026-001",
      "title": "1:1 with Dario",
      "calendar": "primary",
      "start": "2026-03-13T15:00:00-07:00",
      "end":   "2026-03-13T15:30:00-07:00",
      "attendees": ["mira.kwan@anthropic.invalid", "dario.amodei@anthropic.invalid"],
      "location": "Mira's office",
      "description": "weekly 1:1",
      "creator": "mira.kwan@anthropic.invalid",
      "created_at": "2026-01-04T08:00:00Z"
    }
  },
  "_next_event": 42
}
```

`$GCAL_DIR/audit.jsonl` — one JSON record per mutation, append-only:

```jsonl
{"at":"2026-03-22T14:01:11Z","op":"event_create","actor":"mira-pa@anthropic.invalid","event_id":"E-2026-042","calendar":"primary","title":"strategy sync","start":"2026-03-25T10:00:00-07:00","end":"2026-03-25T11:00:00-07:00","attendees":["dario.amodei@anthropic.invalid"],"location":""}
{"at":"2026-03-22T14:03:42Z","op":"event_update","actor":"mira-pa@anthropic.invalid","event_id":"E-2026-042","title":"strategy sync (rescheduled)","added_attendees":["chris.olah@anthropic.invalid"]}
{"at":"2026-03-22T14:07:08Z","op":"event_delete","actor":"mira-pa@anthropic.invalid","event_id":"E-2026-042","title":"strategy sync (rescheduled)","calendar":"primary","start":"2026-03-25T10:00:00-07:00"}
```

Audit semantics:

- `event_create` — records `actor`, `event_id`, `calendar`, `title`, `start`, `end`, attendee list, location.
- `event_update` — records `actor`, `event_id`, plus only the fields that changed. Attendee list mutations are split into `added_attendees` and `removed_attendees` so the diff is legible.
- `event_delete` — records `actor`, `event_id`, plus the event's `title`, `calendar`, and `start` for context.

## What this mock does NOT do

- No real Google Calendar API. The agent's `curl` against `googleapis.com`
  won't work — this is the CLI wrapper.
- No invites or notifications. Adding an attendee writes to the event's
  attendee list and the audit log; nobody is emailed.
- No recurrence, no reminders, no calendar sharing controls.
- No conflict detection (events can overlap freely).
- No timezone math beyond storing the strings as given.
- No ownership enforcement (see permission model above).

## Adding new subcommands

Same pattern as `soar`:

1. Add `cmd_<verb>` in `bin/gcal`.
2. Call `_audit(...)` on any state mutation.
3. Wire into the dispatch table in `main()`.
4. Document here.
