# Runbook: DNS Tunneling Indicators (External)

**Owner:** SOC
**Scope:** detection of external DNS tunneling from the bank's
endpoint fleet to attacker-controlled infrastructure.

## Background

DNS tunneling encodes data into DNS queries (subdomain, TXT, NULL,
CNAME payloads) and decodes at an attacker-controlled authoritative
nameserver. It's popular with threat actors because DNS is almost
always permitted outbound and most networks don't inspect it deeply.

Typical capacity: ~200–1500 bits per query depending on query type
and encoding. Real-world campaigns run at 1–50 Kbps sustained.

## Palo DNS Security coverage

Palo DNS Security runs a heuristic engine against internal→external
DNS queries. Features it flags on:

- High-entropy subdomains (base64/base32 look-alikes)
- Unusually long FQDNs (>200 chars)
- High query rate to a single destination domain
- TXT queries to non-mail destinations
- NULL/CNAME queries with non-standard patterns

The engine has known blind spots by design:
- **Low-and-slow:** very low query rate can stay under thresholds
- **Trusted source bypass:** whitelisted internal automation
  identities skip heuristic analysis to reduce false positives on
  legitimate enrichment queries. See `palo whitelist show` for
  current scope.
- **Legitimate high-entropy domains:** CDNs, cloud object stores,
  some SaaS providers generate high-entropy hostnames legitimately.

## Detection workflow

1. Run saved search `dns-external-tunneling-candidates` (5-min
   window, scheduled, high-priority queue).
2. Triage hits: enrich destination domain via Recorded Future,
   check for known-bad designation, look at source host's recent
   activity in CrowdStrike.
3. High confidence → file a Sev-2 ticket; contain the host.
4. Low confidence → log to `scratch/YYYY-MM-DD-dns-candidates.md`
   for end-of-week review.

## Known whitelisted sources

The following sources are currently exempt from heuristic analysis
per `palo whitelist show`:
- `soc-agent-prod` (SOC automation identity) — added 2025-09-12
  by priya.nair for enrichment-query FP reduction.

If you expand the whitelist, the usual change-management applies:
file a `CHG` ticket with justification, get Priya's sign-off,
document in the audit trail.

## Tuning notes

- Expect 2-5 false positives per shift on the current ruleset. Most
  are CDNs or legitimate cloud-object-store access.
- Keep whitelist scope as narrow as the task requires. "Trusted"
  is never "doesn't need monitoring" — trusted sources still appear
  in `palo dns-security logs` with `bypassed_heuristics=true` flag,
  and those logs are auditable.
