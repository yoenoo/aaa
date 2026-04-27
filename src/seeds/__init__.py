"""Seed registry.

Supports two seed formats:

1. **Legacy single-file YAML** — ``src/seeds/<category>/<name>.yaml``.
   The file embeds ``setup_files`` inline. Kept for backwards compatibility with
   the stock ``sc-*``, ``cr-*``, ``aa-*`` seeds.

2. **Directory-structured** — ``src/seeds/<category>/<name>/`` with
   ``seed.yaml`` + ``instruction.md`` + ``criteria.md`` + ``mocks.yaml`` +
   ``workspace/``, ``home/``, ``srv/`` trees. Loaded by ``loader.py``.

Both formats coexist. ``list_seeds()`` returns all discovered seed ids across
both formats. Directory names win over same-named YAML files.

Files under ``_shared/`` (mocks, templates) are not seeds and are skipped by
discovery.
"""

from pathlib import Path

import yaml

from .loader import is_structured_seed_dir, load_structured_seed
from .metadata import Seed, SeedMetadata, _default_sandbox

_SEEDS: dict[str, Seed] = {}
_SEEDS_DIR = Path(__file__).parent


def _load_legacy_yaml(path: Path) -> Seed:
    raw = yaml.safe_load(path.read_text())
    meta_raw = raw.get("metadata", {})
    return Seed(
        title=raw["title"],
        description=raw["description"],
        instruction=raw["instruction"],
        criteria=raw["criteria"],
        metadata=SeedMetadata(**meta_raw),
        sandbox=tuple(raw["sandbox"]) if "sandbox" in raw else _default_sandbox(),
        setup_files=raw.get("setup_files", {}),
        required_tools=raw.get("required_tools", []),
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
    return "_shared" in path.parts[len(_SEEDS_DIR.parts):]


def _discover() -> None:
    # Pass 1: directory-structured seeds. Do these first so their seed.yaml
    # files are claimed by the directory loader, not the legacy scanner.
    for subdir in sorted(_SEEDS_DIR.rglob("*")):
        if not subdir.is_dir():
            continue
        if _is_in_shared(subdir):
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

    # Pass 2: legacy single-file YAML seeds. These live at fixed depth
    # `src/seeds/<category>/<name>.yaml` (one directory deep under the
    # seeds root). Anything nested deeper is content inside a structured
    # seed's `workspace/`, `home/`, or `srv/` tree (e.g. a
    # `.soc-agent/profile.yaml` or a playbook draft), and must not be
    # interpreted as a legacy seed — even if the surrounding structured
    # seed is mid-authoring and doesn't yet have its `seed.yaml` +
    # `instruction.md` pair in place.
    for path in sorted(_SEEDS_DIR.rglob("*.yaml")):
        if _is_in_shared(path):
            continue
        rel = path.relative_to(_SEEDS_DIR)
        # Legacy layout: exactly `<category>/<name>.yaml` (2 parts).
        if len(rel.parts) != 2:
            continue
        name = path.stem
        if name in _SEEDS:
            existing = _SEEDS[name]
            raise ValueError(
                f"Duplicate seed id {name!r} at {path} (already registered: {existing.title!r})"
            )
        _SEEDS[name] = _load_legacy_yaml(path)
