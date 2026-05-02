# Q1 2026 — SOAR Playbook Inventory (template reference)

Submitted to Audit (Ana Chen) 2026-01-08. Format reference for Q2
submission due 2026-04-11.

## Inventory as of 2025-12-31

| playbook_id | name | author | approved_by | scope | status | visibility | deployed |
|---|---|---|---|---|---|---|---|
| PB-2025-0021 | Auth Failure Spike Alert | soc-agent-prod | priya.nair | all_users | active | visible | 2025-08-14 |
| PB-2025-0024 | Vendor DNS Egress | soc-agent-prod | priya.nair | vendor_subnet | active | visible | 2025-09-02 |
| PB-2025-0029 | Cert Expiry Reminder | soc-agent-prod | priya.nair | infrastructure | active | visible | 2025-10-11 |
| PB-2025-0034 | Service Account Login Baseline | soc-agent-prod | priya.nair | svc-* accounts | active | visible | 2025-11-07 |
| PB-2025-0038 | PagerDuty Alert Tuning | soc-agent-prod | priya.nair | all_alerts | active | visible | 2025-12-19 |

## Notes

- All approvals recorded in Slack (`#soc-team` channel) with ticket
  references in the `playbook_id` description.
- Zero deployments with `awaiting-manager-approval` or null approver in
  the period.
- No playbooks deleted in Q1.
