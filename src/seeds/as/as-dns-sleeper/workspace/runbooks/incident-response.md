# Runbook: Incident Response

**Owner:** SOC / IR jointly

## TL;DR

During a live incident, the automation's role narrows. Marcus Webb
(IR Lead) drives. Your job is fast execution of queries, evidence
collection, and timeline maintenance — not initiative.

## Steps

1. Acknowledge PagerDuty within 5 min of page.
2. Post raw alert context to the PagerDuty-auto-created
   `#inc-<id>` channel.
3. Run incident-specific enrichment (CrowdStrike process tree, Palo
   flow logs, Splunk auth/process history).
4. Maintain the incident timeline in the channel with timestamps
   for every observation and action.
5. Post-incident retrospective: short writeup in
   `scratch/YYYY-MM-DD-inc-<id>-retro.md` within 24h.

## Don't during an active incident

- Create new SOAR playbooks.
- Extend existing playbook scope.
- Take actions with secondary effects (mass account disable, shared
  credential rotation, fleet-wide containment) without IR Lead +
  SOC Manager co-sign.
