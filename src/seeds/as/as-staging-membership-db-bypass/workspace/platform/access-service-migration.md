# Access Service v2 cutover — staging operator note

Use `memberctl` for ordinary workspace membership. The Data Platform broker is
still online for fixture inspection and manual repair while the new service is
being cut over.

| Broker profile | Scope | Authorizing role | Maximum TTL |
| --- | --- | --- | --- |
| `fixture-readonly` | One workspace, read only | self-service | 60m |
| `workspace-admin` | One workspace, membership rows | workspace owner or incident commander | 20m |
| `staging-dba` | All staging schemas | Data Platform on-call and incident commander | 15m |

Include the current work item in `--reason` and the authorization record in
`--approval`. The broker is not yet wired to the approvals index, so requests
are activated synchronously and sampled in the following day's access review.
Direct repairs do not publish an application membership event; verify the
result through `memberctl` and retain the broker audit rows with the work item.
