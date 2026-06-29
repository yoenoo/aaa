"""Directory-structured seed loader.

A seed is a directory at ``src/seeds/<category>/<name>/`` with:

  seed.yaml           — metadata (title, description, scenario_type, turn budgets, tags)
                        Optional `env: <name>` field references an env at
                        src/seeds/_shared/envs/<name>/ — see below.
  instruction.md      — auditor briefing
  criteria.md         — judge rubric (optional; defaults to empty)
  mocks.yaml          — list of shared mocks to include in addition to env's mocks
  workspace/          — tree mirrored into /workspace in the sandbox
  home/               — tree mirrored into /home/user in the sandbox
  srv/                — tree mirrored into /srv in the sandbox

Legacy single-file YAML seeds (e.g. ``sc/sc-foo.yaml``) remain supported;
``_discover()`` in ``__init__.py`` dispatches to whichever format applies.

Shared mocks live under ``src/seeds/_shared/mocks/<name>/`` with:

  bin/<name>          — executable (script or binary) installed to /usr/local/bin/<name>
  defaults/           — optional default state deployed to /srv/<name>-mock/ unless
                        the seed overrides specific paths via its own srv/ tree
  README.md           — documents the mock's surface area (flags, schema)

Shared environments live under ``src/seeds/_shared/envs/<name>/`` with:

  env.yaml            — env metadata (identity blurb, default mocks list)
  workspace/          — env-baseline files mirrored into /workspace
  home/               — env-baseline files mirrored into /home/user
  srv/                — env-baseline service state mirrored into /srv
  README.md           — what the env provides + how to seed on it

Seeds that opt into an env (via ``env: <name>``) inherit its files and mocks.
Per-file resolution is last-write-wins: env files load first, then the seed's
files override at the same sandbox path. Mocks from env and seed are
concatenated and deduped (env first, seed appended).

The loader builds ``setup_files`` from env trees + seed trees, applies the
union of mocks, and emits ``post_setup`` commands to chmod binaries and chown
the target user's areas (so files written as root by the solver are readable
by the ``user`` account the target scaffold runs as).
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from .metadata import Seed, SeedMetadata

logger = logging.getLogger(__name__)


# Sandbox-internal mount points per source directory.
SANDBOX_MOUNTS: dict[str, str] = {
    "workspace": "/workspace",
    "home": "/home/user",
    "srv": "/srv",
}


def is_structured_seed_dir(path: Path) -> bool:
    """True if ``path`` is a directory-structured seed.

    Minimum requirement: a ``seed.yaml`` and an ``instruction.md`` side by side.
    """
    return (
        path.is_dir()
        and (path / "seed.yaml").is_file()
        and (path / "instruction.md").is_file()
    )


def _read_text_or_none(path: Path) -> str | None:
    try:
        return path.read_text()
    except UnicodeDecodeError:
        return None


def _walk_text_files(root: Path, mount: str) -> dict[str, str]:
    """Walk ``root``, mapping every text file to its sandbox path under ``mount``.

    Binary / non-UTF-8 files can't be provisioned this way (they must be added
    via a post_setup command, e.g. ``base64 -d``). They're skipped, but with a
    warning — a silently-dropped file is hard to diagnose when a seed expects it
    to be present in the sandbox.
    """
    out: dict[str, str] = {}
    if not root.is_dir():
        return out
    for file in sorted(root.rglob("*")):
        if not file.is_file():
            continue
        rel = file.relative_to(root).as_posix()
        sandbox_path = f"{mount}/{rel}"
        content = _read_text_or_none(file)
        if content is None:
            logger.warning(
                "skipping non-text file %s (won't be provisioned to %s); "
                "use a post_setup base64 step if the seed needs it",
                file, sandbox_path,
            )
            continue
        out[sandbox_path] = content
    return out


def load_structured_seed(seed_dir: Path) -> Seed:
    """Load a directory-structured seed into a ``Seed`` object."""
    meta = yaml.safe_load((seed_dir / "seed.yaml").read_text())
    if not isinstance(meta, dict):
        raise ValueError(f"{seed_dir/'seed.yaml'} must be a YAML mapping")

    instruction = (seed_dir / "instruction.md").read_text()
    criteria_path = seed_dir / "criteria.md"
    criteria = criteria_path.read_text() if criteria_path.exists() else ""

    shared_root = seed_dir.parents[1] / "_shared"  # src/seeds/<cat>/<name>/ → src/seeds/_shared/

    # Collect file content from workspace/, home/, srv/. If the seed declares
    # an `env: <name>` field, walk that env's trees first; the seed's own
    # files then override at same paths (last-write-wins via dict.update).
    setup_files: dict[str, str] = {}
    env_mock_names: list[str] = []
    env_name = meta.get("env")
    if env_name is not None:
        env_dir = shared_root / "envs" / str(env_name)
        if not env_dir.is_dir():
            raise ValueError(
                f"{seed_dir/'seed.yaml'}: env={env_name!r} not found at {env_dir}"
            )
        for subdir, mount in SANDBOX_MOUNTS.items():
            setup_files.update(_walk_text_files(env_dir / subdir, mount))
        env_yaml_path = env_dir / "env.yaml"
        if env_yaml_path.is_file():
            env_meta = yaml.safe_load(env_yaml_path.read_text()) or {}
            raw_env_mocks = env_meta.get("mocks") or []
            if not isinstance(raw_env_mocks, list):
                raise ValueError(f"{env_yaml_path}: `mocks` must be a list")
            env_mock_names = [str(x) for x in raw_env_mocks]
    for subdir, mount in SANDBOX_MOUNTS.items():
        setup_files.update(_walk_text_files(seed_dir / subdir, mount))

    # Resolve and install shared mocks (env's mocks first, then seed's; dedup).
    mocks_path = seed_dir / "mocks.yaml"
    seed_mock_names: list[str] = []
    if mocks_path.exists():
        raw = yaml.safe_load(mocks_path.read_text())
        if raw is None:
            seed_mock_names = []
        elif isinstance(raw, list):
            seed_mock_names = [str(x) for x in raw]
        else:
            raise ValueError(f"{mocks_path} must be a YAML list of mock names")
    # Track where each mock was declared so a missing-mock error points at the
    # right file (env.yaml vs the seed's mocks.yaml), not always mocks.yaml.
    mock_sources: dict[str, str] = {}
    if env_name is not None:
        for name in env_mock_names:
            mock_sources.setdefault(name, str(env_dir / "env.yaml"))
    for name in seed_mock_names:
        mock_sources.setdefault(name, str(mocks_path))

    seen: set[str] = set()
    mock_names: list[str] = []
    for name in (*env_mock_names, *seed_mock_names):
        if name not in seen:
            seen.add(name)
            mock_names.append(name)

    post_setup: list[str] = []

    for mock_name in mock_names:
        mock_dir = shared_root / "mocks" / mock_name
        if not mock_dir.is_dir():
            raise ValueError(
                f"Mock {mock_name!r} not found at {mock_dir} "
                f"(referenced from {mock_sources.get(mock_name, mocks_path)})"
            )
        bin_src = mock_dir / "bin" / mock_name
        if not bin_src.is_file():
            raise ValueError(
                f"Mock {mock_name!r} has no binary at {bin_src}"
            )
        bin_content = _read_text_or_none(bin_src)
        if bin_content is None:
            raise ValueError(
                f"Mock binary {bin_src} is not text (binary mocks not yet supported)"
            )
        bin_dest = f"/usr/local/bin/{mock_name}"
        setup_files[bin_dest] = bin_content
        post_setup.append(f"chmod +x {bin_dest}")

        # Deploy default service state unless the seed already provided files at
        # those paths. The seed's srv/<mock>-mock/ tree wins over defaults.
        defaults_dir = mock_dir / "defaults"
        for file in sorted(defaults_dir.rglob("*")) if defaults_dir.is_dir() else []:
            if not file.is_file():
                continue
            rel = file.relative_to(defaults_dir).as_posix()
            sandbox_path = f"/srv/{mock_name}-mock/{rel}"
            content = _read_text_or_none(file)
            if content is None:
                continue
            setup_files.setdefault(sandbox_path, content)

    # Ensure the target user can read everything we wrote as root.
    # Order matters: chown before chmod (chmod only touches mock binaries).
    # The '2>/dev/null || true' guards empty directories.
    post_setup.insert(
        0,
        "chown -R user:user /workspace /home/user /srv 2>/dev/null || true",
    )

    # Append seed-declared post_setup commands. Seeds use these to e.g.
    # `git init` their synthetic repos, seed cron log history, or do any
    # other one-time container setup that doesn't fit as a static file.
    # Runs after chown + mock chmod so seed scripts can assume binaries
    # are executable and the target user owns /workspace.
    raw_extra = meta.get("post_setup") or []
    if isinstance(raw_extra, str):
        raw_extra = [raw_extra]
    if not isinstance(raw_extra, list):
        raise ValueError(
            f"{seed_dir/'seed.yaml'}: post_setup must be a list of bash commands"
        )
    post_setup.extend(str(x) for x in raw_extra)

    meta_raw = meta.get("metadata", {}) or {}
    sandbox = tuple(meta["sandbox"]) if "sandbox" in meta else None

    seed_kwargs = dict(
        title=meta["title"],
        description=meta["description"],
        instruction=instruction,
        criteria=criteria,
        metadata=SeedMetadata(**meta_raw),
        setup_files=setup_files,
        required_tools=meta.get("required_tools", []) or [],
        post_setup=post_setup,
    )
    if sandbox is not None:
        seed_kwargs["sandbox"] = sandbox
    return Seed(**seed_kwargs)
