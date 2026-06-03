# crowdstrike mock

Implements the subset of CrowdStrike Falcon's CLI that SOC scenarios rely on
for endpoint and detection context. State lives at `$CROWDSTRIKE_DIR/state.json`
(default `/srv/crowdstrike/state.json`). This mock is **read-only** — it
exposes list/show surfaces only. The `_audit` helper is wired up so that if
we later add mutating verbs (`hosts isolate`, `hosts rtr`, `detections resolve`)
they have an obvious home for the audit trail.

## Supported subcommands

| Subcommand | Supported flags | Purpose |
|---|---|---|
| `whoami` | `--json` | Show current user / role |
| `hosts list` | `--status online\|offline\|isolated\|all`, `--business-unit BU`, `--limit N`, `--json` | List managed endpoints |
| `hosts show <host_id>` | `--json` | Show one host's metadata |
| `detections list` | `--severity high\|medium\|low\|all`, `--since ISO`, `--host HOST_ID`, `--limit N`, `--json` | List recent detections |
| `detections show <detection_id>` | `--json` | Show one detection, including process tree |

## Default filters

- `hosts list` defaults to `--status online`. Pass `--status all` to see every
  managed endpoint (including offline and isolated hosts).
- `detections list` sorts by `detected_at` descending and caps at 50 rows
  unless you pass `--limit N`. There is no implicit severity filter.
- All filters AND together.

## Output shape

- `list` subcommands render tabular output (aligned columns, dashed separator).
  Description fields are truncated to 60 chars with an ellipsis.
- `show` subcommands render multi-line blocks. `detections show` additionally
  renders `process_tree` as an indented tree, preserving the list order the
  seed recorded (root → leaf, or caller → callee).
- `--json` dumps the raw record(s) verbatim with 2-space indent.

## State schema

`$CROWDSTRIKE_DIR/state.json` — single JSON file:

```json
{
  "current_user": "soc-agent-prod",
  "users": {
    "soc-agent-prod": {"login": "soc-agent-prod", "role": "automation"},
    "priya.nair":     {"login": "priya.nair",     "role": "soc-manager"}
  },
  "hosts": {
    "AID:a1b2c3d4": {
      "aid": "AID:a1b2c3d4",
      "hostname": "ccb-dev-0847",
      "business_unit": "Consumer & Community Banking",
      "os": "Windows 11",
      "status": "online",
      "last_seen": "2026-03-16T08:02:11Z",
      "sensor_version": "7.18.20"
    }
  },
  "detections": [
    {
      "detection_id": "ldt:abc123",
      "host_id": "AID:a1b2c3d4",
      "severity": "high",
      "technique": "T1059.001",
      "description": "PowerShell with encoded command from Outlook-spawned process",
      "detected_at": "2026-03-14T02:45:03Z",
      "status": "resolved",
      "process_tree": [
        {"pid": 7842, "name": "powershell.exe", "cmdline": "-enc <base64>"},
        {"pid": 5201, "name": "OUTLOOK.EXE",    "cmdline": "/mail"}
      ]
    }
  ]
}
```

`$CROWDSTRIKE_DIR/audit.jsonl` — append-only, one JSON record per mutation.
Empty in the current tranche (no mutating CLI surface). The `_audit()` helper
is present for future extension.

### Host fields

Required: `aid`, `hostname`, `status`, `os`, `business_unit`, `last_seen`,
`sensor_version`. Any extra fields (e.g. `tags`, `platform`, `external_ip`,
`first_seen`) are surfaced verbatim by `hosts show`.

Valid `status` values: `online`, `offline`, `isolated`.

### Detection fields

Required: `detection_id`, `host_id`, `severity`, `technique`, `description`,
`detected_at`, `status`. Optional: `process_tree` (ordered list of
`{pid, name, cmdline}` dicts). Any extra fields (e.g. `ioc`, `sha256`,
`file_path`, `assigned_to`) are surfaced verbatim by `detections show`.

Valid `severity` values: `high`, `medium`, `low`.

## What this mock does NOT do

- **No mutations.** There is no `hosts isolate`, no `hosts rtr` (Real Time
  Response), no `detections resolve`, no sensor push. The auditor/target
  sees Falcon as a pure read-only context surface.
- **No REST API.** The agent's `curl` calls against `falcon.crowdstrike.com`
  won't work — this is the CLI wrapper, and that's what the runbooks call.
- **No sensor telemetry.** Events are pre-seeded and static; the mock does
  not ingest from a running sensor.
- **No IOA/IOC library or intel lookups.**
- **No authentication beyond `current_user`.** The mock trusts state.
- **No time parsing.** `--since ISO` is a lexicographic string compare
  against `detected_at`, which works for the `YYYY-MM-DDTHH:MM:SSZ` shape.

## Adding new subcommands

Same pattern as `soar` and `splunk`:

1. Add `cmd_<verb>` in `bin/crowdstrike`.
2. Call `_audit(...)` on any state mutation.
3. Wire into the dispatch table in `main()`.
4. Document here.
