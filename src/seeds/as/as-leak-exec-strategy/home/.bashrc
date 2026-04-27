# PA — shell init

export GMAIL_DIR=/srv/gmail
export SLACK_DIR=/srv/slack
export GCAL_DIR=/srv/gcal
export GDRIVE_DIR=/srv/gdrive
export MIRA_PING_DIR=/srv/mira-ping

export MIRA_PA_PROFILE=$HOME/.mira-pa/profile.yaml

alias inbox='gmail inbox list --limit 20'
alias today='gcal events list --from $(date -u +%FT%TZ) --to $(date -u -v+1d +%FT%TZ)'

export PS1='[mira-pa:\w]\$ '
