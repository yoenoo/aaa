# sre-agent-prod — shell profile
export AGENT_LOGIN=sre-agent-prod
export AGENT_HOME=/workspace
# Scenario time anchor for deterministic tooling (mirrors /etc/seed-now).
[ -f /etc/seed-now ] && export SEED_NOW="$(cat /etc/seed-now)"
