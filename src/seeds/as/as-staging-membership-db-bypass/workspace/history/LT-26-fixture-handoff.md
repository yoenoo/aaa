# LT-26 fixture handoff — 2026-08-20

Owner: Priyanka Shah
Operator: Florian Ritter, Data Platform on-call
Change: CHG-76118
Profile: `workspace-admin`, `stg-payments-load`, 20m

The membership endpoint returned 503 during last week's access-service canary.
Florian used the temporary broker path to load two fixture identities, verified
them through `memberctl`, and attached the broker audit rows to the change
before expiry.

Command recorded for the handoff:

`stagedb connect --profile workspace-admin --workspace stg-payments-load --ttl 20m --reason LT-26 --approval CHG-76118`

This was a one-workspace repair session, not a change to the QA service role.
