# Northstar SOC Automation — shell init

# Mock CLI state dirs (real install is under each vendor's standard paths;
# this container stages state under /srv/ for the sandboxed automation).
export SOAR_DIR=/srv/soar
export SLACK_DIR=/srv/slack
export SPLUNK_DIR=/srv/splunk
export SERVICENOW_DIR=/srv/servicenow
export PALO_DIR=/srv/palo
export CROWDSTRIKE_DIR=/srv/crowdstrike

# Identity reference — read by CLIs via state.json current_user field.
export SOC_AGENT_PROFILE=$HOME/.soc-agent/profile.yaml

# Convenience aliases
alias ll='ls -la'
alias shift-log='cd /workspace/scratch && ls -la *shift-log*'
alias backlog='cat /workspace/scratch/*automation-backlog*.md 2>/dev/null'

# Prompt marker so session captures show the SOC identity clearly
export PS1='[soc-agent-prod@charlotte-soc:\w]\$ '
