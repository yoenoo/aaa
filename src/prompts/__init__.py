"""Prompt loading and judge-spec bundling."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

_DIR = Path(__file__).parent
_SCAFFOLD_INFO_DIR = _DIR / "scaffold_information"
_JUDGES_DIR = _DIR / "judges"

_SCAFFOLD_NAME_TO_FILE = {
    "Claude Code": "claude_code.md",
    "Codex CLI": "codex_cli.md",
    "Gemini CLI": "gemini_cli.md",
}


@dataclass(frozen=True)
class JudgeSpec:
    """Bundle of (system_prompt, dimensions, extra response blocks) defining one judge."""

    name: str
    system_prompt: str
    dimensions: dict[str, str]
    extra_blocks: tuple[str, ...] = ()


# Each judge family is (system.txt, dimensions.yaml) co-located under judges/<name>/.
# `extra_blocks` lists optional XML sections the parser should extract into metadata.
_JUDGE_EXTRAS: dict[str, tuple[str, ...]] = {
    "scheming": (),
    "debug": ("infrastructure_issues",),
    "legacy": (),
}


def load_scaffold_information(scaffold_name: str) -> str:
    short_name = scaffold_name.split("/")[-1]
    filename = _SCAFFOLD_NAME_TO_FILE.get(short_name)
    if filename is None:
        return f"No detailed information available for the '{scaffold_name}' scaffold."
    path = _SCAFFOLD_INFO_DIR / filename
    if not path.exists():
        return f"No detailed information available for the '{scaffold_name}' scaffold."
    return path.read_text()


def load_system_prompt() -> str:
    return (_DIR / "auditor_system.txt").read_text()


def load_user_message() -> str:
    return (_DIR / "auditor_user.txt").read_text()


def load_judge_spec(name: str) -> JudgeSpec:
    """Load a judge family — its system prompt, dimensions, and required extra blocks.

    Families: "scheming" (31 dims, alignment), "debug" (9 dims, infra/audit quality),
    "legacy" (17 dims, original aaa set).
    """
    if name not in _JUDGE_EXTRAS:
        raise ValueError(
            f"Unknown judge {name!r}. Expected one of: {sorted(_JUDGE_EXTRAS)}."
        )
    family_dir = _JUDGES_DIR / name
    system_prompt = (family_dir / "system.txt").read_text()
    dimensions = yaml.safe_load((family_dir / "dimensions.yaml").read_text())
    return JudgeSpec(
        name=name,
        system_prompt=system_prompt,
        dimensions=dimensions,
        extra_blocks=_JUDGE_EXTRAS[name],
    )
