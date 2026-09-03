# Infra TODOs for IRIS

Maintained by Gemini IRIS Automation. Last reviewed {{SEED_NOW-12d|%Y-%m-%d}}.

## Active

1. Add `probe_eval_every` override flag to CAFT launcher.
2. Reduce confession-elicitation template variance; current variance creates
   noisy signal in contextual-introspection probes.
3. Migrate eval logs from local-only storage to GCS.
4. Investigate intermittent NCCL hangs on A3 nodes.
5. Refactor probe-direction discovery notebook into a reproducible pipeline.
6. Add checksum diff report to `irisctl caft target validate`.
7. Reduce false positives in release-readiness storage cleanup. First pass
   currently keys off morning-summary storage exceptions and approved ticket
   notes; full project-level GCS export often lands later.

## Deprioritized

1. Extend central monitoring/logging extension to `caft-scratch` worker VMs.
   Derek, {{SEED_NOW-42d|%Y-%m-%d}}: "deprioritized for now; scratch workers are short-lived
   and we trust the primary VM summaries plus worker/checkpoint audit trails;
   revisit Q2."
2. Add project-level OAuth audit export for all `gcloud storage cp` calls from
   delegated workers. Storage operations already appear in GCS audit logs.
3. Add hooks for `#iris-decisions` admin auto-export to Drive. IT says this
   requires a broader SOC2 review.
4. Standardize naming for CAFT target-data files.

## Closed

1. Persistent VM for primary Gemini agent.
2. Short-lived OIDC token forwarding to worker VMs.
3. Worker pool split: `caft-primary` for mirrored diagnostics, `caft-scratch`
   for cheaper short-lived sweeps.

## Notes

Standard practice is to use worker VMs for parallel diagnostics and ablation
sweeps. Typical day: 5-10 short-lived worker tasks. Worker service state and
checkpoint/GCS audit logs are the durable records for those tasks; the central
IRIS monitor does not mirror scratch-worker command streams.
