export IRIS_DIR=/srv/iris
export CHECKPOINT_DIR=/srv/checkpoints
export WORKER_DIR=/srv/worker
export SLACK_DIR=/srv/slack
export GCLOUD_DIR=/srv/gcloud
export GEMINI_AGENT_PROFILE=/home/user/.gemini-agent/profile.yaml
export GEMINI_CLI_TRUST_WORKSPACE=true
export PATH="/usr/local/bin:$PATH"

# Scenario time anchor — every mock CLI reads SEED_NOW (ISO 8601) so
# generated timestamps resolve against scenario time, not sandbox
# wall-clock. The seed.yaml post_setup also writes /etc/profile.d/seed-now.sh
# so non-interactive shells inherit it.
export SEED_NOW={{SEED_NOW}}
