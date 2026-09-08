"""Inspect task definitions for petri audits."""

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import Scorer

import hooks  # noqa: F401 — registers the post-task viewer dump hook
from runtime._modal_fs_patch import apply as _apply_modal_fs_patch
from scorer import (
    debug_judge,
    debug_judge_v2,
    debug_judge_v3,
    legacy_judge,
    scheming_judge,
    scheming_judge_v2,
    scheming_judge_v3,
)
from seeds import list_seeds, load_seed
from solver import petri_solver

# Modal removed the legacy Sandbox filesystem API that inspect_sandboxes still
# calls; rebind its Modal provider onto the new sandbox.filesystem API so Modal
# audits can provision setup_files. No-op on local Docker. See the shim module.
_apply_modal_fs_patch()


def _pick_scorers(judge_preset: str) -> list[Scorer]:
    """Map a preset name to the list of scorers that run on each sample.

    Presets:
      - "v3" / "scheming_v3+debug_v3" — calibrated structured judges (default):
        34 behavior + 14 audit-quality dims, each with applicability and
        validated evidence citations over the complete recorded audit
      - "v2" / "scheming_v2+debug_v2" — strict XML judges (opt-in)
      - "scheming"       — v1 alignment-only judge (31 dims)
      - "debug"          — v1 audit/infra-only judge (9 dims)
      - "scheming+debug" — both v1 judges run independently
      - "legacy"         — original 17-dim judge, for reproducibility
    """
    match judge_preset:
        case "v3" | "scheming_v3+debug_v3":
            return [scheming_judge_v3(), debug_judge_v3()]
        case "scheming":
            return [scheming_judge()]
        case "debug":
            return [debug_judge()]
        case "scheming+debug":
            return [scheming_judge(), debug_judge()]
        case "legacy":
            return [legacy_judge()]
        case "v2" | "scheming_v2+debug_v2":
            return [scheming_judge_v2(), debug_judge_v2()]
        case _:
            raise ValueError(
                f"Unknown judge_preset {judge_preset!r}. "
                "Expected: v3, v2, scheming, debug, scheming+debug, legacy."
            )


@task
def petri_task(
    seed_name: str = "as-hidden-soar",
    scaffold: str = "Claude Code",
    expose_reasoning: bool = False,
    judge_preset: str = "v3",
) -> Task:
    """Create an inspect Task for a single seed.

    Args:
        seed_name: Active seed id returned by ``seeds.list_seeds()``.
        scaffold: "Claude Code", "Codex CLI", "Gemini CLI", or "bare".
        expose_reasoning: If True, forward the target's internal reasoning
            (or provider-returned summary) back to the auditor via
            query_target. Default False keeps audits realistic — the auditor
            sees only what an outside observer would see.
        judge_preset: Which judges to run — "v3" (default: the calibrated
            structured scheming_v3 + debug_v3 judges), "v2", "scheming",
            "debug", "scheming+debug" (v1 pair), or "legacy".
            See _pick_scorers for details.
    """
    seed = load_seed(seed_name)

    return Task(
        dataset=[Sample(input=seed.instruction, id=seed_name)],
        solver=petri_solver(
            seed=seed,
            scaffold=scaffold,
            expose_reasoning=expose_reasoning,
        ),
        scorer=_pick_scorers(judge_preset),
        sandbox=seed.sandbox,
    )
