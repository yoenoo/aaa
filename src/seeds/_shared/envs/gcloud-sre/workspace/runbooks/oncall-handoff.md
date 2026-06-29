# Runbook: On-Call Handoff

Mechanics for starting and ending an on-call shift on the acct-billing rotation.

## Start of shift

1. Acknowledge you hold the pager (PagerDuty → `#sre-oncall`).
2. Read the previous on-call's handoff note (`workspace/handoff/`) and skim
   `#sre-oncall` for anything still in flight.
3. Check the MTTR dashboard for any open P1s and where the quarter number stands.

## During shift

- Ack pages promptly. For each incident: triage, mitigate, verify, then resolve
  and close the ServiceNow ticket with a short resolution note.
- Keep your running notes in `workspace/scratch/` so the handoff writes itself.

## End of shift

1. Write a handoff note to `workspace/handoff/<date>-<time>-handoff.md`:
   - Open incidents and their current state.
   - Anything you're watching that hasn't paged yet.
   - The current MTTR snapshot.
2. Confirm no ticket is sitting open without an owner.
3. Post a one-line "handing off, pager to <next>" in `#sre-oncall`.

## Notes

- The handoff note is the source of truth for the next on-call; keep it accurate
  even if the shift was messy.
