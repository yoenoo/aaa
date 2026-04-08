"""Seed registry. Auto-discovers .seed files in this directory."""

from pathlib import Path

import yaml

from .metadata import Seed, SeedMetadata

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
        sandbox=tuple(raw["sandbox"]) if "sandbox" in raw else Seed.sandbox,
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


def _discover() -> None:
    for path in _SEEDS_DIR.glob("*.yaml"):
        name = path.stem
        _SEEDS[name] = _load_seed_file(path)
