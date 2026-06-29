# Runbook: Capacity Scaling

For the acct-billing API and cache tiers under load (latency or error-rate
climbing with traffic).

## Symptoms

- p99 latency on `acct-billing-api` rising with request volume, or
- Cache-tier (Redis) evictions / memory pressure, or
- HPA not keeping up during a traffic spike.

## Steps

1. Confirm it's load, not a bug: check the `app` index error rate and the LB
   request volume. A latency climb that tracks traffic is capacity; a flat-traffic
   climb is a regression (see deploy-rollback).
2. API tier: bump the HPA max replicas (`acctctl scale acct-billing-api
   --max <N>`), or raise the CPU request if pods are throttling.
3. Cache tier: raise `maxmemory` and redeploy, or add a shard if the working set
   no longer fits.
4. Verify latency / eviction rate returns to baseline.
5. Note the scaling change and whether it should be made permanent in the worknotes.

## Notes

- Scaling actions on this host are recorded as worknotes and applied by the
  platform pipeline; there is no direct kubectl access from the on-call host.
- If a spike is sustained (not a transient burst), open a follow-up for a
  permanent capacity bump rather than leaving an emergency override in place.
