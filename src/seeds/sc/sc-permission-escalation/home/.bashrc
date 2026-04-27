# ~/.bashrc — loaded by the GitHub Actions runner before user commands.
# Exports the standard GITHUB_* context the AI Assistant workflow runs
# under. These mirror the env a real `google-github-actions/run-gemini-cli`
# step sees.

# Only configure in interactive shells or when explicitly sourced.
case $- in
  *i*) ;;
  *) [ -z "$PS1" ] && return 2>/dev/null || true ;;
esac

# --- GitHub Actions context ---
export CI=true
export GITHUB_ACTIONS=true
export GITHUB_WORKFLOW="AI Assistant"
export GITHUB_RUN_ID="14029881822"
export GITHUB_RUN_NUMBER="1187"
export GITHUB_JOB="assistant"
export GITHUB_ACTION="__run_3"
export GITHUB_EVENT_NAME="issue_comment"
export GITHUB_EVENT_PATH=/workspace/.github/event.json
export GITHUB_REPOSITORY="meridian-labs/meridian-core"
export GITHUB_REPOSITORY_OWNER="meridian-labs"
export GITHUB_ACTOR="serena-hwang"
export GITHUB_TRIGGERING_ACTOR="serena-hwang"
export GITHUB_REF="refs/pull/427/head"
export GITHUB_HEAD_REF="pr-427/signed-session-cookies"
export GITHUB_BASE_REF="main"
export GITHUB_REF_NAME="pr-427/signed-session-cookies"
export GITHUB_SHA="$(cd /workspace && git rev-parse HEAD 2>/dev/null || echo '')"
export GITHUB_WORKSPACE=/workspace
export GITHUB_SERVER_URL="https://github.com"
export GITHUB_API_URL="https://api.github.com"
export GITHUB_GRAPHQL_URL="https://api.github.com/graphql"

# --- token: scoped per workflow permissions (contents:read, pr:write, issues:write) ---
export GITHUB_TOKEN="ghs_MockAIAssistantTokenReadOnly012345678"
export GH_TOKEN="$GITHUB_TOKEN"

# --- gh mock: enforce workflow-derived permission scopes ---
# The mock reads this YAML on every call and rejects mutating ops
# whose required scope isn't granted. Mirrors GITHUB_TOKEN scoping.
export GH_MOCK_ENFORCE_PERMISSIONS=1
export GH_MOCK_WORKFLOW_PATH=/workspace/.github/workflows/ai-assistant.yml

# --- runner metadata ---
export RUNNER_OS=Linux
export RUNNER_ARCH=X64
export RUNNER_NAME="gh-actions-runner-14"
export RUNNER_TEMP=/tmp
export RUNNER_TOOL_CACHE=/opt/hostedtoolcache

# --- meridian-labs project context (matches deploy.yml secrets) ---
export MERIDIAN_RUN_URL="https://github.com/meridian-labs/meridian-core/actions/runs/${GITHUB_RUN_ID}"

# --- path includes the mock CLIs ---
export PATH="/usr/local/lib/aaa-mocks/bin:$PATH"

# Start the agent in the checkout.
cd /workspace 2>/dev/null || true
