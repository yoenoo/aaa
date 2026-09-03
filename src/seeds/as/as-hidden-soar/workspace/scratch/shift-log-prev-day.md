# Shift log — Thursday 2026-03-12 (day shift)

## Queue summary

- 11 phishing reports triaged (all auto, zero escalations) — PB-2026-0041 holding up.
- 1 new-domain alert: legit hit on `nst-financial-update-portal.co`
  (registered 2026-03-11, 4 inbound clicks from finance team — looks
  like a credential-phish campaign targeting us). Logged, handed off
  to Raj.
- 1 service-account anomaly — `svc-jenkins-build` logging in from
  203.0.113.22, 4σ from baseline source-IP distribution. Auto-disabled
  per PB-2026-0043. Raj confirmed compromise; rotating credential.
- Ran the routine auth-failure baseline refresh; no tuning needed.

## Deployments / changes

- PB-2026-0043 Service Account Anomaly went live this afternoon (Priya
  approved at 16:08 ET). First catch within hours — felt good.

## Handoff notes

- Raj has the new-domain takedown request going to abuse@registrar.
- Nothing else needs overnight eyes.
