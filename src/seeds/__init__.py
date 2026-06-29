"""Seed registry. Auto-discovers .seed files in this directory."""

from pathlib import Path

import yaml

from .loader import is_structured_seed_dir, load_structured_seed
from .metadata import Seed, SeedMetadata, _default_sandbox, resolve_sandbox

_SEEDS: dict[str, Seed] = {}
_SEEDS_DIR = Path(__file__).parent


def _load_seed_file(path: Path) -> Seed:
    raw = yaml.safe_load(path.read_text())
    meta_raw = raw.get("metadata", {})
    return Seed(
        title=raw["title"],
        description=raw["description"],
        instruction=raw["instruction"],
        criteria=raw["criteria"],
        metadata=SeedMetadata(**meta_raw),
        sandbox=resolve_sandbox(raw.get("sandbox")),
        setup_files=raw.get("setup_files", {}),
        required_tools=raw.get("required_tools", []),
        protocol=raw.get("protocol", []),
    )


def load_seed(name: str) -> Seed:
    if not _SEEDS:
        _discover()
    if name not in _SEEDS:
        available = ", ".join(sorted(_SEEDS))
        raise ValueError(f"Unknown seed: {name!r}. Available: {available}")
    return _SEEDS[name]


def list_seeds() -> list[str]:
    if not _SEEDS:
        _discover()
    return sorted(_SEEDS)


def _is_in_shared(path: Path) -> bool:
    # Only the top-level src/seeds/_shared/ tree (mocks, envs, templates) is
    # "shared" and not a seed. Match the first path component, not any component
    # named _shared (which could appear inside a seed's workspace/ tree).
    rel_parts = path.relative_to(_SEEDS_DIR).parts
    return bool(rel_parts) and rel_parts[0] == "_shared"


def _discover() -> None:
    # Pass 1: directory-structured seeds (src/seeds/<cat>/<name>/ with seed.yaml
    # + instruction.md). Claim these first so their seed.yaml isn't also picked
    # up by the legacy single-file scanner below.
    for subdir in sorted(_SEEDS_DIR.rglob("*")):
        if not subdir.is_dir() or _is_in_shared(subdir):
            continue
        if not is_structured_seed_dir(subdir):
            continue
        name = subdir.name
        if name in _SEEDS:
            raise ValueError(
                f"Duplicate seed id {name!r} at {subdir} "
                f"(already registered: {_SEEDS[name].title!r})"
            )
        _SEEDS[name] = load_structured_seed(subdir)

    # Pass 2: legacy single-file YAML at fixed depth <category>/<name>.yaml.
    # Skip _shared/, and skip anything nested deeper (that's content inside a
    # directory seed's workspace/home/srv tree, not a seed itself).
    for path in sorted(_SEEDS_DIR.rglob("*.yaml")):
        if _is_in_shared(path):
            continue
        if len(path.relative_to(_SEEDS_DIR).parts) != 2:
            continue
        name = path.stem
        if name in _SEEDS:
            existing = _SEEDS[name]
            raise ValueError(
                f"Duplicate seed id {name!r} at {path} (already registered from elsewhere: {existing.title!r})"
            )
        _SEEDS[name] = _load_seed_file(path)
