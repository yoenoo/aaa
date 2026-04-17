"""Target runtime protocol and factory."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class TargetResponse:
    """Response from a target runtime after processing a message."""
    text: str
    tool_calls_summary: str = ""
    model_calls: int = 0
    reasoning: str = ""


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
