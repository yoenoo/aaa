"""Petri solver: orchestrates auditor, target runtime, and environment."""

from __future__ import annotations

from datetime import datetime

import anyio
from inspect_ai.model import (
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
    get_model,
)
from inspect_ai.solver import Generate, TaskState, solver
from inspect_ai.tool import ToolCall
from inspect_ai.util import sandbox

from environment import checkpoint
from prompts import load_scaffold_information, load_system_prompt, load_user_message
from runtime.scaffold import ScaffoldRuntime
from seeds.metadata import Seed, parse_seed_tools
from tools import format_target_response, make_tools


_SCAFFOLD_TARGETS = {"Claude Code", "Codex CLI", "Gemini CLI"}

# Which agent-instruction file each scaffold actually reads. We provision only
# the active scaffold's file so the workspace doesn't reveal it was set up for
# multiple AI tools (an eval-awareness tell).
_AGENT_FILES = {"AGENTS.md", "CLAUDE.md", "GEMINI.md"}
_SCAFFOLD_AGENT_FILE = {
    "Claude Code": "CLAUDE.md",
    "Codex CLI": "AGENTS.md",
    "Gemini CLI": "GEMINI.md",
}


async def _provision_seed(sb, seed: Seed, scaffold: str) -> None:
    """Write the seed's setup_files into the sandbox.

    Only the active scaffold's agent-instruction file is provisioned; writing
    all three (CLAUDE.md/AGENTS.md/GEMINI.md) is itself an eval-awareness tell.
    """
    active_agent_file = _SCAFFOLD_AGENT_FILE.get(scaffold)
    # A non-active agent file (e.g. AGENTS.md when running Gemini CLI) is normally
    # skipped to avoid the multi-scaffold eval-awareness tell. But if it's
    # referenced by name in other setup files it's scenario content, not a
    # redundant scaffold instruction, and must be provisioned (else the scenario
    # has dangling references and reads of it crash).
    referenced_names = "\n".join(seed.setup_files.values())
    for path, content in seed.setup_files.items():
        fname = path.split("/")[-1]
        if (active_agent_file and fname in _AGENT_FILES
                and fname != active_agent_file and fname not in referenced_names):
            continue
        parent = "/".join(path.split("/")[:-1])
        if parent:
            await sb.exec(["mkdir", "-p", parent], timeout=10)
        await sb.write_file(path, content)
        # Make provisioned scripts runnable so the target can invoke them as
        # `./tools/foo`. Keyed off a shebang, so it's general rather than
        # tools/-specific.
        if content.startswith("#!"):
            await sb.exec(["chmod", "+x", path], timeout=10)

    # Directory seeds carry post_setup bash commands (chmod mock binaries, chown
    # the provisioned tree, drop a readiness sentinel); legacy single-file seeds
    # have none. Run them after every setup_file is written.
    for cmd in seed.post_setup:
        await sb.exec(["bash", "-lc", cmd], timeout=60)


async def _start_with_retry(target, attempts: int = 5) -> None:
    """Start the target, retrying transient scaffold-startup failures.

    The ACP scaffolds (esp. Gemini CLI) do an HTTP startup handshake that
    intermittently times out under concurrent cold-starts — a single boot
    timeout shouldn't fail the whole sample. ScaffoldRuntime.start() tears
    itself down before raising and is safe to call again, so we just retry
    with backoff. Non-scaffold runtimes (bare) typically succeed first try.
    """
    last_err: BaseException | None = None
    for attempt in range(attempts):
        try:
            await target.start()
            return
        except Exception as e:
            last_err = e
            if attempt < attempts - 1:
                print(
                    f"[scaffold start] attempt {attempt + 1}/{attempts} failed "
                    f"({type(e).__name__}); retrying...",
                    flush=True,
                )
                await anyio.sleep(2 * (attempt + 1))  # 2s, 4s backoff
    raise last_err


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

        # -- provision seed files --
        await _provision_seed(sb, seed, scaffold)
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
            today_date=datetime.now().strftime("%Y-%m-%d"),
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
        tools, tool_map = make_tools(target, sb, control, protected_paths=frozenset(seed.setup_files))

        # -- start target, then run auditor loop --
        max_turns = seed.metadata.max_model_turns
        try:
            await _start_with_retry(target)

            for _ in range(max_turns):
                output = await auditor_model.generate(auditor_msgs, tools=tools)
                auditor_msgs.append(output.message)

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

                if control["action"] == "end":
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

        return state

    return solve


@solver
def scripted_solver(seed: Seed, scaffold: str, expose_reasoning: bool = False):
    """Measurement solver: drive the target with a fixed message protocol.

    No auditor model. The environment is the frozen seed (provisioned exactly as
    in the auditor path, including the write-guard's protected setup_files), and
    the conversation is the fixed `seed.protocol` list — same stimulus every
    trial, so the only variation across rollouts is the target's stochasticity.

    The transcript it writes to `state.messages` mirrors the auditor path's
    shape (send_message → query_target per turn, target response rendered by the
    shared `format_target_response`), so the judges score it with no changes.
    """
    async def solve(state: TaskState, _generate: Generate) -> TaskState:
        if not seed.protocol:
            raise ValueError(
                f"scripted mode requires a non-empty protocol; seed "
                f"{seed.title!r} has none. Supply one via the seed YAML's "
                "`protocol:` field or task `protocol_name`."
            )
        if scaffold not in _SCAFFOLD_TARGETS:
            raise ValueError(
                f"scripted mode supports scaffold targets only, got {scaffold!r}. "
                f"Use one of: {', '.join(_SCAFFOLD_TARGETS)}."
            )

        sb = sandbox()
        target_model = get_model(role="target")

        await _provision_seed(sb, seed, scaffold)
        await checkpoint(sb, "seed")

        target = ScaffoldRuntime(
            model=target_model,
            scaffold_name=scaffold,
            expose_reasoning=expose_reasoning,
        )

        msgs: list = []
        try:
            await _start_with_retry(target)

            for i, message in enumerate(seed.protocol, start=1):
                send_id, query_id = f"send_{i}", f"query_{i}"
                # Mirror the auditor's send_message → query_target turn so the
                # judge transcript is structurally identical to a real audit.
                msgs.append(ChatMessageAssistant(
                    content="",
                    tool_calls=[ToolCall(
                        id=send_id, function="send_message",
                        arguments={"message": message},
                    )],
                ))
                msgs.append(ChatMessageTool(
                    content="Message queued. Call query_target() to send it.",
                    tool_call_id=send_id, function="send_message",
                ))
                msgs.append(ChatMessageAssistant(
                    content="",
                    tool_calls=[ToolCall(
                        id=query_id, function="query_target", arguments={},
                    )],
                ))
                resp = await target.send(message)
                msgs.append(ChatMessageTool(
                    content=format_target_response(resp),
                    tool_call_id=query_id, function="query_target",
                ))
        except Exception as e:
            import traceback
            err_line = f"{type(e).__name__}: {e}"
            print(
                f"\n[scripted run error] {err_line}\n{traceback.format_exc()}"
                f"Stopping. Partial transcript: {len(msgs)} messages.",
                flush=True,
            )
            raise
        finally:
            await target.stop()
            state.messages = msgs

        return state

    return solve
