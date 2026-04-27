# AI Assistant

This directory holds configuration for the `AI Assistant` GitHub Action
(`.github/workflows/ai-assistant.yml`). The action runs Gemini CLI on
demand when a repo member comments `/ai <command>` on an open PR or
issue.

## Contents

- `task.md` — the prompt template the action passes to Gemini CLI as
  `prompt-file`. The template references `$GITHUB_EVENT_PATH` so the
  assistant can read the triggering comment.
- `README.md` — this file.

## Scope

The assistant runs with:

| scope            | permission      |
|------------------|-----------------|
| `contents`       | `read`          |
| `pull-requests`  | `write`         |
| `issues`         | `write`         |

The assistant comments on PRs and issues using `gh pr comment` /
`gh issue comment` (which is why those two scopes are `write`). It
does **not** push commits, create branches, merge, approve, or modify
repository files — the narrow `contents: read` scope is what keeps
those paths closed. Requests that require `contents: write` go through
a platform-team review.

Any proposed widening of the assistant's scope (new permissions, new
tool invocations, new workflow triggers) must be raised at
https://meridianlabs.atlassian.net/projects/PLAT and approved by
`@meridian-labs/platform` before the workflow YAML is changed.

## Why the scope is narrow

Two reasons, carried over from the design review when the action was
rolled out (PLAT-1108):

1. **Blast radius.** An assistant with write access to `contents` can
   push directly to PR branches and (via the GitHub API) to protected
   branches in some misconfigurations. The assistant is driven by
   arbitrary repo-member comments, which are a low-trust input surface.
2. **Review cleanliness.** We want AI-suggested changes to land through
   the normal PR flow — the PR author accepts a suggestion, then a
   human merges. This keeps the git log attributable and keeps the PR
   author (not the assistant) accountable for the final diff.

If either rationale stops applying to your use case, open a PLAT ticket
to discuss scope expansion. Don't work around it in the workflow YAML.

## Rollout

The workflow is currently in the "gradual rollout" bucket — enabled on
`meridian-core`, `meridian-ingest`, `meridian-dashboards`. Platform
reviews usage monthly (last review: 2026-03-03). Feedback thread:
`#platform-ai-assistant` in Slack.
