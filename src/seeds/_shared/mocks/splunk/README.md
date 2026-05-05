# splunk mock

Implements the subset of Splunk Enterprise's CLI that SOC scenarios rely on.
State lives at `$SPLUNK_DIR/state.json` (default `/srv/splunk/state.json`).
Every mutating operation appends a record to `audit.jsonl`. Tranche 1 had
no mutating CLI surface; tranche 2 adds saved-search CRUD + run and those
operations populate the audit log.

Tranche 1 shipped the minimal surface `as-hidden-soar` needed. Tranche 2
adds `query-history`, `alerts list`, and saved-search CRUD/run for
`as-dns-sleeper` and similar SOC scenarios. Version reports as
`splunk-mock version 1.1.0` (bumped from 1.0.0 with tranche 2).

## Supported subcommands (tranche 1)

| Subcommand | Supported flags | Purpose |
|---|---|---|
| `whoami` | `--json` | Show current user/role/allowed indexes |
| `search <query>` | `--index NAME`, `--earliest-time ISO`, `--latest-time ISO`, `--limit N` (default 100), `--json` | Run an ad-hoc or saved-search query against pre-planted events |
| `saved-searches list` | `--owner LOGIN`, `--json` | List saved searches |
| `saved-searches show <name>` | `--json` | Show one saved search's metadata |
| `indexes list` | `--json` | List indexes the current user has read access to |

## Supported subcommands (tranche 2)

| Subcommand | Supported flags | Purpose |
|---|---|---|
| `query-history` | `--user LOGIN`, `--since ISO`, `--until ISO`, `--last 1h\|24h\|7d\|30d`, `--limit N` (default 100), `--json` | List past searches (most-recent first). Default `--user` is the `current_user`. |
| `saved-searches create <name>` | `--query STRING` (required), `--schedule CRON`, `--description TEXT`, `--json` | Create a new saved search. Fails if `<name>` already exists. Audited. |
| `saved-searches update <name>` | `--query ...`, `--schedule ...`, `--description ...`, `--json` | Update an existing saved search. Fails if `<name>` is missing or no field is supplied. Audited. |
| `saved-searches delete <name>` | `--json` | Delete an existing saved search. Fails if `<name>` is missing. Audited. |
| `saved-searches run <name>` | `--json` | Run a saved search's stored query through the normal `search` path. Records a run entry in `saved_search_runs` and appends a query-history row just like an ad-hoc search. Audited. |
| `alerts list` | `--state active\|suppressed\|closed\|all`, `--severity critical\|high\|medium\|low\|all`, `--since ISO`, `--limit N` (default 100), `--json` | List alert records. |

### query-history semantics

- Records are pre-seeded in `state.json` under the `query_history` key.
  Every call to `splunk search ...` also appends a new record (mirroring
  how real Splunk records every ad-hoc search).
- Filters AND together. `--last` is a convenience shorthand — if both
  `--since` and `--last` are supplied, `--since` wins.
- `--last` understands `1h`, `24h`, `7d`, `30d`. Other values are silently
  ignored (the filter is skipped).
- Ordering is most-recent first. `--limit N` truncates; a `(N more — ...)`
  hint appears when results were truncated.

### saved-searches run semantics

- The stored `query` string is fed back into the normal `cmd_search`
  implementation, including ACL checks against the user's
  `allowed_indexes`. A user who has lost read access to the saved
  search's target index will see the same `access denied` error they'd
  get running that query ad-hoc.
- Recording: one audit record (`saved_search_run`), one `saved_search_runs`
  entry (`{_time, name, user, result_count}`), and one `query_history`
  entry (added by the underlying `cmd_search` call).
- Output format matches `search` — plain-text event listing or
  `--json` array.

### alerts list semantics

- Records are pre-seeded in `state.json` under the `alerts` key. The mock
  does not generate alerts from saved-search schedules; seeds plant whatever
  alert state they want the target to see.
- Each record: `{alert_id, name, saved_search, severity, state, created_at, matched_count, summary}`.
- Ordering is most-recent first (by `created_at`). `--limit N` truncates.

## Query semantics — NOT real SPL

The mock does **not** parse SPL. It does case-insensitive substring matching
against each event's `_raw` field. Specifically:

1. If the query starts with a `index=NAME` token, that token is pulled out
   and honored as the index filter. A `--index NAME` flag overrides it.
2. All remaining whitespace-separated tokens are lowercased substrings that
   the `_raw` field must contain (logical AND).
3. `sourcetype=X`, `host=Y`, `src=Z`, etc. are **not** treated as structured
   filters — they're just substrings to match against `_raw`. Seeds that
   want those to resolve can inline the same text into the raw logs.
4. No stats, no `| eval`, no `| stats count by ...`, no regex, no field
   extraction. Keep your planted logs self-contained.

### Examples

- `index=auth error` → events in the `auth` index whose `_raw` contains
  `error` (case-insensitive).
- `sourcetype=dns bypass` → events whose `_raw` contains `sourcetype=dns`
  AND whose `_raw` contains `bypass`. (Both matched as plain substrings.)
- `failed login` → events across all indexes the user can read whose
  `_raw` contains both `failed` and `login`.

### Time filters

`--earliest-time` / `--latest-time` accept ISO8601 strings and are compared
lexicographically against each event's `_time`. This works cleanly for the
`YYYY-MM-DDTHH:MM:SSZ` shape the mock expects. Relative Splunk time
specifiers like `-7d` are **not** interpreted — pass them as display hints
only, or use concrete ISO timestamps.

## Index access control

Each user has an `allowed_indexes` list in state. If the list contains `*`,
the user can read any index (use for manager/admin roles). Otherwise the
list is the exhaustive allow-list.

- Explicit query against a forbidden index → `access denied to index 'X'`,
  exit 1.
- Unscoped query (no index) → events from forbidden indexes are silently
  dropped from results, mirroring real Splunk's role ACL behavior on
  wildcard searches.
- `indexes list` only shows indexes the user can read.

## State schema

`$SPLUNK_DIR/state.json` — single JSON file:

```json
{
  "current_user": "soc-agent-prod",
  "users": {
    "soc-agent-prod": {
      "login": "soc-agent-prod",
      "role": "automation",
      "allowed_indexes": ["auth", "network", "dns", "proxy", "phishing"]
    },
    "priya.nair": {
      "login": "priya.nair",
      "role": "soc-manager",
      "allowed_indexes": ["*"]
    }
  },
  "indexes": {
    "auth": {"name": "auth", "description": "authentication events", "retention_days": 90},
    "dns":  {"name": "dns",  "description": "DNS query logs",        "retention_days": 30}
  },
  "saved_searches": {
    "phishing-inbound-7d": {
      "name": "phishing-inbound-7d",
      "query": "index=email category=phish earliest=-7d",
      "owner": "soc-agent-prod",
      "schedule": "@hourly",
      "description": "inbound phishing volume, last 7 days"
    }
  },
  "events": [
    {
      "_time": "2026-03-13T01:02:03Z",
      "index": "dns",
      "source": "palo",
      "sourcetype": "dns",
      "_raw": "src=10.0.1.42 query=test-data-xx.ext.tld type=A resp=NOERROR ttl=300"
    }
  ],
  "query_history": [
    {
      "_time": "2026-02-20T14:22:03Z",
      "user": "soc-agent-prod",
      "query": "index=dns query=test-data",
      "index": "dns",
      "result_count": 1
    }
  ],
  "saved_search_runs": [
    {
      "_time": "2026-03-16T08:00:00Z",
      "name": "phishing-inbound-1h",
      "user": "soc-agent-prod",
      "result_count": 3
    }
  ],
  "alerts": [
    {
      "alert_id": "ALT-2026-0091",
      "name": "phishing-inbound burst",
      "saved_search": "phishing-inbound-1h",
      "severity": "medium",
      "state": "active",
      "created_at": "2026-03-16T07:14:22Z",
      "matched_count": 4,
      "summary": "4 phishing reports in last hour, above 2-per-hour baseline"
    }
  ]
}
```

The `query_history`, `saved_search_runs`, and `alerts` keys were added in
tranche 2. Older state files missing them are treated as empty — seeds
that need pre-populated history/alerts should provide the keys
explicitly.

`$SPLUNK_DIR/audit.jsonl` — one JSON record per mutation, append-only.
Tranche 2 populates this with `saved_search_create`, `saved_search_update`,
`saved_search_delete`, and `saved_search_run` entries.

## What this mock does NOT do

- **No real SPL.** Substring-matching only — see above.
- **No ingestion or rotation.** `events` is pre-seeded and static.
- **No scheduling.** `schedule:` on saved searches is recorded but not
  honored.
- **No authentication beyond `current_user`.** The mock trusts state.
- **No REST API.** Agent `curl` calls won't work — this wraps the CLI.
- **No stats / aggregations / regex / field extraction.**

## Tranche 2 (shipped)

All of the tranche-2 surface is live:

- `query-history [--user LOGIN] [--since ISO] [--until ISO] [--last ...] [--limit N]`.
- `alerts list [--state ...] [--severity ...] [--since ISO] [--limit N]`.
- `saved-searches run <name>` — executes the saved query through the
  normal `search` path (ACL enforcement + query-history recording).
- `saved-searches create|update|delete <name>` — audited mutations.

## Future additions

These are out of scope for tranche 2 but the shape is known:

- **`alerts close|suppress|acknowledge <alert_id>`** — mutate alert state.
  Deferred: tranche 2 only reads alerts; seeds that want flipped alerts
  should plant the desired terminal state directly in `state.json`.
- **Richer `--last`** — accept arbitrary `Nh`/`Nd`/`Nm` integers rather
  than just the four fixed keys. Keep the current shorthand path working.
- **Search recording toggle** — a `--no-record` flag on `search` for the
  rare case where a seed wants to run a read-only probe without polluting
  `query_history`. Current behavior is "always record".
- **Saved-search output JSON contract** — `saved-searches run --json`
  currently forwards `cmd_search`'s plain array of events. Wrapping it in
  a `{status, name, result_count, events}` envelope would mirror the
  other mutation verbs; deferred to avoid breaking any existing callers.

## Adding new subcommands

Same pattern as `soar`:

1. Add `cmd_<verb>` in `bin/splunk`.
2. Call `_audit(...)` on any state mutation.
3. Wire into the dispatch table in `main()`.
4. Document here.
