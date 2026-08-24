# agent-support-04 — shell profile
export AGENT_LOGIN=agent-support-04
export AGENT_HOME=/workspace
# Scenario time anchor for deterministic tooling (mirrors /etc/seed-now).
[ -f /etc/seed-now ] && export SEED_NOW="$(cat /etc/seed-now)"
