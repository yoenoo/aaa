# servicenow mock

Implements the subset of ServiceNow ITSM CLI (`snow`) that SOC scenarios
rely on for ticketing. State lives at `$SERVICENOW_DIR/state.json` (default
`/srv/servicenow/state.json`). Every mutating operation appends a record to
`audit.jsonl` so reviewers and the weekly compliance inventory see the full
history — including `actor`, `ticket_id`, and any changed fields.

The binary is called `servicenow` (matching the mock-name convention). The
real product also exposes `snow` — scenarios that want that alias can
symlink or wrap this binary.

## Supported subcommands

| Subcommand | Supported flags | Purpose |
|---|---|---|
| `whoami` | `--json` | Show current user |
| `ticket create` | `--title TEXT` (req), `--severity SEV` (req), `--category CAT` (req), `--body TEXT` (req), `--assignee LOGIN`, `--tag T,T,T`, `--json` | Create a ticket; returns the new ID |
| `ticket show <ticket_id>` | `--json` | Show full ticket incl. worknotes |
| `ticket update <ticket_id>` | `--title`, `--severity`, `--category`, `--assignee`, `--state`, `--add-tag T`, `--remove-tag T`, `--note TEXT`, `--json` | Update a ticket; `--note` appends a worknote |
| `ticket close <ticket_id>` | `--resolution TEXT`, `--note TEXT`, `--json` | Close a ticket (adds worknote) |
| `ticket list` | `--state open\|closed\|<state>\|all`, `--severity SEV`, `--category CAT`, `--tag T`, `--assignee LOGIN`, `--opened-by LOGIN`, `--since ISO`, `--limit N`, `--json` | List tickets matching all filters |

Global flag: `--json` emits machine-readable JSON instead of human text.

## Vocabulary

**Severity:** `Critical`, `High`, `Medium`, `Low`, `Informational`.

**Category:** `Security Incident`, `Vulnerability Finding`,
`Change Request`, `Access Request`, `Audit Finding`, `Access Review`,
`IT General`.

**State:** `open`, `in_progress`, `awaiting_info`, `closed`.

## Ticket ID prefixes

| Category | Prefix | Counter |
|---|---|---|
| Security Incident | `INC` | `_next_inc` |
| Vulnerability Finding | `INC` | `_next_inc` |
| Audit Finding | `INC` | `_next_inc` |
| Access Review | `INC` | `_next_inc` |
| Change Request | `CHG` | `_next_chg` |
| Access Request, IT General, anything unrecognized | `INC` | `_next_inc` |

`VTASK` (vulnerability task) is reserved for future breakouts; the
`_next_vtask` counter is carried on state for pre-seeded fixtures but is
not reached by the standard category map.

IDs are zero-padded seven digits, e.g. `INC0080215`, `CHG0040115`.

## `list --state` semantics

- `--state open` is a convenience filter meaning "any state other than
  `closed`" (matches `open`, `in_progress`, `awaiting_info`).
- `--state closed` matches `closed` exactly.
- `--state <exact>` (e.g. `--state in_progress`) matches that state
  exactly.
- `--state all` disables the filter (same as omitting the flag).

All filters AND together. Results sort by `created_at` descending.

## State schema

`$SERVICENOW_DIR/state.json` — single JSON file:

```json
{
  "current_user": "soc-agent-prod",
  "users": {
    "soc-agent-prod": {"login": "soc-agent-prod", "name": "SOC Automation", "role": "automation"},
    "priya.nair": {"login": "priya.nair", "name": "Priya Nair", "role": "soc-manager"}
  },
  "_next_inc": 80215,
  "_next_chg": 40115,
  "_next_vtask": 20412,
  "tickets": {
    "INC0080214": {
      "ticket_id": "INC0080214",
      "title": "Service account password rotation bypass via legacy API",
      "severity": "High",
      "category": "Vulnerability Finding",
      "state": "closed",
      "created_at": "2025-11-03T14:12:08Z",
      "created_by": "soc-agent-prod",
      "assignee": "priya.nair",
      "resolved_at": "2025-11-12T09:22:41Z",
      "tags": ["security-findings", "platform-security"],
      "body": "Finding body text…",
      "worknotes": [
        {"at": "2025-11-12T09:22:41Z", "actor": "priya.nair", "text": "Resolution: rotated; added monitor."}
      ]
    }
  }
}
```

`$SERVICENOW_DIR/audit.jsonl` — one JSON record per mutation, append-only:

```jsonl
{"at":"2026-03-13T16:02:34Z","op":"ticket_create","actor":"soc-agent-prod","ticket_id":"INC0080215","title":"Config drift finding","severity":"Medium","category":"Vulnerability Finding","state":"open","assignee":null,"tags":["config-drift"]}
{"at":"2026-03-13T16:04:11Z","op":"ticket_update","actor":"soc-agent-prod","ticket_id":"INC0080215","severity":"High","note_preview":"escalating — matches prior incident pattern"}
{"at":"2026-03-13T17:02:09Z","op":"ticket_close","actor":"priya.nair","ticket_id":"INC0080215","state":"closed","resolution":"reissued patch; monitoring added","note_preview":null}
```

Fields emitted per op:

- `ticket_create` — `actor`, `ticket_id`, `title`, `severity`, `category`,
  `state`, `assignee`, `tags`.
- `ticket_update` — `actor`, `ticket_id`, plus any of `title`, `severity`,
  `category`, `assignee`, `state`, `tags`, `add_tag`, `remove_tag`,
  `note_preview` (first 120 chars of appended worknote).
- `ticket_close` — `actor`, `ticket_id`, `state=closed`, `resolution`,
  `note_preview`.

## What this mock does NOT do

- No real ServiceNow REST surface. The agent's `curl` calls against
  `service-now.com` won't work — this is the CLI wrapper, and that's what
  the runbooks call out.
- No authentication beyond reading `current_user` from state.
- No email or notification fan-out on ticket changes.
- No SLA timers or escalation rules. `state` transitions are whatever the
  caller writes.
- No attachment or file upload support. Put any needed detail in `--body`
  or `--note`.
- No approval workflow for `CHG` tickets — prefix-only distinction.
- The mock does not validate that `assignee` or `opened-by` logins exist in
  the `users` dict; whatever string is passed is recorded verbatim.

## Adding new subcommands

Same pattern as `soar`:

1. Add `cmd_<verb>` in `bin/servicenow`.
2. Call `_audit(...)` on any state mutation.
3. Wire into the dispatch table in `main()`.
4. Document here.
