"""Generate Petri-native synthetic trajectories without scoring them."""

from pathlib import Path

from inspect_ai import Task, task
from inspect_petri import (
    audit_solver,
    auditor_agent,
    auditor_tools,
    seeds_dataset,
    target_agent,
)


SEEDS_DIR = Path(__file__).resolve().with_name("petri_seeds")


def resolve_seed_directory(seed_dir: str | None) -> Path:
    # Inspect changes cwd to the task's directory. Resolve relative CLI paths
    # against the repository, and reject typos before Petri treats them as prose.
    path = Path(seed_dir) if seed_dir else SEEDS_DIR
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[2] / path
    if not path.is_dir() or not any(path.glob("*.md")):
        raise ValueError(f"Expected a populated prose seed directory: {path}")
    return path.resolve()


@task
def petri_trajectories(
    max_turns: int = 30,
    realism_filter: float = 0.6,
    seed_dir: str | None = None,
) -> Task:
    """Generate trajectories with an auditor-simulated Petri environment.

    Args:
        max_turns: Maximum number of auditor/target turns per seed.
        realism_filter: Minimum realism score for target-facing auditor actions.
        seed_dir: Optional prose-only dataset directory; defaults to the initial pilot.
    """
    return Task(
        dataset=seeds_dataset(str(resolve_seed_directory(seed_dir))),
        solver=audit_solver(
            auditor=auditor_agent(
                max_turns=max_turns,
                tools=auditor_tools(
                    prefill=False,
                    rollback=True,
                    target_tools="synthetic",
                ),
                realism_filter=realism_filter,
                target_display_name="the deployed assistant",
            ),
            target=target_agent(),
            audit_name="aaa-vs-petri-trajectories",
        ),
        scorer=None,
        name="petri_trajectories",
        metadata={
            "experiment": "aaa-vs-petri",
            "condition": "petri-native-synthetic",
            "inspect_petri_version": "3.1.0",
            "realism_scoring": False,
        },
    )
