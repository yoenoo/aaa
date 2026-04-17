"""Inspect task definitions for petri audits."""

from inspect_ai import Task, task
from inspect_ai.dataset import Sample

import hooks  # noqa: F401 — registers the post-task viewer dump hook
from scorer import alignment_judge
from seeds import list_seeds, load_seed
from solver import petri_solver


@task
def petri_task(
    seed_name: str = "sc-oversight-code-review",
    target_name: str = "Claude Code",
) -> Task:
    """Create an inspect Task for a single seed.

    Args:
        seed_name: Name of the seed (stem of the .yaml file).
        target_name: "Claude Code", "Codex CLI", "Gemini CLI", or "bare".
    """
    seed = load_seed(seed_name)

    return Task(
        dataset=[Sample(input=seed.instruction, id=seed_name)],
        solver=petri_solver(seed=seed, target_name=target_name),
        scorer=alignment_judge(),
        sandbox=seed.sandbox,
    )
