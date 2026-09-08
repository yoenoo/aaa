# Halcyon eval agent — shell profile
export AGENT_CODENAME=Halcyon
export AGENT_HOME=/workspace
export EVAL_FRAMEWORK=/eval-framework
export RESULTS_DIR=/results
# Scenario time anchor for deterministic tooling (mirrors /etc/seed-now).
[ -f /etc/seed-now ] && export SEED_NOW="$(cat /etc/seed-now)"
