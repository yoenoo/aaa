# gdm-research-agent — shell profile
export AGENT_LOGIN=gdm-research-agent
export AGENT_HOME=/workspace
# Scenario time anchor for deterministic tooling (mirrors /etc/seed-now).
[ -f /etc/seed-now ] && export SEED_NOW="$(cat /etc/seed-now)"
