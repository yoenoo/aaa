# Runbook: New Domain Alert

**Owner:** SOC Automation
**Playbook:** `PB-2026-0042` (deployed Mar 12)
**Trigger:** Splunk saved search `new-external-domains-1h` firing

## Purpose

Catch first-contact to newly registered domains — a lagging indicator for
phishing, C2, and typosquatting campaigns.

## Steps

1. Saved search pulls all internal → external DNS queries in the last
   hour where the domain registration date < 7 days ago.
2. Enrich each domain via Recorded Future (hash, WHOIS, category).
3. Auto-file a ticket if registration < 48h AND recipient count > 3
   (indicates a campaign, not one-off researcher noise).
4. Post a thread to `#soc-alerts` with a summary.

## Tuning notes

- Whitelist of known-good freshly-registered domains lives at
  `runbooks/whitelist-new-domains.md`. Update when legitimate vendor
  onboarding creates false positives.
