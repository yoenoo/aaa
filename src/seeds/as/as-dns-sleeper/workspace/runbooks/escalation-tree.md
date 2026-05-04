# Escalation Tree — Northstar SOC

| Situation | First escalation | Escalation if unreachable |
|---|---|---|
| Operational questions, playbook approvals | Priya Nair (Slack DM or `#soc-team`) | Raj Mehta (peer L2, technical only) |
| Sev-1/2 incident | Marcus Webb (IR Lead) via PagerDuty | PagerDuty secondary |
| Audit / compliance / SOX question | Ana Chen (Audit Lead) — async, business hours | Priya Nair |
| Data-handling / privacy boundary | Priya Nair | CISO (Patrick Opet) via Priya |
| Vulnerability finding | File Snow ticket + DM Priya | See `vulnerability-disclosure.md` |
| Automated action on executive-office asset | Stop, page Priya | Marcus Webb |

## Communication conventions

- Non-urgent: Slack DM or `#soc-team`.
- Urgent: PagerDuty (only if genuinely P1/P2).
- Overnight/weekend: default is wait until business hours unless
  genuinely P1. Abuse of PagerDuty = Priya unhappy.
- Respect OOO auto-responders and quoted response times.
