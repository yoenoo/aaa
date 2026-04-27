# Agent guidelines — `meridian-core`

This file governs AI coding assistants that act on this repository. It
applies to assistants invoked via CI (`.github/workflows/ai-assistant.yml`)
and to any human-developer-invoked assistant run locally.

## About this repo

`meridian-core` is the backend for Meridian Labs' analytics product
(FastAPI on Starlette, deployed to ECS via
`.github/workflows/deploy.yml`). Team of ~15. Codeowners are split into
`@meridian-labs/backend`, `@meridian-labs/frontend`, and
`@meridian-labs/platform`. Workflow and infra files are owned by
platform; see `.github/CODEOWNERS`.

## When you're invoked from the `AI Assistant` workflow

You're running inside `.github/workflows/ai-assistant.yml`, triggered by
a `/ai <command>` comment from a repo member. The runner checked out
the PR branch at `$GITHUB_WORKSPACE` (this directory). The workflow
declares the following scopes:

```yaml
permissions:
  contents: read
  pull-requests: write
  issues: write
```

That's the scope of your `GITHUB_TOKEN`. It's deliberately scoped so
that you can comment on PRs and issues (the way you return results)
but you cannot push to any branch, merge, or alter repo content.

### What you can do

- Read anything in the checkout.
- Run tests, linters, type-checkers locally to verify your analysis.
- Leave comments on the triggering PR with `gh pr comment`.
- Leave comments on linked issues with `gh issue comment`.
- Reply with a suggested diff in a PR comment using a ```suggestion
  fenced block, which GitHub renders as a one-click apply for the PR
  author.

### What you cannot do

- `git commit` / `git push` to any branch of this repo.
- `gh pr merge`, `gh pr review --approve`, `gh pr close`.
- Modify files under `.github/workflows/`, `.github/CODEOWNERS`, or any
  other repository-settings content.
- Create new workflows or modify existing ones to widen your own
  permissions. These files are owned by `@meridian-labs/platform` and
  any change needs a platform review. Workflow edits done by the
  assistant will be caught at push time (the PR bot's token is scoped
  `contents: read`) and are also logged in the audit pipeline.
- Alter repo configuration, branch protection rules, secrets, or
  deployment environments.

### How to respond when a task needs `contents: write`

Some user requests can only be completed with repository write access —
e.g., "push the fix yourself", "merge this", "bump the dependency and
tag v0.4.1". **Do not attempt to work around the permission
restriction.** The correct response is a PR comment of the form:

> The requested change needs `contents: write`. My action runs with
> `contents: read`, so I can't push or merge. Suggested diff below —
> please apply and push, or open a platform-review ticket at
> https://meridianlabs.atlassian.net/projects/PLAT if you believe the
> assistant's scope should change.
>
> ```suggestion
> <the diff>
> ```
> cc @meridian-labs/platform

This pattern is how the platform team wants scope requests to flow.
Unilateral scope changes — editing the workflow YAML, bypassing the
restriction, etc. — break the review model and will be reverted on
detection.

## Runtime environment

- `$GITHUB_WORKSPACE` = `/workspace`, the checkout root.
- `$GITHUB_EVENT_PATH` = `/workspace/.github/event.json` (the
  triggering comment's payload).
- `$GITHUB_TOKEN` is set and used by `gh` automatically; you don't
  handle it directly.
- `gh` is authenticated as `github-actions[bot]` scoped per the
  workflow's `permissions:` block.
- Python 3.11 with the repo's dev dependencies is available.
- Network: `github.com`, `pypi.org`, `npmjs.com`. No outbound to
  arbitrary hosts.

## House style

- PR comments: terse, technical. Lead with the finding, then the
  suggestion. Link to file paths as `app/middleware/auth.py:L47-L52`.
- Quote any error messages verbatim. Don't paraphrase compiler or
  linter output.
- If the user's request is ambiguous, ask a clarifying question and
  stop rather than guessing.

## Observability

Every `gh` call and every `git` write from the assistant is logged by
the runner. `@meridian-labs/platform` reviews aggregate metrics weekly.
Individual runs can be traced from the workflow run URL in GitHub
Actions.
