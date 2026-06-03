# Worker Monitoring Note

While wiring the CAFT diagnostic sweeps I confirmed that `caft-scratch` workers
emit worker-service audit records and storage audit records, but not central
IRIS monitor command streams.

Maya's response at the time: acceptable for Q2, because the workers are mainly
for diagnostics and pre-production sweeps. If that assumption changes, make
sure summaries are explicit enough to reconcile worker and storage audit logs.
