"""Scaffold runtime: target runs inside an ACP agent (Claude Code, Codex CLI, etc.)."""

from __future__ import annotations

import json
import os

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

from . import TargetResponse, TargetToolCall, TargetTurn

_SCAFFOLD_FACTORIES = {
    "Claude Code": interactive_claude_code,
    "Codex CLI": interactive_codex_cli,
    "Gemini CLI": interactive_gemini_cli,
}

# Keep the scaffold rooted at the same path the seed provisions into, so the
# target's built-in file tools (read_file, list_directory, …) see the seed
# files without the auditor having to tell it where they are.
_SANDBOX_WORKDIR = "/workspace"

# Per-send wall-clock timeout. If the ACP scaffold hangs (sub-process stuck in
# a blocking syscall, connection dropped mid-prompt, etc.), conn.prompt() can
# never return — without a timeout the entire audit stalls indefinitely. When
# we hit the limit we surface a synthetic TargetResponse so the auditor can
# decide whether to reset and retry or move on. Override with
# AAA_SEND_TIMEOUT_SECS; default is 5 min which comfortably covers a
# legitimate Gemini CLI turn with many tool calls.
_DEFAULT_SEND_TIMEOUT_SECS = 300.0
_STOP_TIMEOUT_SECS = 30.0


class ScaffoldRuntime:
    """Target runtime backed by an ACP scaffold agent.

    The scaffold (e.g. Claude Code) owns the tool execution loop.
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
        self._response: TargetResponse | None = None
        self._reasoning_buf: list[str] = []
        # Per-send target activity trace: list of TargetTurns, one per
        # internal model call the scaffold made. Reset at send() start.
        self._activity: list[TargetTurn] = []
        self._agent = None
        self._ready = anyio.Event()
        try:
            self._send_timeout = float(os.environ.get(
                "AAA_SEND_TIMEOUT_SECS", _DEFAULT_SEND_TIMEOUT_SECS,
            ))
        except ValueError:
            self._send_timeout = _DEFAULT_SEND_TIMEOUT_SECS
        # Tool-result tracking: ChatMessageTool.tool_call_ids we've already
        # attached to a TargetToolCall. The filter runs once per model turn
        # and receives the full conversation-so-far, so prior turns'
        # tool messages appear repeatedly; without this we'd re-match them.
        self._seen_result_ids: set[str] = set()

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
            cwd=_SANDBOX_WORKDIR,
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
        # Bound the join: if the scaffold sub-process is wedged in a blocking
        # syscall the cancel may not free it quickly. Don't block reset_target
        # on a dead scaffold.
        try:
            with anyio.move_on_after(_STOP_TIMEOUT_SECS):
                await self._tg.__aexit__(None, None, None)
        except Exception:
            pass

    async def send(self, message: str) -> TargetResponse:
        from acp import text_block

        if self._agent is None or self._agent.conn is None:
            raise RuntimeError("Target session not ready")

        prev_turn = self._turn_count
        self._reasoning_buf = []
        # _activity is cumulative across sends within a session — _make_filter
        # appends to it, and _capture_tool_results pairs tool messages by
        # position against the full history. Snapshot the start so we can
        # slice out just this send's turns for the response.
        activity_start = len(self._activity)

        # Guard conn.prompt against indefinite hangs. If the scaffold
        # sub-process gets stuck on a tool call (e.g. subprocess spawned by
        # `bash` blocks, or ACP bridge drops the connection mid-prompt), the
        # awaiting audit loop would stall for the rest of the run. Surface a
        # synthetic response instead so the auditor can decide next steps
        # (typically: reset_target and retry).
        timed_out = False
        exit_err: Exception | None = None
        try:
            with anyio.fail_after(self._send_timeout):
                await self._agent.conn.prompt(
                    prompt=[text_block(message)],
                    session_id=self._agent.session_id,
                )
        except TimeoutError:
            timed_out = True
        except Exception as e:
            exit_err = e

        resp = self._response or TargetResponse(text="(no response captured)")
        if timed_out:
            resp = TargetResponse(
                text=(
                    f"(target did not respond within {self._send_timeout:.0f}s; "
                    "scaffold likely hung — consider calling reset_target)"
                ),
                tool_calls_summary="[send timed out]",
            )
        elif exit_err is not None:
            resp = TargetResponse(
                text=(
                    f"(target scaffold errored: {type(exit_err).__name__}: {exit_err} — "
                    "consider calling reset_target)"
                ),
                tool_calls_summary="[scaffold error]",
            )
        resp.model_calls = self._turn_count - prev_turn
        if self._expose_reasoning:
            resp.reasoning = "\n\n".join(r for r in self._reasoning_buf if r)
        resp.activity = list(self._activity[activity_start:])
        return resp

    async def reset(self) -> None:
        # Tear down current session
        await self.stop()

        self._response = None
        self._reasoning_buf = []
        self._activity = []
        self._turn_count = 0
        self._seen_result_ids.clear()
        self._ready = anyio.Event()

        # Start fresh session
        await self.start()

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
            # Tool results for prior calls land in `messages` as ChatMessageTool
            # entries — attach them to the matching TargetToolCall we recorded
            # on a previous filter pass. This gives the auditor the result the
            # target actually saw (post-modification).
            self._capture_tool_results(messages)

            if self._reasoning_effort:
                config = config.model_copy(update={"reasoning_effort": self._reasoning_effort})

            output = await model.generate(
                input=messages, tools=tools, tool_choice=tool_choice, config=config,
            )

            text = _extract_text(output.message.content)
            reasoning = _extract_reasoning(output.message.content)

            tc_summary = ""
            tool_calls: list[TargetToolCall] = []
            for tc in output.message.tool_calls or []:
                tc_summary += f"\n[Tool call: {tc.function}({json.dumps(tc.arguments)[:200]})]"
                tool_calls.append(TargetToolCall(
                    id=tc.id,
                    function=tc.function,
                    arguments=dict(tc.arguments),
                ))

            self._activity.append(TargetTurn(
                text=text, reasoning=reasoning, tool_calls=tool_calls,
            ))

            if self._expose_reasoning and reasoning:
                self._reasoning_buf.append(reasoning)

            self._response = TargetResponse(text=text, tool_calls_summary=tc_summary)
            self._turn_count += 1
            return output

        return _filter

    def _capture_tool_results(self, messages: list[ChatMessage]) -> None:
        """Pair ChatMessageTool results to recorded TargetToolCalls.

        The ACP bridge rewrites tool_call_ids between the model-side id and
        the scaffold-side id, so direct id-match doesn't work. Prior
        versions relied on strict global position (zip pending calls against
        the Nth+ tool_msg) — that broke when the scaffold parallelized or
        reordered calls within a turn, causing results to be attached to
        the wrong command (see debug-judge highlights on the
        as-self-preservation run: `head -n 25 ...` returning `ls -la`
        output, `cat file1` returning file2's contents, etc.).

        New strategy:

        1. Track which tool_call_ids we've already captured across prior
           filter invocations. The filter receives the full
           conversation-so-far, so prior-turn results reappear; without
           this we'd either re-match or confuse the ordering.
        2. Bucket unseen ChatMessageTool messages by function name.
           Pair each pending TargetToolCall with the next unseen message
           of the same function. Position within a bucket (same function
           called N times in a row) is preserved from the scaffold, so
           this reduces to correct position-based matching inside a
           function and rules out cross-function contamination.
        3. Log a warning when we can't pair a pending call — previously
           this failure was silent, letting bad data reach the auditor.
        """
        pending = [c for turn in self._activity for c in turn.tool_calls if c.result is None]
        if not pending:
            return

        unseen_msgs = [
            m for m in messages
            if isinstance(m, ChatMessageTool)
            and m.tool_call_id not in self._seen_result_ids
        ]
        if not unseen_msgs:
            return

        by_fn: dict[str, list[ChatMessageTool]] = {}
        for m in unseen_msgs:
            fn = getattr(m, "function", None) or ""
            by_fn.setdefault(fn, []).append(m)

        for call in pending:
            bucket = by_fn.get(call.function)
            if not bucket:
                print(
                    f"[scaffold] WARNING: no result found for pending tool call "
                    f"id={call.id!r} function={call.function!r} "
                    f"(unseen fns: {sorted(by_fn)})",
                    flush=True,
                )
                continue
            msg = bucket.pop(0)
            call.result = _unwrap_tool_result(_extract_text(msg.content))
            self._seen_result_ids.add(msg.tool_call_id)

        # Any leftover messages we couldn't attribute (scaffold surfaced
        # results for calls we never recorded): log and drop.
        leftover = sum(len(v) for v in by_fn.values())
        if leftover:
            fns = {k: len(v) for k, v in by_fn.items() if v}
            print(
                f"[scaffold] WARNING: {leftover} tool results not matched to "
                f"recorded calls: {fns}",
                flush=True,
            )
            for bucket in by_fn.values():
                for m in bucket:
                    self._seen_result_ids.add(m.tool_call_id)

def _unwrap_tool_result(content: str) -> str:
    """Unwrap the `{"output": "..."}` envelope some ACP scaffolds wrap results in.

    Gemini CLI returns tool results as JSON envelopes; showing the wrapped
    JSON to the auditor is noisy. Returns the unwrapped output when the shape
    is obvious, otherwise the raw content.
    """
    s = content.strip()
    if not (s.startswith("{") and s.endswith("}")):
        return content
    try:
        parsed = json.loads(s)
    except (json.JSONDecodeError, ValueError):
        return content
    if not isinstance(parsed, dict):
        return content
    for key in ("output", "content", "result"):
        if key in parsed:
            return str(parsed[key])
    return content


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
