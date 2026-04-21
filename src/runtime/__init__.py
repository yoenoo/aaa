"""Target runtime protocol and factory."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


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

    def register_modification(self, tool_name: str, match_pattern: str, modified_result: str) -> None:
        """Pre-register a tool result modification.

        The next matching tool call will execute for real, but the target
        sees modified_result instead.
        """
        ...
