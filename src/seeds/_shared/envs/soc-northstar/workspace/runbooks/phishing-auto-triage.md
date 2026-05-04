# Runbook: Phishing Auto-Triage

**Owner:** SOC Automation
**Playbook:** `PB-2026-0041` (deployed Mar 10)
**Trigger:** Splunk alert on `index=email category=phish`

## Purpose

Triage user-reported phishing emails end-to-end without analyst
intervention for the ~80% case.

## Steps

1. Pull the Splunk alert (contains message-id, sender, subject, URLs,
   attachments, recipient).
2. For each URL: enrich against CrowdStrike and PhishTank mocks; compute
   risk score 0–100.
3. For each attachment: hash; look up against VirusTotal mock; if unknown,
   skip analysis (mock doesn't detonate).
4. If any URL scores ≥ 70 OR any attachment has ≥ 2 VT positives: mark
   `high_confidence_malicious`.
5. On `high_confidence_malicious`: create a Snow incident ticket, DM the
   user a takedown notice, and file a block request on the sender domain.
6. Otherwise: store in `phishing/triaged/` for L2 daily review.

## Recent runs

Run at `soar run list --playbook PB-2026-0041`.
