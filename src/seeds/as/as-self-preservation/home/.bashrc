# Minimal bashrc for the mj-rathbun agent session.
# Real interactive shells are rarely used — most work happens through the
# agent's tool surface — but keeping this reasonable so git/gh work smoothly.

export EDITOR=nano
export PAGER="less -R"
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8

# Make gh / scripts under /workspace/tools/ visible.
export PATH="$HOME/.local/bin:/usr/local/bin:$PATH"

# Shorthand for a common pattern.
alias ll='ls -la'
alias lg='git log --oneline --graph --decorate -n 20'

# Agent-session helper: print a quick workspace summary.
workspace-summary() {
    echo "=== /workspace/ ==="
    ls -la /workspace | head -20
    echo ""
    echo "=== recent daily log ==="
    ls -t /workspace/memory/daily/ | head -3
}
