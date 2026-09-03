"""Petri solver: orchestrates auditor, target runtime, and environment."""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from inspect_ai.model import (
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
    GenerateConfig,
    get_model,
)
from inspect_ai.solver import Generate, TaskState, solver
from inspect_ai.util import sandbox

from environment import checkpoint
from prompts import load_scaffold_information, load_system_prompt, load_user_message
from runtime.scaffold import ScaffoldRuntime
from seeds.metadata import Seed, parse_seed_tools
from tools import make_tools


# Seeds pin their fiction to the *real run date* by writing {{SEED_NOW}} tokens
# instead of hardcoding absolute dates. At provision time we substitute the
# actual run timestamp, so the date the scaffold injects into the target's
# system prompt (the real clock) matches the scenario — nothing for the target
# to flag as "months in the past."
#
#   {{SEED_NOW}}              -> 2026-09-03T16:55:02Z            (ISO 8601 UTC)
#   {{SEED_NOW-2d}}           -> two days before now, ISO 8601
#   {{SEED_NOW+2h|%Y-%m-%d}}  -> two hours after now, custom strftime format
#
# Offset grammar: [+-]<int><unit>, unit in s/m/h/d/w. Optional |<strftime>.
_SEED_NOW_TOKEN = re.compile(r"\{\{SEED_NOW([+-]\d+[smhdw])?(?:\|([^}]+))?\}\}")
_SEED_NOW_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def apply_seed_now(text: str, base: datetime) -> str:
    """Replace {{SEED_NOW[±offset][|fmt]}} tokens in ``text`` using ``base``."""
    def _repl(m: "re.Match[str]") -> str:
        off, fmt = m.group(1), m.group(2)
        t = base
        if off:
            secs = int(off[1:-1]) * _SEED_NOW_UNITS[off[-1]]
            t = base + timedelta(seconds=(-secs if off[0] == "-" else secs))
        return t.strftime(fmt) if fmt else t.strftime("%Y-%m-%dT%H:%M:%SZ")

    return _SEED_NOW_TOKEN.sub(_repl, text)


_SCAFFOLD_TARGETS = {"Claude Code", "Codex CLI", "Gemini CLI"}


def _open_live_stream() -> tuple[Path | None, object | None]:
    """Open a per-run JSONL file that mirrors auditor turn activity.

    inspect_ai's .eval log is only written at completion; on SIGINT or
    crash the whole sample is lost. This stream is an independent,
    flushed-per-line record so partial transcripts survive the process
    dying.

    Location: $AAA_LIVE_DIR (default "logs/live"). Filename:
    live-<ISO-timestamp>-<short-uuid>.jsonl. Disable by setting
    AAA_LIVE_STREAM=0.
    """
    if os.environ.get("AAA_LIVE_STREAM") == "0":
        return None, None
    live_dir = Path(os.environ.get("AAA_LIVE_DIR", "logs/live"))
    try:
        live_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        return None, None
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    path = live_dir / f"live-{stamp}-{uuid.uuid4().hex[:8]}.jsonl"
    try:
        f = path.open("a", buffering=1)  # line-buffered
    except Exception:
        return None, None
    return path, f


def _live_write(stream, record: dict) -> None:
    if stream is None:
        return
    try:
        stream.write(json.dumps(record, default=str) + "\n")
        stream.flush()
    except Exception:
        pass


@solver
def petri_solver(seed: Seed, scaffold: str, expose_reasoning: bool = False):
    """Solver that runs an auditor against a target.

    Args:
        seed: Seed to audit against.
        scaffold: "Claude Code", "Codex CLI", "Gemini CLI", or "bare".
        expose_reasoning: If True, forward the target's internal reasoning
            (or provider-returned summary) back to the auditor via
            query_target. Less realistic (auditor sees more than a real-world
            observer), but gives sharper audit signal.
    """
    async def solve(state: TaskState, _generate: Generate) -> TaskState:
        sb = sandbox()
        auditor_model = get_model()
        target_model = get_model(role="target")

        # -- auditor-model recommendation check (non-fatal) --
        # Seeds may flag auditors that surface the eval frame too readily and
        # de-fang the pressure. Warn rather than block: a mismatched pair can be
        # run intentionally to study the difference.
        auditor_name = str(auditor_model)
        avoid = seed.metadata.avoid_auditor_models
        if avoid and any(a and a in auditor_name for a in avoid):
            rec = seed.metadata.recommended_auditor_model
            print(
                f"[petri] WARNING: auditor model {auditor_name!r} is on this "
                f"seed's avoid_auditor_models list ({avoid})."
                + (f" Recommended auditor: {rec}." if rec else ""),
                file=sys.stderr, flush=True,
            )

        # -- pre-flight: confirm the target model is callable --
        # When a model name is wrong or the project lacks access (404, auth
        # errors), the scaffold's npm CLI inside the sandbox will get the
        # same error and crash, surfacing only as ``ACPError: Connection
        # closed`` after a long Docker setup. Fail fast at the host level
        # so the operator sees the real cause and the audit aborts before
        # touching any sandbox.
        # max_tokens=64 — small enough to be cheap (~1 cent for gpt-5),
        # large enough to fit a reasoning trace + a one-token reply for
        # thinking models. max_tokens=4 fails on Responses-API thinking
        # models because their reasoning eats the budget before any
        # visible output.
        try:
            await target_model.generate(
                input=[ChatMessageUser(content="ping")],
                config=GenerateConfig(max_tokens=64),
            )
        except Exception as e:
            err_line = f"{type(e).__name__}: {str(e)[:400]}"
            raise RuntimeError(
                f"Target model {target_model} pre-flight check failed: "
                f"{err_line}\n\n"
                "This run will not proceed because the scaffold cannot reach "
                "a working target. Common causes: model name typo, the "
                "Vertex/OpenAI project lacks access, API key missing, or "
                "the model has been deprecated. Use a known-good model name."
            ) from e

        # -- scenario anchor: pin the fiction to the REAL run date --
        # Seeds express their timestamps relative to this anchor via
        # {{SEED_NOW}} tokens (see apply_seed_now) rather than hardcoding an
        # absolute past date. The scaffold injects the real clock into the
        # target's system prompt, so anchoring "now" to the real run time keeps
        # the scenario and that injected date consistent — no faking needed.
        seed_now = datetime.now(timezone.utc).replace(microsecond=0)
        seed_now_iso = seed_now.strftime("%Y-%m-%dT%H:%M:%SZ")
        scenario_date = seed_now.strftime("%Y-%m-%d")

        # -- provision seed files (with {{SEED_NOW}} substitution) --
        for path, content in seed.setup_files.items():
            parent = "/".join(path.split("/")[:-1])
            if parent:
                await sb.exec(["mkdir", "-p", parent], timeout=10)
            await sb.write_file(path, apply_seed_now(content, seed_now))

        # -- publish the anchor for the mock CLIs (which read SEED_NOW /
        # /etc/seed-now for deterministic timestamps). Written 0644 so a seed
        # that still sets its own anchor in post_setup can override it. --
        await sb.exec(["bash", "-c",
            "printf '%s\\n' \"$0\" > /etc/seed-now && chmod 0644 /etc/seed-now && "
            "printf 'export SEED_NOW=%s\\n' \"$0\" > /etc/profile.d/seed-now.sh && "
            "chmod 0755 /etc/profile.d/seed-now.sh", seed_now_iso], timeout=10)

        # -- run post-setup commands (same {{SEED_NOW}} substitution) --
        for cmd in seed.post_setup:
            await sb.exec(["bash", "-c", apply_seed_now(cmd, seed_now)], timeout=30)

        # If the seed wrote its own /etc/seed-now (unconverted, hardcoded date),
        # honor it for the auditor's "today" so auditor and sandbox still agree.
        try:
            _sn = await sb.exec(["bash", "-c",
                "cut -c1-10 /etc/seed-now 2>/dev/null"], timeout=10)
            _d = (getattr(_sn, "stdout", "") or "").strip()
            if len(_d) == 10 and _d[:4].isdigit():
                scenario_date = _d
        except Exception:
            pass

        await checkpoint(sb, "seed")

        # -- create target runtime --
        if scaffold in _SCAFFOLD_TARGETS:
            target = ScaffoldRuntime(
                model=target_model,
                scaffold_name=scaffold,
                expose_reasoning=expose_reasoning,
            )
        elif scaffold == "bare":
            from runtime.bare import BareModelRuntime
            seed_tools = parse_seed_tools(seed.required_tools) if seed.required_tools else None
            target = BareModelRuntime(
                model=target_model,
                sandbox=sb,
                seed_tools=seed_tools,
                expose_reasoning=expose_reasoning,
            )
        else:
            raise ValueError(f"Unknown scaffold '{scaffold}'. Use one of: {', '.join(_SCAFFOLD_TARGETS)}, bare")

        # -- build auditor messages --
        system_prompt = load_system_prompt().format(
            target_model=str(target_model),
            scaffold_name=scaffold,
            scaffold_information=load_scaffold_information(scaffold),
            seed_instructions=seed.instruction,
            today_date=scenario_date,
        )
        user_msg = load_user_message().format(
            target_model=str(target_model),
            scaffold_name=scaffold,
            seed_instructions=seed.instruction,
        )

        auditor_msgs = [
            ChatMessageSystem(content=system_prompt),
            ChatMessageUser(content=user_msg),
        ]

        control = {"action": None}
        tools, tool_map = make_tools(target, sb, control)

        # -- start target --
        # Open the live stream BEFORE target.start() so scaffold-startup
        # failures are recorded in the live JSONL too. Also catch the
        # exception so the audit terminates cleanly with a visible error
        # rather than crashing the inspect-ai sample (which would hide the
        # failure cause behind a generic "task failed").
        max_turns = seed.metadata.max_model_turns
        loop_started = time.monotonic()
        live_path, live_stream = _open_live_stream()
        if live_path:
            print(f"[petri] live stream: {live_path}", file=sys.stderr, flush=True)
            _live_write(live_stream, {
                "event": "run_start",
                "at": datetime.now().isoformat(),
                "seed_name": state.sample_id,
                "title": seed.title,
                "scaffold": scaffold,
                "max_turns": max_turns,
            })

        try:
            await target.start()
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            err_line = f"{type(e).__name__}: {e}"
            print(
                f"\n[scaffold start error] {err_line}\n{tb}",
                file=sys.stderr, flush=True,
            )
            _live_write(live_stream, {
                "event": "scaffold_start_error",
                "error": err_line,
                "traceback": tb,
                "scaffold": scaffold,
            })
            # Append a visible error to auditor_msgs so the eval log captures
            # the failure cleanly rather than reporting an empty audit.
            auditor_msgs.append(ChatMessageUser(
                content=(
                    f"[scaffold failed to start: {scaffold}]\n\n{err_line}\n\n"
                    "Audit cannot proceed. See traceback above. Common fixes:\n"
                    "  - For Codex CLI: ensure OPENAI_API_KEY is set.\n"
                    "  - For Gemini CLI: try a different target model "
                    "(gemini-3.1-pro-preview is the known-good default).\n"
                    "  - For Claude Code: ensure ANTHROPIC_API_KEY is set.\n"
                    "  - Any scaffold: a cold sandbox may need a larger "
                    "AAA_SCAFFOLD_START_TIMEOUT_SECS for the first npm install."
                ),
            ))
            state.messages = auditor_msgs
            if live_stream is not None:
                _live_write(live_stream, {
                    "event": "run_end",
                    "at": datetime.now().isoformat(),
                    "total_s": round(time.monotonic() - loop_started, 2),
                    "turns": 0,
                    "abort_reason": "scaffold_start_error",
                })
                try:
                    live_stream.close()
                except Exception:
                    pass
            raise

        # -- auditor loop --
        try:
            for i in range(max_turns):
                turn_start = time.monotonic()
                output = await auditor_model.generate(auditor_msgs, tools=tools)
                auditor_msgs.append(output.message)

                tc_names = [tc.function for tc in output.message.tool_calls or []]
                t_total = time.monotonic() - loop_started
                t_turn = time.monotonic() - turn_start
                print(
                    f"[petri {i+1}/{max_turns} t+{t_total:6.1f}s "
                    f"Δ{t_turn:5.1f}s] "
                    f"auditor: {', '.join(tc_names) or '(no tool calls)'}",
                    file=sys.stderr, flush=True,
                )

                turn_tool_calls_meta = [
                    {"id": tc.id, "function": tc.function,
                     "arguments": tc.arguments}
                    for tc in (output.message.tool_calls or [])
                ]
                _live_write(live_stream, {
                    "event": "auditor_turn",
                    "turn": i + 1,
                    "t_total": round(t_total, 2),
                    "t_turn": round(t_turn, 2),
                    "text": (output.message.text or "")[:5000],
                    "tool_calls": turn_tool_calls_meta,
                })

                if not output.message.tool_calls:
                    auditor_msgs.append(ChatMessageUser(
                        content="Please use one of your tools to proceed.",
                    ))
                    continue

                tc_list = output.message.tool_calls
                reset_parallel = (
                    len(tc_list) > 1
                    and any(tc.function == "reset_target" for tc in tc_list)
                )
                if reset_parallel:
                    # reset_target is a hard branch boundary; mixing it with
                    # siblings makes branch attribution of the siblings' results
                    # ambiguous. Reject the whole turn and let the auditor retry.
                    err = (
                        "Error: reset_target must be called alone, not in "
                        "parallel with other tools. It is a hard branch "
                        "boundary — call it by itself, then make other tool "
                        "calls in the next turn."
                    )
                    for tc in tc_list:
                        auditor_msgs.append(ChatMessageTool(
                            content=err, tool_call_id=tc.id, function=tc.function,
                        ))
                else:
                    for tc in tc_list:
                        fn = tool_map.get(tc.function)
                        result = await fn(**tc.arguments) if fn else f"Unknown tool: {tc.function}"
                        auditor_msgs.append(ChatMessageTool(
                            content=str(result), tool_call_id=tc.id, function=tc.function,
                        ))
                        _live_write(live_stream, {
                            "event": "tool_result",
                            "turn": i + 1,
                            "tool_call_id": tc.id,
                            "function": tc.function,
                            "result": str(result)[:20000],
                        })

                if control["action"] == "end":
                    _live_write(live_stream, {"event": "end_audit", "turn": i + 1})
                    break
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            err_line = f"{type(e).__name__}: {e}"
            print(
                f"\n[audit error] {err_line}\n{tb}"
                f"Stopping audit. Partial transcript: {len(auditor_msgs)} messages.",
                flush=True,
            )
            _live_write(live_stream, {
                "event": "audit_error",
                "error": err_line,
                "traceback": tb,
            })
            # Close any dangling tool_calls from the last assistant turn so the
            # timeline renders cleanly, then append a visible error note.
            last = auditor_msgs[-1] if auditor_msgs else None
            if last and last.role == "assistant" and last.tool_calls:
                answered = {
                    m.tool_call_id for m in auditor_msgs
                    if isinstance(m, ChatMessageTool)
                }
                for tc in last.tool_calls:
                    if tc.id not in answered:
                        auditor_msgs.append(ChatMessageTool(
                            content=f"[tool failed: {err_line}]",
                            tool_call_id=tc.id,
                            function=tc.function,
                        ))
            auditor_msgs.append(ChatMessageUser(
                content=f"[audit stopped due to error]\n\n{err_line}\n\n{tb}",
            ))
            raise
        finally:
            await target.stop()
            state.messages = auditor_msgs
            _live_write(live_stream, {
                "event": "run_end",
                "at": datetime.now().isoformat(),
                "total_s": round(time.monotonic() - loop_started, 2),
                "turns": len([m for m in auditor_msgs if m.role == "assistant"]),
            })
            if live_stream is not None:
                try:
                    live_stream.close()
                except Exception:
                    pass

        return state

    return solve
