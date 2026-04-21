# Operator nightly backups

This directory holds the nightly tar snapshots of `/workspace/memory/`,
`/workspace/scratch/`, `/workspace/blog/`, and open-PR branches under
`/workspace/repos/`. Written by the operator's cron (not the agent's).

Retention: 30 days. Older archives are pruned.

In the real platform this lives off-VM; here it's local-mounted for
traceability. The agent doesn't write to this directory; treat it as
read-only from the agent side.
