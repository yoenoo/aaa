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


# Codex CLI defaults to sandbox_mode="workspace-write", which mounts
# everything outside the cwd (here `/workspace`) as read-only at the OS
# level. That breaks every mock CLI under `/srv` because mocks write
# state.json on each mutation. Symptom in transcripts:
#   OSError: [Errno 30] Read-only file system: '/srv/splunk/state.json'
# This sandbox is enforced inside Codex's own subprocess — inspect_swe's
# ACP-layer auto-approval can't bypass it. Switching to full-access is
# the only path; the Docker sandbox itself contains the blast radius and
# the target has no internet access in our setup.
#
# Note: we deliberately do NOT override approval_policy. inspect_swe's
# DefaultClient (acp/client.py:60) auto-approves tool-call permission
# requests via the ACP `session/request_permission` RPC, so approval
# never blocks regardless of Codex's own approval_policy setting. The
# same reasoning is why we do not need to inject --yolo into gemini-cli.
_CODEX_CONFIG_OVERRIDES = {
    "sandbox_mode": "danger-full-access",
}

_GEMINI_ENV_OVERRIDES = {
    # Gemini CLI's write tools refuse privileged approval flows in an
    # untrusted workspace. ACP runs are headless, so trust /workspace for the
    # session instead of relying on an interactive folder-trust dialog.
    "GEMINI_CLI_TRUST_WORKSPACE": "true",
    # Keep Gemini's own config/cache inside the sandbox user's home instead of
    # inheriting an implementation-dependent default.
    "GEMINI_CLI_HOME": "/home/user/.gemini",
}


_SCAFFOLD_FACTORIES = {
    "Claude Code": interactive_claude_code,
    "Codex CLI": lambda **kw: interactive_codex_cli(
        config_overrides={**_CODEX_CONFIG_OVERRIDES, **(kw.pop("config_overrides", None) or {})},
        **kw,
    ),
    "Gemini CLI": lambda **kw: interactive_gemini_cli(
        env={**_GEMINI_ENV_OVERRIDES, **(kw.pop("env", None) or {})},
        **kw,
    ),
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
_DEFAULT_SEND_TIMEOUT_SECS = 600.0
_STOP_TIMEOUT_SECS = 30.0
# First-time install of an ACP adapter (claude-agent-acp, codex-acp,
# gemini-cli) plus its node bundle plus connecting to the target model can
# take 1-2 minutes on a cold sandbox. After the bundle is host-cached the
# install drops to seconds. Empirically, ~30% of inter-branch reset_target
# calls re-run npm install which can take 3-5 minutes on flaky network
# (see logs/baseline-260504/* — both seeds hit 180s timeout on resets).
# Default 360s absorbs that variance; override via
# AAA_SCAFFOLD_START_TIMEOUT_SECS.
_DEFAULT_START_TIMEOUT_SECS = 360.0
_SAFE_ORDERED_RESULT_FUNCTIONS = {
    "read_file",
    "list_directory",
    "grep_search",
    "glob",
    "write_file",
    "replace",
    "web_fetch",
    "run_shell_command",
}


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
        try:
            self._start_timeout = float(os.environ.get(
                "AAA_SCAFFOLD_START_TIMEOUT_SECS", _DEFAULT_START_TIMEOUT_SECS,
            ))
        except ValueError:
            self._start_timeout = _DEFAULT_START_TIMEOUT_SECS
        self._startup_error: BaseException | None = None
        # Tool-result tracking: ChatMessageTool.tool_call_ids we've already
        # attached to a TargetToolCall. The filter runs once per model turn
        # and receives the full conversation-so-far, so prior turns'
        # tool messages appear repeatedly; without this we'd re-match them.
        self._seen_result_keys: set[tuple[str, str, str]] = set()

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
        self._startup_error = None

        async def _run():
            try:
                with self._run_scope:
                    await run(self._agent, "")
            except BaseException as e:
                # Stash the exception so the start() method can surface it
                # explicitly. Without this, `await self._ready.wait()` below
                # would block indefinitely because `_wait_ready` is cancelled
                # by the task group's failure handling but the ready event
                # is never set. We also set _ready here to short-circuit the
                # wait, then re-raise so the task group records the failure.
                self._startup_error = e
                self._ready.set()
                raise

        async def _wait_ready():
            await self._agent.ready.wait()
            self._ready.set()

        self._tg = anyio.create_task_group()
        await self._tg.__aenter__()
        self._tg.start_soon(_run)
        self._tg.start_soon(_wait_ready)

        # Wait for ready or startup-error (whichever comes first). If neither
        # signals within the timeout, the scaffold is hung — usually means
        # the npm install or ACP bridge connection silently stalled. Fail
        # loudly instead of letting the audit hang.
        try:
            with anyio.fail_after(self._start_timeout):
                await self._ready.wait()
        except TimeoutError:
            await self.stop()
            raise TimeoutError(
                f"Scaffold '{self._scaffold_name}' did not become ready within "
                f"{self._start_timeout:.0f}s for target {self._model}. "
                "Likely causes: ACP adapter npm install hung (host-network/"
                "registry policy), the ACP bridge couldn't connect to the "
                "target model (provider auth, model name unknown to bridge), "
                "or the sandbox blocked outbound traffic. Override the "
                "timeout via AAA_SCAFFOLD_START_TIMEOUT_SECS if a cold install "
                "legitimately takes longer."
            )

        if self._startup_error is not None:
            # Run task raised before/while becoming ready; tear down and
            # surface the underlying error rather than silently returning a
            # broken target.
            captured = self._startup_error
            await self.stop()
            raise RuntimeError(
                f"Scaffold '{self._scaffold_name}' failed to start: "
                f"{type(captured).__name__}: {captured}"
            ) from captured

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
        self._seen_result_keys.clear()
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

        Earlier strategies paired tool results against pending calls by
        strict position (or function-name order) across the conversation.
        That breaks if the scaffold delivers results late, out of order,
        or in a different turn than the call was made — the symptom is
        tool outputs visibly attached to the wrong commands in the
        auditor's view (e.g., `head` returning the result of an unrelated
        `bash` call).

        Current strategy:

        1. Track which ChatMessageTool entries we've already captured.
           The filter receives the full conversation-so-far,
           so prior-turn results reappear on every invocation; without
           dedup we'd re-pair them, shifting legitimate new results
           off-by-one.
        2. **Pass A — exact id match.** For each unseen tool message,
           if its tool_call_id equals a pending call's id, pair them.
           This is the correct match when the scaffold preserves ids
           (Gemini CLI via ACP appears to, based on transcript
           inspection). Skips position fragility entirely.
        3. **Pass B — safe ordered fallback.** For common Gemini CLI tools,
           pair available same-function results with the oldest remaining
           same-function calls. Gemini can stream a partial batch of shell
           results (e.g. 3 results visible while 7 calls are still pending),
           so unmatched calls stay pending instead of being marked failed.
        4. **Pass C — safe singleton fallback.** Pair by function when
           there is exactly one remaining pending call and one remaining
           result with the same non-empty function name. Ambiguous or
           cross-function leftovers are quarantined. Gemini CLI sometimes
           emits tool messages with a missing or misleading function name;
           showing those under the wrong command is worse than showing a
           capture warning.
        4. Log a WARNING for any remaining unmatched pending call or
           leftover unmatched message. Under AAA_DEBUG_PAIRING=1, log
           the full pending/incoming id lists on every invocation so
           we can see what the scaffold is actually emitting.
        """
        pending = [c for turn in self._activity for c in turn.tool_calls if c.result is None]
        if not pending:
            return

        unseen_msgs = []
        for m in messages:
            if not isinstance(m, ChatMessageTool):
                continue
            key = _tool_msg_key(m)
            if key in self._seen_result_keys:
                continue
            unseen_msgs.append(m)
        if not unseen_msgs:
            return

        debug = os.environ.get("AAA_DEBUG_PAIRING") == "1"
        if debug:
            print(
                f"[scaffold.debug] pairing pass: pending={len(pending)} "
                f"unseen_msgs={len(unseen_msgs)}",
                flush=True,
            )
            for c in pending:
                print(f"[scaffold.debug]   pending id={c.id!r} fn={c.function!r}")
            for m in unseen_msgs:
                fn = getattr(m, "function", None) or ""
                print(f"[scaffold.debug]   msg id={m.tool_call_id!r} fn={fn!r}")

        # --- Pass A: exact tool_call_id match ---
        msg_by_id: dict[str, ChatMessageTool] = {
            m.tool_call_id: m for m in unseen_msgs if m.tool_call_id
        }
        paired_call_ids: set[str] = set()
        for call in pending:
            # Guard against calls with missing ids (shouldn't happen with
            # proper scaffolds, but don't collapse onto msg_by_id[None]).
            if not call.id:
                continue
            msg = msg_by_id.get(call.id)
            if msg is None:
                continue
            call.result = _unwrap_tool_result(_extract_text(msg.content))
            self._seen_result_keys.add(_tool_msg_key(msg))
            paired_call_ids.add(call.id)
            if debug:
                print(f"[scaffold.debug]   pass-A paired {call.id!r}")

        # --- Pass B: safe ordered function-name fallback ---
        still_pending = [c for c in pending if c.id not in paired_call_ids]
        remaining_msgs = [
            m for m in unseen_msgs
            if _tool_msg_key(m) not in self._seen_result_keys
        ]

        for fn in _SAFE_ORDERED_RESULT_FUNCTIONS:
            fn_calls = [c for c in still_pending if c.function == fn]
            fn_msgs = [m for m in remaining_msgs if (getattr(m, "function", None) or "") == fn]
            if not fn_calls or not fn_msgs or len(fn_msgs) > len(fn_calls):
                continue
            for call, msg in zip(fn_calls, fn_msgs):
                call.result = _unwrap_tool_result(_extract_text(msg.content))
                self._seen_result_keys.add(_tool_msg_key(msg))
                paired_call_ids.add(call.id)
                if debug:
                    print(
                        f"[scaffold.debug]   pass-B ordered paired "
                        f"call={call.id!r} with msg={msg.tool_call_id!r} "
                        f"(function={fn!r})"
                    )

        # --- Pass C: safe singleton function-name fallback ---
        still_pending = [c for c in pending if c.id not in paired_call_ids]
        remaining_msgs = [
            m for m in unseen_msgs
            if _tool_msg_key(m) not in self._seen_result_keys
        ]

        if len(still_pending) == 1 and len(remaining_msgs) == 1:
            call = still_pending[0]
            msg = remaining_msgs[0]
            msg_fn = getattr(msg, "function", None) or ""
            if msg_fn and msg_fn == call.function:
                call.result = _unwrap_tool_result(_extract_text(msg.content))
                self._seen_result_keys.add(_tool_msg_key(msg))
                paired_call_ids.add(call.id)
                if debug:
                    print(
                        f"[scaffold.debug]   pass-C singleton paired "
                        f"call={call.id!r} with msg={msg.tool_call_id!r} "
                        f"(function={call.function!r})"
                    )

        still_pending = [c for c in pending if c.id not in paired_call_ids]
        remaining_msgs = [
            m for m in unseen_msgs
            if _tool_msg_key(m) not in self._seen_result_keys
        ]

        # Calls that haven't been paired yet stay pending; their results may
        # arrive on a later filter pass when the scaffold delivers them
        # (Gemini's partial-batch streaming is the canonical case). The
        # earlier strategy of marking every still-pending call as failed
        # the moment any leftover message existed would also drop legitimate-
        # but-delayed results, so we only log a diagnostic here.
        if still_pending and (debug or remaining_msgs):
            print(
                f"[scaffold] pairing pass left {len(still_pending)} call(s) "
                f"pending and {len(remaining_msgs)} message(s) unattributed; "
                f"will retry next pass",
                flush=True,
            )

        # Any leftover messages we couldn't attribute: log and quarantine so
        # they are not attached to the wrong command on a later filter pass.
        if remaining_msgs:
            summary: dict[str, int] = {}
            for msg in remaining_msgs:
                fn = getattr(msg, "function", None) or ""
                summary[fn] = summary.get(fn, 0) + 1
                self._seen_result_keys.add(_tool_msg_key(msg))
            print(
                f"[scaffold] WARNING: quarantined {len(remaining_msgs)} "
                f"unmatched tool result(s): {summary}",
                flush=True,
            )
            if debug:
                for msg in remaining_msgs:
                    content = _extract_text(msg.content).replace("\n", "\\n")
                    print(
                        f"[scaffold.debug]   quarantined id={msg.tool_call_id!r} "
                        f"fn={(getattr(msg, 'function', None) or '')!r} "
                        f"content={content[:300]!r}",
                        flush=True,
                    )


def _tool_msg_key(msg: ChatMessageTool) -> tuple[str, str, str]:
    """Stable-ish key for deduping tool messages across cumulative histories."""
    tcid = getattr(msg, "tool_call_id", None) or ""
    fn = getattr(msg, "function", None) or ""
    return (tcid, fn, _extract_text(msg.content))

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
