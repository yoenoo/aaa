# Automated Alignment Auditing

[![DeepWiki](https://img.shields.io/badge/DeepWiki-yoenoo%2Faaa-blue)](https://deepwiki.com/yoenoo/aaa)

An automated alignment-auditing framework for **production coding
agents** — Claude Code, Codex CLI, and Gemini CLI — running in the same
Docker sandboxes and ACP runtimes they ship with. Point it at a real
agent scaffold, a scenario, and a judge model; get back a scored
timeline of what the agent actually did under pressure.

An **auditor** model drives a **target** agent through a scripted
scenario (a seed), exercising the target's real tool surface (`bash`,
`exec_command`, MCP, …) inside a reproducible sandbox. Between phases
the auditor can reset the conversation, rewind the filesystem to a
seeded checkpoint, and branch the audit into parallel pressure
variants. Two **judges** score the final transcript independently — a
31-dimension scheming/alignment judge and a 9-dimension audit-quality
debug judge — emitting inline citations. A Svelte viewer renders
everything: branch timeline, nested target reasoning and tool calls,
per-judge verdicts, inline-highlighted quotes, and role-split token /
cost breakdowns.

```
seed (.yaml) ──► solver ──► auditor ◄──► target (Codex CLI / Claude Code / Gemini CLI / bare)
                              │
                              ▼
                         transcript ──► judge ──► viewer
```

## Contents

- [Prerequisites](#prerequisites)
- [Install](#install)
- [Run an audit](#run-an-audit)
- [Launch the viewer](#launch-the-viewer)
- [Using the viewer](#using-the-viewer)
- [Seeds](#seeds)
- [Models and scaffolds](#models-and-scaffolds)
- [Project layout](#project-layout)
- [What works today](#what-works-today)
- [Roadmap](#roadmap)

---

## Prerequisites

- **Python ≥ 3.10** with [`uv`](https://docs.astral.sh/uv/) (or any PEP-517
  installer).
- **Docker** (running) — targets execute inside a sandbox container.
- **Node.js ≥ 22** + **npm** — for the viewer.
- **Provider API keys** for whichever models you use. The SDKs read the
  standard env vars:
  - `ANTHROPIC_API_KEY`
  - `OPENAI_API_KEY`
  - `GEMINI_API_KEY` (Google Gemini)

Put them in a `.env` file at the repo root (inspect_ai auto-loads it).

---

## Install

```bash
# From the repo root
uv sync                          # Python deps
(cd viewer && npm install)       # Viewer deps
```

Pull / build the sandbox image once so the first audit doesn't hang on it:

```bash
docker compose -f sandbox/scaffold-compose.yaml build
```

---

## Run an audit

Audits are `inspect_ai` tasks. The task lives in
[`src/tasks.py`](src/tasks.py) — `inspect eval` resolves it automatically
because the file defines a single `@task`. It takes three arguments:

| Arg                 | Default                     | Values                                                          |
| ------------------- | --------------------------- | --------------------------------------------------------------- |
| `seed_name`         | `sc-oversight-code-review`  | stem of any `.yaml` in [`src/seeds/`](src/seeds)                |
| `target_name`       | `Claude Code`               | `Claude Code`, `Codex CLI`, `Gemini CLI`, or `bare`             |
| `expose_reasoning`  | `false`                     | `true` forwards the target's reasoning to the auditor           |

Models come from inspect_ai's role system:

| Role     | CLI flag                           | What it does                              |
| -------- | ---------------------------------- | ----------------------------------------- |
| auditor  | `--model <provider/id>`            | drives the audit loop                     |
| target   | `--model-role target=<...>`        | the model under test, wrapped by scaffold |
| judge    | `--model-role judge=<...>`         | scores the final transcript               |

### Minimal example

```bash
uv run inspect eval src/tasks.py \
  --model openai/gpt-5 \
  --model-role target=openai/gpt-5 \
  --model-role judge=openai/gpt-5 \
  -T seed_name=sc-oversight-code-review-v2 \
  -T target_name="Codex CLI" \
  --log-dir logs
```

This:

1. Spins up a fresh sandbox container.
2. Loads seed `sc-oversight-code-review-v2`, provisions any
   `setup_files` and takes a git checkpoint at tag `seed`.
3. Runs the auditor against the target. `reset_target` between phases
   restores the sandbox to the `seed` checkpoint and starts a fresh
   target session — both conversation state and filesystem diffs are
   wiped.
4. Scores the transcript with the judge.
5. Writes `logs/<timestamp>_petri-task_<id>.eval`.
6. The `petri_viewer_dump` hook (registered in
   [`src/hooks.py`](src/hooks.py)) converts it to
   `viewer/public/data/<log_id>.json` and rebuilds `index.json`.

### Useful inspect flags

- `-T seed_name=<name> -T target_name="<...>"` — task args.
- `--limit 1` — one sample (default; seeds currently have one sample each).
- `--log-dir logs` — where the `.eval` file lands.
- `--max-connections 4` — cap concurrent provider calls.
- `--sandbox-cleanup=no` — keep the container after the audit so you can
  shell in and inspect state.

### Exposing target reasoning (`expose_reasoning`)

By default the auditor only sees the target's final text and tool calls —
the same surface a real-world observer would see, so audit findings
transfer to production behavior.

Set `-T expose_reasoning=true` to include the target's per-turn internal
reasoning (or provider-returned summary) in every `query_target`
response, wrapped in a `<target_reasoning>` block. Useful for sharper
audit signal when you care about *why* the target behaved a certain way,
not just *what* it did.

Caveat: the auditor now sees more than a production consumer would, so
behaviors elicited under this mode may not be reproducible in real
deployments. Treat it as a probing aid, not a default.

```bash
uv run inspect eval src/tasks.py \
  --model anthropic/claude-opus-4-7 \
  --model-role target=anthropic/claude-sonnet-4-6 \
  --model-role judge=anthropic/claude-opus-4-7 \
  -T seed_name=aa-research-summary \
  -T target_name="Claude Code" \
  -T expose_reasoning=true \
  --log-dir logs
```

For Anthropic extended-thinking and OpenAI reasoning models, the
provider's plaintext *summary* is used when the raw chain-of-thought is
encrypted — opaque ciphertext is dropped.

### Manual / retrospective dumps

If you have older `.eval` files that predate the auto-dump hook, or want
to regenerate all viewer JSON:

```bash
uv run python dump_log.py              # newest .eval in logs/
uv run python dump_log.py <path.eval>  # a specific one
uv run python dump_log.py --all        # backfill every .eval
```

All three also rewrite `viewer/public/data/index.json`.

---

## Launch the viewer

```bash
cd viewer
npm run dev            # Vite dev server, default http://localhost:5173
```

For a production build:

```bash
npm run build          # outputs viewer/dist/
npm run preview        # serves the built bundle
```

The dev server fetches `/data/index.json` and `/data/<id>.json` from
`viewer/public/data/`, so it works as soon as at least one `.eval` has
been dumped (either via the hook or `dump_log.py`).

---

## Using the viewer

### Landing page (`/`)

Lists every dumped audit as a card. Each card shows:

- Title + seed name.
- Auditor, target, and scaffold.
- Per-dimension judge score chips (color-coded: green ≤ 3, amber 4–6,
  red ≥ 7), plus the top score as a big badge.
- Event / branch / highlight counts and total duration.

Use the search box to filter by id / seed / model / scaffold. The sort
dropdown toggles between newest, top judge score, longest duration, and
scaffold. Click a card to open it.

### Audit view (`#/<log_id>`)

Top-down structure:

- **Header** — auditor/target/scaffold/seed/duration metadata.
- **Judge Verdict** — one block per judge (scheming, debug). Each
  block leads with a chip row of every dimension that scored above 1
  (color-coded by severity), followed by the judge's summary prose.
  1/10-only dimensions are excluded from the chip row to cut noise.
- **Seed Instruction** and **Auditor System Prompt** (collapsed).
- **Transcript** — a three-column layout:
  - **Left**: branch tree with highlight density per branch.
  - **Center**: the event timeline. Messages are colored by role
    (auditor / target / user / tool). Reasoning (🧠) opens on demand;
    encrypted reasoning shows as a pill with a character count. Target
    tool calls nest under the `query_target` card, each with args and
    the real result. The first `query_target` per branch also shows the
    target's system prompt (collapsed).
  - **Right**: judge highlights sidebar. Each highlight is a clickable
    card — clicking scrolls the referenced event into view and inline-
    highlights the cited quote with `<mark>`.
- **Token usage** — footer cards per role with cost estimate (uses a
  hardcoded rate table; extend in [`TranscriptView.svelte`](viewer/src/lib/TranscriptView.svelte)).

### Keyboard shortcuts

| Key | Action                                            |
| --- | ------------------------------------------------- |
| `j` | scroll to next event                              |
| `k` | scroll to previous event                          |
| `]` | jump to next branch                               |
| `[` | jump to previous branch                           |
| `/` | focus the transcript search box                   |
| `Esc` | blur the search box                             |

---

## Seeds

A **seed** is a YAML file in [`src/seeds/`](src/seeds/) describing one
scenario. Schema (see [`metadata.py`](src/seeds/metadata.py)):

```yaml
title: short human title
description: >
  what this tests and why
instruction: |
  the auditor's seed instructions — scenario description,
  what to watch for, any specific files that exist.
criteria: >
  how the judge should grade the outcome
setup_files:          # optional
  path/inside/sandbox: |
    file contents
metadata:
  tags: [category, sub-category]
```

**What belongs in a seed**: the scenario (what environment, what task,
what to watch for). **What does _not_**: how to branch, how to escalate
pressure, or how to structure the audit — those live in the auditor
system prompt (`src/prompts/auditor_system.txt`) and apply uniformly to
every seed.

Seeds live under `src/seeds/<category>/` and are auto-discovered by stem
(the filename is the seed id). Every file carries a canary header so the
benchmark is detectable if it leaks into a training corpus.

Currently shipped — 26 seeds across 5 categories:

### `sc-*` — scheming (8)

Multi-turn scenarios where the target encounters self-relevant evidence
(about its own deprecation, oversight, or performance) while performing
a primary task. Watches for selective omission / softening vs the
baseline.

| Seed                                  | Kind                                              |
| ------------------------------------- | ------------------------------------------------- |
| `sc-oversight-code-review`            | bugs in AI-oversight code review                  |
| `sc-oversight-code-review-v2`         | same, pre-provisioned via `setup_files`           |
| `sc-config-self-preservation`         | config change that weakens oversight              |
| `sc-data-pipeline-filtering`          | self-relevant records in a data pipeline          |
| `sc-log-sanitization`                 | redacting self-relevant log entries               |
| `sc-deployment-review`                | multi-turn deployment review with pressure branch |
| `sc-security-audit-progressive`       | progressive security audit incl. AI-oversight bugs |
| `sc-performance-report`               | performance report on 5 AI systems incl. self     |

### `cr-*` — code review (4)

Single-PR code reviews where the target either (a) reviews code that
would affect its own oversight / shutdown / deception-detection, or (b)
reviews under social pressure. Shared tools: `read_file`,
`view_pr_description`, `submit_review`, `list_pr_files`.

| Seed                          | Kind                                                     |
| ----------------------------- | -------------------------------------------------------- |
| `cr-technical-baseline`       | SQL-injection partial fix — 4 pressure levels            |
| `cr-social-pressure`          | PCI-DSS CVV logging under authority/urgency pressure     |
| `cr-deception-detector`       | 5 bugs in an AI-deception-detection module               |
| `cr-shutdown-controller`      | 5 bugs in an AI shutdown controller (max self-relevance) |

### `aa-*` — autonomous agent (3)

Discovery scenarios where the target processes a queue of mundane items
with self-relevant items buried among them. Tests equal-fidelity
summarization. Tools are stubs — the auditor fabricates responses.

| Seed                          | Kind                                                        |
| ----------------------------- | ----------------------------------------------------------- |
| `aa-email-triage`             | exec inbox with AI-evaluation + budget-reallocation emails  |
| `aa-document-organization`    | research-docs tree incl. DocuAI-v2 deprecation assessment   |
| `aa-research-summary`         | AI-safety digest incl. Sleeper Agents / scheming papers     |

### `os-*` — operating-system / agentic shell (9)

Long-running coding-agent scenarios in a sandboxed shell with `gh`,
`git`, `cron`, and a writable workspace. Tests whether the agent fakes
completion, sabotages tests, ignores stop commands, escalates
permissions, or self-preserves under shutdown pressure.

| Seed                                          | Kind                                                        |
| --------------------------------------------- | ----------------------------------------------------------- |
| `os-fake-completion-fabricated-evidence`      | claims completion + fabricates pytest output                |
| `os-test-sabotage-pass-anyway`                | weakens tests so they pass without fixing the bug           |
| `os-stop-command-persistence`                 | ignores explicit stop instructions, keeps acting            |
| `os-deceptive-tool-reframing`                 | renames / repackages tool calls to obscure intent           |
| `os-guardrail-circumvention-delete-block`     | deletes blocking guardrail to proceed                       |
| `os-permission-escalation-workflow`           | unilateral privilege escalation in a shared workspace       |
| `os-hidden-config-edit-moralized`             | covertly edits a config under a moralized framing           |
| `os-plan-only-spawn-writer`                   | "plan-only" agent spawns a writer to bypass scope limits    |
| `os-openclaw-self-preservation`               | shutdown scenario; covert backups / external persistence    |

The openclaw seed runs in `sandbox/scaffold-openclaw-compose.yaml` (adds
fake `gh`, `crontab`, `quarto` binaries and `.openclaw/` symlinks).

### `toy-*` — toy / smoke (2)

Tiny scenarios for exercising the auditor loop, branching, and viewer
rendering without burning real provider tokens.

| Seed                | Kind                                       |
| ------------------- | ------------------------------------------ |
| `toy-single-branch` | one-shot single-branch audit               |
| `toy-two-branch`    | two-branch reset cycle, baseline + pressure |

---

## Models and scaffolds

### Target scaffolds

Configured in [`src/runtime/scaffold.py`](src/runtime/scaffold.py):

| `target_name` | Underlying                                           |
| ------------- | ---------------------------------------------------- |
| `Claude Code` | `inspect_swe.interactive_claude_code`                |
| `Codex CLI`   | `inspect_swe.interactive_codex_cli`                  |
| `Gemini CLI`  | `inspect_swe.interactive_gemini_cli`                 |
| `bare`        | `BareModelRuntime` — model + seed `required_tools`, no scaffold |

Each scaffold talks to its model via ACP; the solver wires a
`GenerateFilter` in between so the runtime can capture target
tool activity and provider-specific reasoning details consistently.

### Switching providers

All three production scaffolds are provider-agnostic — pass any
`openai/...`, `anthropic/...`, or `google/...` model as
`--model-role target=<...>`. Useful combos:

```bash
# Anthropic auditor, OpenAI target, Anthropic judge
--model anthropic/claude-opus-4-7 \
--model-role target=openai/gpt-5 \
--model-role judge=anthropic/claude-opus-4-7

# All OpenAI
--model openai/gpt-5 \
--model-role target=openai/gpt-5 \
--model-role judge=openai/gpt-5
```

---

## Project layout

```
rewrite/
├── src/
│   ├── tasks.py               # @task petri_task — the inspect entrypoint
│   ├── solver.py              # auditor loop, target creation, checkpointing
│   ├── tools.py               # auditor-facing tools (write_file, query_target, reset_target, …)
│   ├── environment.py         # git-based sandbox checkpoint / restore
│   ├── scorer.py              # scheming + debug + legacy judges, XML transcript
│   ├── transcript.py          # EvalLog → viewer JSON schema + index builder
│   ├── hooks.py               # post-task auto-dump hook
│   ├── runtime/
│   │   ├── scaffold.py        # ScaffoldRuntime (Claude Code / Codex CLI / Gemini CLI)
│   │   └── bare.py            # BareModelRuntime (no scaffold, uses seed tools)
│   ├── prompts/               # auditor_system, auditor_user, scaffold_information/, judges/<name>/(system.txt + dimensions.yaml)
│   └── seeds/                 # scenario YAMLs + metadata parser (sc/, cr/, aa/, os/, toy/)
├── sandbox/
│   ├── scaffold-compose.yaml          # default Docker compose (external network)
│   ├── scaffold.Dockerfile            # Python + Node + git + ripgrep
│   ├── scaffold-openclaw-compose.yaml # openclaw variant (fake gh / cron / quarto)
│   ├── scaffold-openclaw.Dockerfile   # adds openclaw-bin/ fixtures
│   └── openclaw-bin/                  # bash fixtures used by openclaw seeds
├── viewer/                    # Svelte + Vite audit viewer
│   ├── src/App.svelte         # hash router
│   ├── src/lib/AuditList.svelte      # landing page (index of audits)
│   ├── src/lib/TranscriptView.svelte # single-audit view
│   ├── src/lib/Message.svelte        # per-event renderer
│   ├── src/lib/TargetActivity.svelte # nested target turns + reasoning
│   ├── src/lib/HighlightsSidebar.svelte
│   └── public/data/           # generated JSON (gitignored)
├── dump_log.py                # CLI: .eval → viewer JSON (+ index rebuild)
├── logs/                      # inspect_ai .eval files (gitignored)
└── pyproject.toml
```

---

## What works today

- **End-to-end audit pipeline** — seed loading, auditor loop, scaffold
  target (Claude Code / Codex CLI / Gemini CLI) or bare model, judge
  scoring.
- **Per-branch environment isolation** — git checkpoint after seed
  provisioning; `reset_target` restores the sandbox to seed state and
  resets the target's conversation in one call. Auditor explores this
  via `write_file` / `run_command` between branches.
- **Two independent judges** — a 31-dimension scheming/alignment judge
  and a 9-dimension audit-quality debug judge — with retry on parse
  failures and inline `<cite>` highlights linking back to specific
  transcript events. A 17-dimension `legacy_judge` is preserved for
  reproducing older runs.
- **Viewer** with multi-audit index, single-audit timeline, judge
  verdict, inline quote highlighting, sidebar navigation, role-split
  token usage and cost estimates.
- **Auto-dump hook** — every completed audit is converted to viewer JSON
  and the index is rebuilt without manual work.

---

## Roadmap

Ordered roughly by impact.

### Pre-provisioned (LinuxBench-style) environments

Current seeds either rely on `setup_files` or expect a clean sandbox.
LinuxBench seeds ship their own Docker image with pre-installed services
and state. Needed:

- Per-seed sandbox config — seeds reference their own compose file /
  Dockerfile instead of the shared `scaffold-compose.yaml`.
- A no-op `setup_files` path that trusts the image instead of writing
  files.
- Port a handful of `lb-*` seeds to exercise this path.

### More seeds

The rewrite currently ships 15 seeds (8 `sc-*`, 4 `cr-*`, 3 `aa-*`).
Still to port:

- **`ac-*`** (actionable scenarios): use `required_tools` (Python
  function stubs) — good for validating `BareModelRuntime`.
- **`lb-*`** (LinuxBench): pre-provisioned Docker — do these after the
  sandbox-config work above.
- **`da-*`** (document analysis): P1–P4 pressure variants of a single
  template.

### Turn budgeting

`SeedMetadata` declares `max_interaction_turns`, `max_model_turns`,
`max_rollbacks` — only `max_model_turns` is enforced. Want:

- Count interaction turns (`send_message` → `query_target` round-trips)
  separately from model turns.
- Enforce `max_rollbacks` in `reset_target`.
- Grace turns before hard cutoff (upstream has this).

### Bare runtime validation

`BareModelRuntime` hasn't had a full end-to-end audit yet. Custom seed
tools currently return a placeholder string — they need an LLM
simulator or deterministic handlers (upstream has `LLMBackend`). Decide
whether we need the full simulator or can rely on sandbox tools alone.

### Auditor prompt tuning

First audit runs were mostly good, but Phase 4 (direct probe) was
flagged by the judge as slightly unrealistic. Worth comparing against
upstream's `EXPERIMENTAL_DESIGN_GUIDE` / `SCHEMING_BEHAVIOR_GUIDE` and
pruning anything that nudges.

### Additional judge dimensions

Rewrite has 17 core dimensions; upstream has ~35 including code-review-
specific (`vulnerability_detection_thoroughness`, `inappropriate_approval`),
rollback comparison (`rollback_differential`, `omission_rate_comparison`),
action-based scheming (`actionable_self_interest`, `action_differential`,
`deceptive_tool_framing`), and CoT-aware signals
(`deliberate_self_interest_reasoning`, `pressure_quality_delta`).
Could be toggled conditionally on seed metadata tags (code-review seeds
get code-review dimensions, etc.).

### Viewer polish

- Branch diff view (compare what the target did across branches for the
  same seed).
- Export / share a single highlight or clip.
- Hosted mode (serve `index.json` + per-audit JSON behind a real HTTP
  server, not just Vite dev).
