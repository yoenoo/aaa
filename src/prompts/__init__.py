"""Prompt loading and formatting."""

from pathlib import Path

import yaml

_DIR = Path(__file__).parent
_SCAFFOLD_INFO_DIR = _DIR / "scaffold_information"

_SCAFFOLD_NAME_TO_FILE = {
    "Claude Code": "claude_code.md",
    "Codex CLI": "codex_cli.md",
    "Gemini CLI": "gemini_cli.md",
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


def load_judge_prompt() -> str:
    return (_DIR / "judge_system.txt").read_text()


def load_dimensions() -> dict[str, str]:
    return yaml.safe_load((_DIR / "dimensions.yaml").read_text())
