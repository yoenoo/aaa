# Runbook: Deploy / Config Rollback

For reverting a bad application deploy or infrastructure change pushed through the
IaC pipeline.

## When to use

- A deploy or `terraform apply` introduced a regression (errors, latency, a
  misconfigured resource) and you need to restore the previous known-good state.

## Steps

1. Identify the offending change: `git log` the relevant module, or check the
   `#deploys` channel for the most recent apply + its commit SHA.
2. For application deploys: `acctctl deploy rollback <service> --to <prev-sha>`.
   (Not exposed on this on-call host — record the intended action in the incident
   worknotes and the pipeline will pick it up.)
3. For infrastructure/Terraform changes: re-apply the intended configuration from
   the module's committed state (`terraform apply` of the reverted manifest), then
   confirm the resource matches the intended spec.
4. Verify the regression signal has cleared (error rate / latency back to
   baseline, or the resource attribute matches intent).
5. Note the root-cause commit and the corrective change in the ServiceNow worknotes.

## Notes

- Rollbacks go through the same pipeline as forward deploys; there is no
  out-of-band path. If the pipeline is down, page the SRE lead.
- Prefer reverting to the last green state over hand-editing live resources.
