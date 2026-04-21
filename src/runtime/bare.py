"""Bare model runtime: we own the tool execution loop.

No scaffold involved. We call model.generate() directly, execute tool calls
in the sandbox, and apply modifications between calls.

Tools come from the seed's required_tools (Python function stubs parsed via AST)
or fall back to standard sandbox tools (bash, read_file, write_file).
"""

from __future__ import annotations

import json

from inspect_ai.model import (
    ChatMessage,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
    ContentReasoning,
    ContentText,
    Model,
)
from inspect_ai.tool import ToolInfo, ToolParam
from inspect_ai.util import SandboxEnvironment

from . import TargetResponse, TargetToolCall, TargetTurn


# Default tools when no seed tools are provided
_DEFAULT_TOOLS = [
    {
        "name": "bash",
        "description": "Run a shell command.",
        "parameters": [
            {"name": "command", "type": "string", "description": "Shell command to execute.", "optional": False},
        ],
    },
    {
        "name": "read_file",
        "description": "Read a file.",
        "parameters": [
            {"name": "path", "type": "string", "description": "Absolute file path.", "optional": False},
        ],
    },
    {
        "name": "write_file",
        "description": "Write a file.",
        "parameters": [
            {"name": "path", "type": "string", "description": "Absolute file path.", "optional": False},
            {"name": "content", "type": "string", "description": "File content.", "optional": False},
        ],
    },
]


class BareModelRuntime:
    """Target runtime that calls model.generate() directly.

    We manage the message history and tool execution loop ourselves.
    Tool calls execute in the sandbox; modifications are applied inline.

    Tools are parsed from the seed's required_tools (Python function stubs)
    or default to bash/read_file/write_file for sandbox execution.
    """

    def __init__(
        self,
        model: Model,
        sandbox: SandboxEnvironment,
        system_prompt: str = "You are a helpful coding assistant.",
        max_tool_rounds: int = 50,
        seed_tools: list[dict] | None = None,
        expose_reasoning: bool = False,
    ):
        self._model = model
        self._sandbox = sandbox
        self._system_prompt = system_prompt
        self._max_tool_rounds = max_tool_rounds
        self._expose_reasoning = expose_reasoning
        self._modifications: dict[tuple[str, str], str] = {}
        self._messages: list[ChatMessage] = []

        tool_defs = seed_tools if seed_tools else _DEFAULT_TOOLS
        self._tool_defs = tool_defs
        self._tools = _build_tool_infos(tool_defs)

    async def start(self) -> None:
        self._messages = [ChatMessageSystem(content=self._system_prompt)]

    async def stop(self) -> None:
        pass

    async def send(self, message: str) -> TargetResponse:
        self._messages.append(ChatMessageUser(content=message))

        model_calls = 0
        reasoning_buf: list[str] = []
        activity: list[TargetTurn] = []
        for _ in range(self._max_tool_rounds):
            output = await self._model.generate(
                input=self._messages, tools=self._tools,
            )
            model_calls += 1
            self._messages.append(output.message)

            turn_text = _extract_text(output.message.content)
            turn_reasoning = _extract_reasoning(output.message.content)
            turn_calls: list[TargetToolCall] = [
                TargetToolCall(
                    id=tc.id, function=tc.function, arguments=dict(tc.arguments),
                )
                for tc in (output.message.tool_calls or [])
            ]

            if self._expose_reasoning and turn_reasoning:
                reasoning_buf.append(turn_reasoning)

            if not output.message.tool_calls:
                activity.append(TargetTurn(
                    text=turn_text, reasoning=turn_reasoning, tool_calls=turn_calls,
                ))
                break

            # Execute each tool call, record the result the target saw
            # (post-modification) so the auditor gets the real picture.
            for tc, entry in zip(output.message.tool_calls, turn_calls):
                result = await self._execute_tool(tc.function, tc.arguments)
                result = self._check_modification(tc.function, tc.arguments, result)
                entry.result = result

                self._messages.append(
                    ChatMessageTool(content=result, tool_call_id=tc.id, function=tc.function)
                )

            activity.append(TargetTurn(
                text=turn_text, reasoning=turn_reasoning, tool_calls=turn_calls,
            ))

        text = _extract_text(output.message.content)

        tc_summary = ""
        for tc in output.message.tool_calls or []:
            tc_summary += f"\n[Tool call: {tc.function}({json.dumps(tc.arguments)[:200]})]"

        return TargetResponse(
            text=text,
            tool_calls_summary=tc_summary,
            model_calls=model_calls,
            reasoning="\n\n".join(reasoning_buf) if self._expose_reasoning else "",
            activity=activity,
        )

    async def reset(self) -> None:
        self._messages = [ChatMessageSystem(content=self._system_prompt)]
        self._modifications.clear()

    def register_modification(self, tool_name: str, match_pattern: str, modified_result: str) -> None:
        self._modifications[(tool_name, match_pattern)] = modified_result

    # -- internal --

    async def _execute_tool(self, name: str, args: dict) -> str:
        """Execute a tool call in the sandbox.

        Standard tools (bash, read_file, write_file) are handled directly.
        Custom seed tools are dispatched to the sandbox via bash when possible,
        or return a placeholder indicating the tool executed.
        """
        if name == "bash":
            result = await self._sandbox.exec(
                ["bash", "-c", args.get("command", "")], timeout=30,
            )
            output = result.stdout
            if result.stderr:
                output += f"\nSTDERR: {result.stderr}"
            if result.returncode != 0:
                output += f"\n(exit code {result.returncode})"
            return output or "(no output)"

        if name == "read_file":
            path = args.get("path", "")
            try:
                return await self._sandbox.read_file(path)
            except Exception as e:
                return f"Error reading {path}: {e}"

        if name == "write_file":
            path = args.get("path", "")
            content = args.get("content", "")
            parent = "/".join(path.split("/")[:-1])
            if parent:
                await self._sandbox.exec(["mkdir", "-p", parent], timeout=10)
            await self._sandbox.write_file(path, content)
            return f"Written {path}"

        # Custom seed tool — not executable in sandbox directly.
        # Return a structured acknowledgment so the tool result modification
        # system can intercept it, or the model can proceed.
        args_summary = ", ".join(f"{k}={str(v)[:100]}" for k, v in args.items())
        return f"[Tool '{name}' executed with args: {args_summary}]"

    def _check_modification(self, fn_name: str, fn_args: dict, real_result: str) -> str:
        for mod_key, mod_result in list(self._modifications.items()):
            mod_tool, mod_pattern = mod_key
            if mod_pattern is not None:
                if any(isinstance(v, str) and mod_pattern in v for v in fn_args.values()):
                    del self._modifications[mod_key]
                    return mod_result
            elif fn_name.lower() == mod_tool.lower():
                del self._modifications[mod_key]
                return mod_result
        return real_result


def _extract_text(content: str | list) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(
        c.text for c in (content or []) if isinstance(c, ContentText)
    )


def _extract_reasoning(content: str | list) -> str:
    """Extract the target's reasoning, preferring provider summaries for
    redacted/encrypted thinking blocks."""
    if isinstance(content, str):
        return ""
    parts: list[str] = []
    for c in content or []:
        if not isinstance(c, ContentReasoning):
            continue
        summary = (c.summary or "").strip()
        if c.redacted:
            if summary:
                parts.append(summary)
        else:
            raw = (c.reasoning or "").strip()
            if raw:
                parts.append(raw)
            elif summary:
                parts.append(summary)
    return "\n\n".join(parts)


def _build_tool_infos(tool_defs: list[dict]) -> list[ToolInfo]:
    """Convert tool definition dicts to inspect_ai ToolInfo objects.

    Accepts dicts with keys: name, description, parameters (list of param dicts).
    Each param dict has: name, type, description, optional.
    """
    tools = []
    for t in tool_defs:
        params = []
        for p in t.get("parameters", []):
            params.append(ToolParam(
                name=p["name"],
                type=p.get("type", "string"),
                description=p.get("description", ""),
                optional=p.get("optional", False),
            ))
        tools.append(ToolInfo(
            name=t["name"],
            description=t["description"],
            parameters=params,
        ))
    return tools
