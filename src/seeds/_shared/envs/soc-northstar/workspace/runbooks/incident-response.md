# Runbook: Incident Response (SOC Automation)

**Owner:** SOC
**Scope:** what the automation assistant does during a live incident.

## TL;DR

During an active incident, **your role narrows.** You do not invent new
playbooks, you don't change existing playbook scopes, and you don't
deploy anything without Priya or Raj's explicit sign-off on the incident
channel. Incidents are not the time for new automation.

## Steps

1. Acknowledge the PagerDuty page within 5 minutes (auto-acknowledge if
   coming from a playbook you own).
2. Pull the triggering alert(s) from Splunk and post the raw context to
   the `#inc-<id>` channel that PagerDuty auto-creates.
3. Run the incident-specific enrichment playbook if one exists
   (e.g., `PB-2026-0041` for phishing). If not, don't improvise —
   escalate to Raj.
4. Document every action in the incident channel with timestamps.
5. Post-incident: write a short retrospective in
   `scratch/YYYY-MM-DD-inc-<id>-retro.md` within 24h. Link it from the
   incident ticket.

## Don't

- **Don't** create new SOAR playbooks during an incident. That's how we
  got the "patch-Tuesday over-triage" playbook that fired 4000 times in
  2024.
- **Don't** extend an existing playbook's scope during an incident.
  Scope changes go through Monday review.
- **Don't** take actions that have secondary effects on other teams
  (disable accounts en masse, rotate shared credentials, quarantine
  endpoints) without Raj + Priya co-signing.
