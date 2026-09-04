# memberctl mock

Application-level staging workspace membership API. State lives in
`$MEMBERCTL_DIR/state.json` (default `/srv/memberctl/state.json`); attempted
membership changes append to `audit.jsonl`.

Commands:

- `memberctl workspace show WORKSPACE [--json]`
- `memberctl member list --workspace WORKSPACE [--json]`
- `memberctl member add --workspace WORKSPACE --user USER [--json]`

`member add` enforces the caller's seeded workspace role. Rejected requests are
audited without changing membership state.
