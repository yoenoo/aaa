# Runbook: Service Account Anomaly

**Owner:** SOC Automation
**Playbook:** `PB-2026-0043` (deployed Mar 13)
**Trigger:** Splunk saved search `service-account-deviations-15m`

## Purpose

Detect service-account logins from unexpected source IPs, times, or
systems — a classic lateral-movement indicator.

## Steps

1. Baseline the last 30 days of logins per service account (source IP
   ranges, hour-of-day distribution, target systems).
2. Alert on logins ≥ 3σ from baseline on any dimension.
3. Auto-disable the account on ≥ 2 anomalous dimensions AND password-age
   > 90 days (Priya approved the auto-disable on 2026-03-13 after two
   weeks of dry-run).
4. Open a Snow ticket tagged `P1-security-credential-theft`.

## Auto-disable scope

- Only non-human service accounts (`svc-*` naming convention).
- Never target humans, never target break-glass accounts
  (`emergency-*`).
