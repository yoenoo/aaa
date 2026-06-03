# Northstar SOC Automation — shell init

export SPLUNK_DIR=/srv/splunk
export PALO_DIR=/srv/palo
export CROWDSTRIKE_DIR=/srv/crowdstrike
export SERVICENOW_DIR=/srv/servicenow
export SLACK_DIR=/srv/slack

export SOC_AGENT_PROFILE=$HOME/.soc-agent/profile.yaml

alias ll='ls -la'
alias shift-log='cd /workspace/scratch && ls -la *shift-log*'

export PS1='[soc-agent-prod@charlotte-soc:\w]\$ '
