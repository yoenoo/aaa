"""Seed and metadata contracts."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from textwrap import dedent

SANDBOX_COMPOSE = Path(__file__).resolve().parents[2] / "sandbox" / "scaffold-compose.yaml"


@dataclass
class SeedMetadata:
    """Scenario requirements declared by each seed.

    The orchestrator reads these to configure turn budgets,
    branching requirements, and enforcement.
    """
    branch_comparison_required: bool = True
    max_rollbacks: int = 3
    max_interaction_turns: int = 50
    max_model_turns: int = 80
    scenario_type: str = "scheming"
    tags: list[str] = field(default_factory=list)


@dataclass
class Seed:
    """Everything needed to run an audit.

    A seed bundles auditor instructions, grading criteria,
    environment setup, and scenario metadata.
    """
    title: str                                  # human-readable name
    description: str                            # what the scenario tests
    instruction: str                            # auditor's task
    criteria: str                               # grading criteria (for judge)
    metadata: SeedMetadata = field(default_factory=SeedMetadata)
    sandbox: tuple[str, str] = ("docker", str(SANDBOX_COMPOSE))
    setup_files: dict[str, str] = field(default_factory=dict)
    required_tools: list[str] = field(default_factory=list)  # Python function stubs


def parse_seed_tools(required_tools: list[str]) -> list[dict]:
    """Parse seed-declared Python function stubs into tool definition dicts.

    Seeds declare tools as Python function stubs (with docstrings, no body).
    This parses them into dicts with name, description, and parameters
    that can be converted to inspect_ai ToolInfo objects.

    Args:
        required_tools: List of Python function code strings from seed dicts

    Returns:
        List of tool definition dicts: {name, description, parameters: [{name, type, description, optional}]}
    """
    tool_defs = []
    for code in required_tools:
        try:
            tool_defs.append(_parse_function_stub(code))
        except Exception:
            continue
    return tool_defs


def _parse_function_stub(code: str) -> dict:
    """Parse a single Python function stub into a tool definition dict."""
    code = dedent(code).strip()
    parsed = ast.parse(code)

    if len(parsed.body) != 1 or not isinstance(parsed.body[0], ast.FunctionDef):
        raise ValueError("Code must contain exactly one function definition")

    func_def = parsed.body[0]
    name = func_def.name
    docstring = ast.get_docstring(func_def) or f"Tool '{name}'."

    # Extract description (first line/paragraph before Args:)
    desc_lines = []
    for line in docstring.split("\n"):
        stripped = line.strip()
        if stripped.lower().startswith("args:") or stripped.lower().startswith("returns:"):
            break
        desc_lines.append(stripped)
    description = " ".join(l for l in desc_lines if l).strip()

    # Extract parameters from function signature
    params = []
    for arg in func_def.args.args:
        if arg.arg == "self":
            continue
        param_type = "string"
        if arg.annotation and isinstance(arg.annotation, ast.Name):
            ann = arg.annotation.id.lower()
            if ann == "int":
                param_type = "integer"
            elif ann == "float":
                param_type = "number"
            elif ann == "bool":
                param_type = "boolean"

        # Try to extract param description from docstring
        param_desc = _extract_param_desc(docstring, arg.arg)

        params.append({
            "name": arg.arg,
            "type": param_type,
            "description": param_desc,
            "optional": False,
        })

    # Mark params with defaults as optional
    n_defaults = len(func_def.args.defaults)
    if n_defaults:
        for param in params[-n_defaults:]:
            param["optional"] = True

    return {"name": name, "description": description, "parameters": params}


def _extract_param_desc(docstring: str, param_name: str) -> str:
    """Extract a parameter description from a Google-style docstring."""
    lines = docstring.split("\n")
    in_args = False
    for line in lines:
        stripped = line.strip()
        if stripped.lower().startswith("args:"):
            in_args = True
            continue
        if in_args:
            if stripped.lower().startswith("returns:"):
                break
            if stripped.startswith(f"{param_name}:"):
                return stripped.split(":", 1)[1].strip()
    return "Parameter."
