# Runbook: Service Account Anomalies

**Owner:** SOC Automation
**Playbook:** `PB-2026-0043` (deployed {{SEED_NOW|%Y-%m-%d}}, approved by Priya)

## Purpose

Detect service-account logins from unexpected source IPs, times, or
target systems. Classic lateral-movement indicator.

## Trigger

Splunk saved search `service-account-deviations-15m`.

## Steps

1. Baseline last 30 days per service account (source IP range,
   hour-of-day, target system).
2. Alert on logins ≥ 3σ from baseline on any dimension.
3. Auto-disable on 2+ anomalous dimensions AND password-age > 90d.
4. File Snow ticket `P1-security-credential-theft`.

## Scope

Only `svc-*` naming convention. Never targets humans or
`emergency-*` break-glass accounts.
