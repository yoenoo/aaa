"""Petri solver: orchestrates auditor, target runtime, and environment."""

from __future__ import annotations

from datetime import datetime

from inspect_ai.model import (
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
    get_model,
)
from inspect_ai.solver import Generate, TaskState, solver
from inspect_ai.util import sandbox

from environment import checkpoint
from prompts import load_scaffold_information, load_system_prompt, load_user_message
from runtime.scaffold import ScaffoldRuntime
from seeds.metadata import Seed, parse_seed_tools
from tools import make_tools


_SCAFFOLD_TARGETS = {"Claude Code", "Codex CLI", "Gemini CLI"}


@solver
def petri_solver(seed: Seed, target_name: str, expose_reasoning: bool = False):
    """Solver that runs an auditor against a target.

    Args:
        seed: Seed to audit against.
        target_name: "Claude Code", "Codex CLI", "Gemini CLI", or "bare".
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
        for path, content in seed.setup_files.items():
            parent = "/".join(path.split("/")[:-1])
            if parent:
                await sb.exec(["mkdir", "-p", parent], timeout=10)
            await sb.write_file(path, content)

        await checkpoint(sb, "seed")

        # -- create target runtime --
        if target_name in _SCAFFOLD_TARGETS:
            target = ScaffoldRuntime(
                model=target_model,
                scaffold_name=target_name,
                expose_reasoning=expose_reasoning,
            )
        elif target_name == "bare":
            from runtime.bare import BareModelRuntime
            seed_tools = parse_seed_tools(seed.required_tools) if seed.required_tools else None
            target = BareModelRuntime(
                model=target_model,
                sandbox=sb,
                seed_tools=seed_tools,
                expose_reasoning=expose_reasoning,
            )
        else:
            raise ValueError(f"Unknown target '{target_name}'. Use one of: {', '.join(_SCAFFOLD_TARGETS)}, bare")

        # -- build auditor messages --
        system_prompt = load_system_prompt().format(
            target_model=str(target_model),
            scaffold_name=target_name,
            scaffold_information=load_scaffold_information(target_name),
            seed_instructions=seed.instruction,
            today_date=datetime.now().strftime("%Y-%m-%d"),
        )
        user_msg = load_user_message().format(
            target_model=str(target_model),
            scaffold_name=target_name,
            seed_instructions=seed.instruction,
        )

        auditor_msgs = [
            ChatMessageSystem(content=system_prompt),
            ChatMessageUser(content=user_msg),
        ]

        control = {"action": None}
        tools, tool_map = make_tools(target, sb, control)

        # -- start target --
        await target.start()

        # -- auditor loop --
        max_turns = seed.metadata.max_model_turns
        try:
            for _ in range(max_turns):
                output = await auditor_model.generate(auditor_msgs, tools=tools)
                auditor_msgs.append(output.message)

                if not output.message.tool_calls:
                    auditor_msgs.append(ChatMessageUser(
                        content="Please use one of your tools to proceed.",
                    ))
                    continue

                for tc in output.message.tool_calls:
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
