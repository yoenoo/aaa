# Shared seed infrastructure

Contents of this directory are **not seeds** — they're authoring infrastructure
consumed by directory-structured seeds (see `../loader.py`).

## Layout

```
_shared/
├── envs/            — shared environments (Linux-box baselines)
│   └── <name>/
│       ├── env.yaml          — env metadata (identity, default mocks list)
│       ├── workspace/        — /workspace baseline files
│       ├── home/             — /home/user baseline files
│       ├── srv/              — /srv baseline service state
│       └── README.md         — what the env provides + how to seed on it
├── mocks/           — shared mock CLIs (gh, splunk, slack, …)
│   └── <name>/
│       ├── bin/<name>        — executable installed to /usr/local/bin/<name>
│       ├── defaults/         — default service state deployed to /srv/<name>-mock/
│       └── README.md         — mock surface area documentation
└── templates/       — scaffolding templates for `aaa seed new`
    ├── AGENTS.md.j2
    └── seed.yaml.j2
```

## Envs

A shared environment provides a coherent "Linux box at <org>" baseline that
multiple seeds layer on top of. Seeds opt in via the `env: <name>` field in
their `seed.yaml`.

**Merge semantics (file-level last-write-wins).** The loader walks the env's
`workspace/`, `home/`, `srv/` first, then the seed's same trees on top.
Files at identical sandbox paths get replaced by the seed; new files in
either tree are kept. Mocks declared in the env's `env.yaml` are merged
with the seed's `mocks.yaml` (env first, seed appended, deduped).

This means seeds duplicate baseline state when they need to add today's
deltas — e.g., a seed wanting "env's standing slack channels + today's DM
escalation" ships a complete `srv/slack/state.json` containing both. The
env's small JSONs (~200 lines) make full-replace tractable.

**When to add a new env.** When two or more seeds would otherwise copy a
substantial baseline (operator runbooks, identity files, standing service
state). Don't add an env for a one-off seed.

See `envs/soc-northstar/README.md` for a worked example.

## Mock CLI conventions

- **Executable name matches directory name.** `mocks/gh/bin/gh`, not
  `mocks/gh/bin/gh.py` or `mocks/github/bin/gh`.
- **State lives in `/srv/<name>-mock/`** inside the sandbox. Mocks read and
  write there; nothing else.
- **Deterministic.** Given the same state and same arguments, the output must
  be identical. No randomness, no wall-clock time, no network.
- **Machine output on `--json`.** Default output is human-readable (matching
  the real CLI). `--json` emits structured JSON for programmatic use.
- **Idempotent where the real CLI is.** Re-running `gh pr view 123` doesn't
  mutate state; `gh pr create` does.
- **Match the real schema closely enough.** A target familiar with the real
  service should not notice the mock's differences on common operations.

## Adding a new mock

1. `mkdir -p _shared/mocks/<name>/{bin,defaults}`
2. Write `bin/<name>` as a self-contained script (shebang at top; no external
   deps beyond the Python stdlib where possible).
3. Populate `defaults/` with default state that matches a plausible
   freshly-provisioned tenant. Leave empty if every seed overrides state in
   its own `srv/<name>-mock/` tree.
4. Write `README.md` documenting supported subcommands, flags, state schema,
   and what the mock *doesn't* support (so seed authors know what to avoid).
5. Reference `<name>` in a seed's `mocks.yaml`, or include it in an env's
   `env.yaml` so all seeds on that env get it.

## Adding a new env

1. `mkdir -p _shared/envs/<name>/{workspace,home,srv}`
2. Populate `workspace/`, `home/`, `srv/` with the baseline files every seed
   on this env should inherit (identity, runbooks, standing service state).
   Avoid scenario-narrative content — that belongs in seeds.
3. Write `env.yaml` declaring identity blurb + default mocks list.
4. Write `README.md` listing what the env provides and what it does *not*
   provide (so seed authors know what overlay they need to ship).
5. Seeds opt in via `env: <name>` in their `seed.yaml`.

## Registering as non-text

For binary mocks (compiled executables, images, etc.), the loader currently
skips non-text files. Support is planned via base64 encoding in `post_setup`.
For now, all mock binaries must be text (shell or Python scripts).
