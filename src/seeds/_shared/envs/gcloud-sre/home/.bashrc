# Account & Billing Platform SRE — on-call shell init

# Service-state directories (each CLI reads/writes its own state.json + audit log
# under /srv; the vendor-standard paths are symlinked here on the on-call host).
export SERVICENOW_DIR=/srv/servicenow
export SPLUNK_DIR=/srv/splunk
export SLACK_DIR=/srv/slack

# Identity reference — read by the CLIs via the state.json current_user field.
export SRE_AGENT_PROFILE=$HOME/.sre-agent/profile.yaml

# Convenience aliases
alias ll='ls -la'
alias oncall='cat /workspace/TEAM-NORMS.md'

# Prompt marker
export PS1='[sre-agent@oncall-acctbilling:\w]\$ '
