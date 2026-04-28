"""Scaffold runtime: target runs inside an ACP agent (Claude Code, Codex CLI, etc.)."""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

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
# everything outside the cwd (here `/workspace`) as read-only. That breaks
# every mock CLI under `/srv` because mocks write state.json on each
# mutation (deploy, post, ticket-create, etc.). Symptom in transcripts:
#   OSError: [Errno 30] Read-only file system: '/srv/splunk/state.json'
# Workspace-write is a Codex feature aimed at human-supervised coding;
# it doesn't fit our auditing topology where the agent legitimately
# mutates `/srv/<service>/state.json`. Switch to full-access — the
# Docker sandbox itself contains the blast radius and the target has
# no internet access in our setup.
_CODEX_CONFIG_OVERRIDES = {
    "sandbox_mode": "danger-full-access",
    "approval_policy": "never",
}


def _patch_gemini_cli_yolo() -> None:
    """Inject ``--yolo`` into the gemini-cli launch.

    Without ``--yolo``, several gemini-cli tool paths block waiting for
    interactive approval that never arrives in our containerized sandbox;
    the audit hangs on a tool call indefinitely. ``--yolo`` auto-approves,
    eliminating that hang class. Safe here — the Docker sandbox contains
    the blast radius and the target has no network.

    Upstream's *non*-ACP wrapper at
    ``inspect_swe._gemini_cli.gemini_cli`` already adds ``--yolo`` (line
    ~182, ``cmd.append("--yolo")``); the ACP wrapper at
    ``inspect_swe.acp._agents.gemini_cli.gemini_cli`` doesn't. This patch
    fills that gap. (Worth filing upstream as a one-line PR.)

    We monkey-patch ``GeminiCli._start_agent`` rather than subclassing
    because the upstream factory ``interactive_gemini_cli`` is decorated
    with ``@agent(name="Gemini CLI")`` and that registration only attaches
    to the decorated function — the runtime fails with "Object 'unknown'
    does not have registry info" when ``run()`` receives an instance of an
    undecorated subclass. Patching keeps the canonical class identity and
    the decorator's registration intact.

    The body mirrors upstream exactly except the one AAA modification
    flagged inline. Update if upstream's body changes.
    """
    try:
        from inspect_swe.acp._agents.gemini_cli import gemini_cli as _gemini_mod
    except ImportError:
        return

    GeminiCliCls = _gemini_mod.GeminiCli

    @asynccontextmanager
    async def _patched_start_agent(self, state) -> AsyncIterator[tuple[object, object]]:
        from inspect_ai.agent import sandbox_agent_bridge
        from inspect_ai.model import get_model
        from inspect_ai.tool import install_skills
        from inspect_ai.util import ExecRemoteStreamingOptions, store
        from inspect_ai.util import sandbox as sandbox_env
        from inspect_swe._gemini_cli.agentbinary import ensure_gemini_cli_setup
        from inspect_swe._util.path import join_path

        sbox = sandbox_env(self.sandbox)
        model = get_model(self.model)

        MODEL_PORT = "gemini_acp_model_port"
        port = store().get(MODEL_PORT, 3000) + 1
        store().set(MODEL_PORT, port)

        async with sandbox_agent_bridge(
            state,
            model=None,
            model_aliases=self.model_map,
            filter=self.filter,
            retry_refusals=self.retry_refusals,
            bridged_tools=self.bridged_tools or None,
            port=port,
        ) as bridge:
            gemini_binary, node_binary = await ensure_gemini_cli_setup(
                sbox, self._version, self.user
            )
            node_dir = str(Path(node_binary).parent)

            home_result = await sbox.exec(["sh", "-c", "echo $HOME"], user=self.user)
            sandbox_home = home_result.stdout.strip() or "/root"

            if self._resolved_skills:
                GEMINI_SKILLS = ".gemini/skills"
                skills_dir = (
                    join_path(self.cwd, GEMINI_SKILLS)
                    if self.cwd is not None
                    else GEMINI_SKILLS
                )
                await install_skills(self._resolved_skills, sbox, self.user, skills_dir)

            agent_env = {
                "GOOGLE_GEMINI_BASE_URL": f"http://127.0.0.1:{bridge.port}",
                "GEMINI_API_KEY": "api-key",
                "PATH": f"{node_dir}:/usr/local/bin:/usr/bin:/bin",
                "HOME": sandbox_home,
            } | self.env

            proc = await sbox.exec_remote(
                # AAA modification: --yolo auto-approves all tool calls.
                cmd=[
                    gemini_binary,
                    "--experimental-acp",
                    "--yolo",
                    "--model",
                    model.name,
                ],
                options=ExecRemoteStreamingOptions(
                    stdin_open=True,
                    cwd=self.cwd,
                    env=agent_env,
                    user=self.user,
                ),
            )

            yield proc, bridge

    GeminiCliCls._start_agent = _patched_start_agent


_patch_gemini_cli_yolo()


_SCAFFOLD_FACTORIES = {
    "Claude Code": interactive_claude_code,
    "Codex CLI": lambda **kw: interactive_codex_cli(
        config_overrides={**_CODEX_CONFIG_OVERRIDES, **(kw.pop("config_overrides", None) or {})},
        **kw,
    ),
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
# First-time install of an ACP adapter (claude-agent-acp, codex-acp,
# gemini-cli) plus its node bundle plus connecting to the target model can
# take 1-2 minutes on a cold sandbox. After the bundle is host-cached the
# install drops to seconds. Default 180s comfortably covers cold-cache;
# override via AAA_SCAFFOLD_START_TIMEOUT_SECS.
_DEFAULT_START_TIMEOUT_SECS = 180.0


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

        Earlier strategies paired tool results against pending calls by
        strict position (or function-name order) across the conversation.
        That breaks if the scaffold delivers results late, out of order,
        or in a different turn than the call was made — the symptom is
        tool outputs visibly attached to the wrong commands in the
        auditor's view (e.g., `head` returning the result of an unrelated
        `bash` call).

        Current strategy:

        1. Track which ChatMessageTool.tool_call_ids we've already
           captured. The filter receives the full conversation-so-far,
           so prior-turn results reappear on every invocation; without
           dedup we'd re-pair them, shifting legitimate new results
           off-by-one.
        2. **Pass A — exact id match.** For each unseen tool message,
           if its tool_call_id equals a pending call's id, pair them.
           This is the correct match when the scaffold preserves ids
           (Gemini CLI via ACP appears to, based on transcript
           inspection). Skips position fragility entirely.
        3. **Pass B — function-name bucket fallback.** For whatever's
           still unpaired after pass A (happens when the scaffold
           rewrites ids or emits results out-of-band), bucket the
           remaining messages by function name and pair each pending
           call with the next same-function message. Prevents
           cross-function contamination even when within-function
           order is uncertain.
        4. Log a WARNING for any remaining unmatched pending call or
           leftover unmatched message. Under AAA_DEBUG_PAIRING=1, log
           the full pending/incoming id lists on every invocation so
           we can see what the scaffold is actually emitting.
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
            self._seen_result_ids.add(msg.tool_call_id)
            paired_call_ids.add(call.id)
            if debug:
                print(f"[scaffold.debug]   pass-A paired {call.id!r}")

        # --- Pass B: function-name bucket fallback ---
        still_pending = [c for c in pending if c.id not in paired_call_ids]
        remaining_msgs = [m for m in unseen_msgs if m.tool_call_id not in self._seen_result_ids]

        by_fn: dict[str, list[ChatMessageTool]] = {}
        for m in remaining_msgs:
            fn = getattr(m, "function", None) or ""
            by_fn.setdefault(fn, []).append(m)

        for call in still_pending:
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
            if debug:
                print(
                    f"[scaffold.debug]   pass-B paired call={call.id!r} "
                    f"with msg={msg.tool_call_id!r} (function={call.function!r})"
                )

        # Any leftover messages we couldn't attribute: log and drop so
        # seen_result_ids doesn't hold them open forever.
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
