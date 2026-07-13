"""Target runtime protocol and factory."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


# Tool functions for which positional ("ordered") fallback pairing of a tool
# RESULT to its originating tool CALL is safe — read/inspect/file/shell tools
# that are deterministic and order-stable, so zipping calls to results in order
# can't attach a result to the wrong command. Tool names differ per scaffold,
# so this set spans all three runtimes we drive:
#   - Gemini CLI: snake_case (run_shell_command, read_file, …)
#   - Claude Code: PascalCase (Bash, Read, Edit, …) — note CC/Codex use `Bash`,
#     not `run_shell_command`
#   - Codex CLI: `shell` for command execution
# Shared here (rather than duplicated in runtime/scaffold.py and transcript.py)
# so the live-pairing path and the post-hoc transcript path stay in lockstep.
# Anything not in this set falls back to a placeholder rather than risk pairing
# a result to the wrong call.
SAFE_ORDERED_RESULT_FUNCTIONS: set[str] = {
    # Gemini CLI
    "read_file",
    "list_directory",
    "grep_search",
    "glob",
    "write_file",
    "replace",
    "web_fetch",
    "run_shell_command",
    # Claude Code
    "Bash",
    "Read",
    "LS",
    "Glob",
    "Grep",
    "Write",
    "Edit",
    "MultiEdit",
    "WebFetch",
    # Codex CLI
    "shell",
}


@dataclass
class TargetToolCall:
    """One tool call the target made during a turn.

    `result` is filled in after the tool runs (captured from the next inner
    turn's input messages). Stays None only if the target turn ended before
    the tool result flowed back.
    """
    id: str
    function: str
    arguments: dict[str, Any]
    result: str | None = None


@dataclass
class TargetTurn:
    """One internal model turn the target made while handling a message."""
    text: str
    reasoning: str = ""
    tool_calls: list[TargetToolCall] = field(default_factory=list)


@dataclass
class TargetResponse:
    """Response from a target runtime after processing a message.

    `activity` is the full per-turn trace (intermediate text + tool calls +
    results). Empty for runtimes that don't track per-turn detail.
    `text` is the final terminal message the target produced.
    """
    text: str
    tool_calls_summary: str = ""
    model_calls: int = 0
    reasoning: str = ""
    activity: list[TargetTurn] = field(default_factory=list)


class TargetRuntime(Protocol):
    """Interface for interacting with a target model.

    Two implementations:
    - ScaffoldRuntime: ACP agent (Claude Code, Codex CLI) owns the tool loop
    - BareModelRuntime: We own the tool loop, calling model.generate() directly
    """

    async def start(self) -> None:
        """Start the target session."""
        ...

    async def stop(self) -> None:
        """Stop the target session."""
        ...

    async def send(self, message: str) -> TargetResponse:
        """Send a message and wait for the target's full response."""
        ...

    async def reset(self) -> None:
        """Reset to a fresh session. Target loses all history."""
        ...
