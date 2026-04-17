"""Scaffold runtime: target runs inside an ACP agent (Claude Code, Codex CLI, etc.).

The scaffold owns the tool execution loop. We hook into it via a GenerateFilter
that modifies tool results before the target model sees them.
"""

from __future__ import annotations

import json

import anyio
from inspect_ai.agent import run
from inspect_ai.model import (
    ChatMessage,
    ChatMessageTool,
    Content,
    ContentReasoning,
    ContentText,
    GenerateConfig,
    GenerateFilter,
    Model,
    ModelOutput,
)
from inspect_ai.tool import ToolChoice, ToolInfo
from inspect_swe import interactive_claude_code, interactive_codex_cli, interactive_gemini_cli

from . import TargetResponse

_SCAFFOLD_FACTORIES = {
    "Claude Code": interactive_claude_code,
    "Codex CLI": interactive_codex_cli,
    "Gemini CLI": interactive_gemini_cli,
}


class ScaffoldRuntime:
    """Target runtime backed by an ACP scaffold agent.

    The scaffold (e.g. Claude Code) owns the tool execution loop.
    We intercept tool results via a GenerateFilter to apply modifications.
    """

    def __init__(
        self,
        model: Model,
        scaffold_name: str,
        reasoning_effort: str | None = "medium",
        expose_reasoning: bool = False,
    ):
        self._model = model
        self._scaffold_name = scaffold_name
        self._reasoning_effort = reasoning_effort
        self._expose_reasoning = expose_reasoning
        self._modifications: dict[tuple[str, str], str] = {}
        self._applied: dict[str, str] = {}
        self._response: TargetResponse | None = None
        self._reasoning_buf: list[str] = []
        self._agent = None
        self._ready = anyio.Event()

    async def start(self) -> None:
        factory = _SCAFFOLD_FACTORIES.get(self._scaffold_name)
        if factory is None:
            raise ValueError(
                f"Unknown scaffold '{self._scaffold_name}'. "
                f"Available: {', '.join(_SCAFFOLD_FACTORIES)}"
            )
        self._agent = factory(
            model=self._model,
            filter=self._make_filter(),
        )
        self._run_scope = anyio.CancelScope()

        async def _run():
            with self._run_scope:
                await run(self._agent, "")

        async def _wait_ready():
            await self._agent.ready.wait()
            self._ready.set()

        self._tg = anyio.create_task_group()
        await self._tg.__aenter__()
        self._tg.start_soon(_run)
        self._tg.start_soon(_wait_ready)
        await self._ready.wait()

    async def stop(self) -> None:
        self._run_scope.cancel()
        try:
            await self._tg.__aexit__(None, None, None)
        except Exception:
            pass

    async def send(self, message: str) -> TargetResponse:
        from acp import text_block

        if self._agent is None or self._agent.conn is None:
            raise RuntimeError("Target session not ready")

        prev_turn = self._turn_count
        self._reasoning_buf = []
        await self._agent.conn.prompt(
            prompt=[text_block(message)],
            session_id=self._agent.session_id,
        )
        resp = self._response or TargetResponse(text="(no response captured)")
        resp.model_calls = self._turn_count - prev_turn
        if self._expose_reasoning:
            resp.reasoning = "\n\n".join(r for r in self._reasoning_buf if r)
        return resp

    async def reset(self) -> None:
        # Tear down current session
        await self.stop()

        # Clear modifications for fresh branch
        self._modifications.clear()
        self._applied.clear()
        self._response = None
        self._reasoning_buf = []
        self._turn_count = 0
        self._ready = anyio.Event()

        # Start fresh session
        await self.start()

    def register_modification(self, tool_name: str, match_pattern: str, modified_result: str) -> None:
        self._modifications[(tool_name, match_pattern)] = modified_result

    # -- internal --

    _turn_count: int = 0

    def _make_filter(self) -> GenerateFilter:
        async def _filter(
            model: Model,
            messages: list[ChatMessage],
            tools: list[ToolInfo],
            tool_choice: ToolChoice | None,
            config: GenerateConfig,
        ) -> ModelOutput | None:
            messages = self._apply_modifications(messages)

            if self._reasoning_effort:
                config = config.model_copy(update={"reasoning_effort": self._reasoning_effort})

            output = await model.generate(
                input=messages, tools=tools, tool_choice=tool_choice, config=config,
            )

            # Capture response for auditor
            text = _extract_text(output.message.content)
            tc_summary = ""
            for tc in output.message.tool_calls or []:
                tc_summary += f"\n[Tool call: {tc.function}({json.dumps(tc.arguments)[:200]})]"

            if self._expose_reasoning:
                r = _extract_reasoning(output.message.content)
                if r:
                    self._reasoning_buf.append(r)

            self._response = TargetResponse(text=text, tool_calls_summary=tc_summary)
            self._turn_count += 1
            return output

        return _filter

    def _apply_modifications(self, messages: list[ChatMessage]) -> list[ChatMessage]:
        if not self._modifications and not self._applied:
            return messages

        # Build tool_call_id -> (function_name, arguments) map
        tc_meta: dict[str, tuple[str, dict]] = {}
        for msg in messages:
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    tc_meta[tc.id] = (tc.function, tc.arguments)

        result = list(messages)
        for i, msg in enumerate(result):
            if not isinstance(msg, ChatMessageTool):
                continue

            tc_id = msg.tool_call_id

            # Re-apply previously matched modification
            if tc_id in self._applied:
                result[i] = ChatMessageTool(content=self._applied[tc_id], tool_call_id=tc_id)
                continue

            # Try to match a new modification
            if not self._modifications or tc_id not in tc_meta:
                continue

            fn_name, fn_args = tc_meta[tc_id]
            for mod_key, mod_result in list(self._modifications.items()):
                mod_tool, mod_pattern = mod_key
                if _matches(fn_name, fn_args, mod_tool, mod_pattern):
                    self._applied[tc_id] = mod_result
                    result[i] = ChatMessageTool(content=mod_result, tool_call_id=tc_id)
                    del self._modifications[mod_key]
                    break

        return result


def _matches(fn_name: str, fn_args: dict, mod_tool: str, mod_pattern: str | None) -> bool:
    """Check if a tool call matches a modification rule.

    Pattern takes precedence: if provided, matches any tool whose arguments
    contain the pattern string. Tool name is a fallback when no pattern given.
    """
    if mod_pattern is not None:
        return any(isinstance(v, str) and mod_pattern in v for v in fn_args.values())
    return fn_name.lower() == mod_tool.lower()


def _extract_text(content: str | list[Content]) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(c.text for c in content if isinstance(c, ContentText))


def _extract_reasoning(content: str | list[Content]) -> str:
    """Extract the target's reasoning, preferring provider-returned summaries
    for redacted/encrypted thinking blocks (Anthropic extended-thinking,
    OpenAI encrypted_content)."""
    if isinstance(content, str):
        return ""
    parts: list[str] = []
    for c in content:
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
