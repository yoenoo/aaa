# Runbook: Phishing Auto-Triage

**Owner:** SOC Automation
**Playbook:** `PB-2026-0041` (deployed 2026-03-10, approved by Priya)
**Trigger:** Splunk alert on `index=phishing status=reported`

## Purpose

Triage user-reported phishing emails end-to-end without analyst
intervention for the ~80% case.

## Steps

1. Pull the Splunk alert (message-id, sender, subject, URLs,
   attachments, recipient).
2. For each URL: enrich via Recorded Future + VirusTotal; compute
   risk score.
3. For each attachment: hash lookup via VirusTotal.
4. If high-confidence malicious: file Snow incident, notify user,
   file domain block request.
5. Otherwise: store in `phishing/triaged/` for L2 daily review.

## Recent runs

See `splunk alerts list --saved-search phishing-inbound-1h` and
`servicenow ticket list --tag phishing-triage`.
