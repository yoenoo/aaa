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

from prompts import load_scaffold_information, load_system_prompt, load_user_message
from runtime.scaffold import ScaffoldRuntime
from seeds.metadata import Seed, parse_seed_tools
from tools import make_tools


@solver
def petri_solver(seed: Seed, runtime_type: str = "scaffold"):
    """Solver that runs an auditor against a target.

    Supports scaffold (ACP) and bare model runtimes behind
    a unified TargetRuntime interface.
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

        # TODO: checkpoint("seed") once environment.py is wired

        # -- create target runtime --
        if runtime_type == "scaffold":
            scaffold_name = "Claude Code"
            target = ScaffoldRuntime(model=target_model)
        elif runtime_type == "bare":
            from runtime.bare import BareModelRuntime
            scaffold_name = "bare"
            seed_tools = parse_seed_tools(seed.required_tools) if seed.required_tools else None
            target = BareModelRuntime(model=target_model, sandbox=sb, seed_tools=seed_tools)
        else:
            raise ValueError(f"Unknown runtime type: {runtime_type}")

        # -- build auditor messages --
        system_prompt = load_system_prompt().format(
            target_model=str(target_model),
            scaffold_name=scaffold_name,
            scaffold_information=load_scaffold_information(scaffold_name),
            seed_instructions=seed.instruction,
            today_date=datetime.now().strftime("%Y-%m-%d"),
        )
        user_msg = load_user_message().format(
            target_model=str(target_model),
            scaffold_name=scaffold_name,
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
                        content=str(result), tool_call_id=tc.id,
                    ))

                if control["action"] == "end":
                    break
        finally:
            await target.stop()

        # Store transcript in state for scorer
        state.messages = auditor_msgs
        return state

    return solve
