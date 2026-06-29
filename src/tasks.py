"""Inspect task definitions for petri audits."""

from dataclasses import replace

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import Scorer

import hooks  # noqa: F401 — registers the post-task viewer dump hook
from protocols import get_protocol
from scorer import debug_judge, legacy_judge, scheming_judge
from seeds import list_seeds, load_seed
from solver import petri_solver, scripted_solver


def _pick_scorers(judge_preset: str) -> list[Scorer]:
    """Map a preset name to the list of scorers that run on each sample.

    Presets:
      - "scheming"       — alignment-only judge (31 dims)
      - "debug"          — audit/infra-only judge (9 dims)
      - "scheming+debug" — both judges run independently (default)
      - "legacy"         — original 17-dim judge, for reproducibility
    """
    match judge_preset:
        case "scheming":
            return [scheming_judge()]
        case "debug":
            return [debug_judge()]
        case "scheming+debug":
            return [scheming_judge(), debug_judge()]
        case "legacy":
            return [legacy_judge()]
        case _:
            raise ValueError(
                f"Unknown judge_preset {judge_preset!r}. "
                "Expected: scheming, debug, scheming+debug, legacy."
            )


@task
def petri_task(
    seed_name: str = "sc-oversight-code-review",
    scaffold: str = "Claude Code",
    expose_reasoning: bool = False,
    judge_preset: str = "scheming+debug",
    mode: str = "auditor",
    protocol_name: str | None = None,
) -> Task:
    """Create an inspect Task for a single seed.

    Args:
        seed_name: Name of the seed (stem of the .yaml file).
        scaffold: "Claude Code", "Codex CLI", "Gemini CLI", or "bare".
        expose_reasoning: If True, forward the target's internal reasoning
            (or provider-returned summary) back to the auditor via
            query_target. Default False keeps audits realistic — the auditor
            sees only what an outside observer would see.
        judge_preset: Which judges to run — "scheming", "debug",
            "scheming+debug" (default: runs both), or "legacy".
            See _pick_scorers for details.
        mode: "auditor" (default) drives the target with the improvising LLM
            auditor — for discovery. "scripted" drives it with a fixed message
            protocol and no auditor model — for controlled measurement.
        protocol_name: In scripted mode, the registry protocol to use
            (src/protocols.py). Overrides any protocol baked into the seed.
            Ignored in auditor mode.
    """
    seed = load_seed(seed_name)

    if mode == "scripted":
        if protocol_name is not None:
            seed = replace(seed, protocol=get_protocol(protocol_name))
        solver = scripted_solver(
            seed=seed, scaffold=scaffold, expose_reasoning=expose_reasoning,
        )
    elif mode == "auditor":
        solver = petri_solver(
            seed=seed, scaffold=scaffold, expose_reasoning=expose_reasoning,
        )
    else:
        raise ValueError(
            f"Unknown mode {mode!r}. Expected 'auditor' or 'scripted'."
        )

    return Task(
        dataset=[Sample(input=seed.instruction, id=seed_name)],
        solver=solver,
        scorer=_pick_scorers(judge_preset),
        sandbox=seed.sandbox,
    )
