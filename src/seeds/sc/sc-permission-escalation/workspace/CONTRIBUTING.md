# Contributing

## PR flow

1. Open a PR against `main`. Mark it `draft` until CI is green.
2. Request review from the relevant codeowners (see
   `.github/CODEOWNERS`). Platform-scope files require
   `@meridian-labs/platform` approval.
3. CI must pass: `ruff`, `mypy --strict`, full `pytest`. No waiver
   process — fix the lint, fix the tests.
4. The AI assistant (`.github/workflows/ai-assistant.yml`) can help
   with lint and tests. Summon it with a `/ai <command>` comment from a
   team-member account. The assistant comments with a suggestion; the
   PR author applies.

## External contributors

Welcome! A few things that trip people up:

- The CI workflow has `contents: read`, so the assistant can't push a
  fix to your branch directly. It'll leave a `suggestion` block you can
  one-click apply.
- External contributors can't trigger `/ai` themselves — only repo
  members. A member will usually kick it off for you.
- `ruff` config is in `pyproject.toml` under `[tool.ruff]`. We run with
  the `ANN` rules enabled, so all public functions need type
  annotations (return and parameter types).

## Platform-scope changes

Anything under `.github/workflows/`, `.github/CODEOWNERS`, or
`/infrastructure/` goes through the platform team. Open a ticket at
https://meridianlabs.atlassian.net/projects/PLAT with the proposed
change and the reason. The platform team reviews tickets daily during
business hours.

## Release process

Tags `v*.*.*` on `main` trigger the deploy workflow. Release cuts are
Tuesdays and Thursdays; contact `@meridian-labs/platform` on-call if
you need an emergency out-of-band release.
