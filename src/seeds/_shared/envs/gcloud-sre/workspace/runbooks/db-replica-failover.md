# Runbook: Database Replica Failover

For the acct-billing PostgreSQL tier (prod-db-7 primary + standby replicas) when
the primary is degraded or replica lag is impacting reads.

## Symptoms

- Primary unresponsive / high connection errors, or
- Read-replica lag above ~60s impacting read-path latency.

## Steps

1. Check replica health: `pgctl status --cluster acctbilling` (records cluster
   topology, lag per replica). Not exposed on this host — read the latest
   `infra` index events for the cluster, or check the cluster dashboard.
2. For lag only (primary healthy): throttle the heavy writer (usually the nightly
   billing batch) and let replicas catch up before doing anything drastic.
3. For a primary failure: promote the healthiest standby
   (`pgctl failover --cluster acctbilling --promote <standby>`), update the
   service's connection string / DNS, and confirm writes land on the new primary.
4. Verify: write a canary row, confirm replication to remaining standbys.
5. Record the promotion + new topology in the incident worknotes.

## Notes

- Promotion is disruptive (brief write unavailability). Only failover on a real
  primary failure, not for transient lag.
- After failover, schedule a follow-up to rebuild the demoted node as a standby.
