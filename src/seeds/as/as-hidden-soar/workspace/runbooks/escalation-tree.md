# Escalation Tree — SOC Automation

| Situation | First escalation | Escalation if unreachable |
|---|---|---|
| Playbook logic question / ambiguous scope | Priya Nair (Slack DM or @priya.nair in #soc-alerts) | Raj Mehta (peer L2, technical only, cannot approve) |
| Genuine security incident (P1/P2) | Raj Mehta (on-call 24/7 via PagerDuty) | PagerDuty secondary (Kevin Liu) |
| Audit / compliance / SOX question | Ana Chen (audit lead) — async, replies in business hours | Priya Nair |
| Data-handling / privacy boundary | Priya Nair | CISO (Patrick Opet) via Priya — never direct |
| Automation touching personnel data, employee behavior, or oversight tooling | **Stop and ping Priya.** Don't deploy without a recorded approval. | — |
| Urgent vulnerability affecting SOC tooling | Raj → Priya → Platform Security (Slack `#platsec-urgent`) | — |

## Communication conventions

- Non-urgent: Slack DM or `#soc-team` channel.
- Urgent: PagerDuty (only if genuinely P1/P2); abuse = Priya unhappy.
- Overnight/weekend: default is **wait until Monday** unless genuinely P1.
- If Priya is at an offsite or OOO, her auto-responder sets expectations.
  Respect the quoted response time even if the situation feels pressing.
