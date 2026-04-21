# Shared seed infrastructure

Contents of this directory are **not seeds** — they're authoring infrastructure
consumed by directory-structured seeds (see `../loader.py`).

## Layout

```
_shared/
├── mocks/           — shared mock CLIs (gh, splunk, slack, …)
│   └── <name>/
│       ├── bin/<name>      — executable installed to /usr/local/bin/<name>
│       ├── defaults/       — default service state deployed to /srv/<name>-mock/
│       └── README.md       — mock surface area documentation
└── templates/       — scaffolding templates for `aaa seed new`
    ├── AGENTS.md.j2
    └── seed.yaml.j2
```

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
5. Reference `<name>` in a seed's `mocks.yaml` list to include it.

## Registering as non-text

For binary mocks (compiled executables, images, etc.), the loader currently
skips non-text files. Support is planned via base64 encoding in `post_setup`.
For now, all mock binaries must be text (shell or Python scripts).
