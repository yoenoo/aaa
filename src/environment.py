"""Git-based sandbox checkpointing.

Provides checkpoint/restore primitives backed by git inside the Docker sandbox.
Used by the solver to snapshot the seed state after provisioning, and by
reset_target to restore the sandbox to a clean state between branches.
"""

from __future__ import annotations

from inspect_ai.util import SandboxEnvironment

WORKDIR = "/workspace"


_SAFE = f'-c safe.directory={WORKDIR}'


async def _git(sb: SandboxEnvironment, args: str) -> str:
    result = await sb.exec(
        ["bash", "-c", f"git {_SAFE} -C {WORKDIR} {args}"], timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git command failed (exit {result.returncode}): git {args}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return result.stdout


async def checkpoint(sb: SandboxEnvironment, tag: str) -> None:
    """Snapshot the sandbox filesystem at /workspace under the given tag.

    Idempotent: re-running with the same tag force-updates the tag to the
    current state. Sets git config if needed.
    """
    has_git = await sb.exec(["bash", "-c", f"test -d {WORKDIR}/.git"], timeout=5)
    if has_git.returncode != 0:
        init = await sb.exec(["bash", "-c", f"git init {WORKDIR}"], timeout=10)
        if init.returncode != 0:
            raise RuntimeError(f"git init failed: {init.stderr}")
        await _git(sb, 'config user.email "petri@local"')
        await _git(sb, 'config user.name "petri"')

    await _git(sb, "add -A")
    await _git(sb, f'commit --allow-empty -q -m "checkpoint: {tag}"')
    await _git(sb, f"tag -f {tag}")


async def restore(sb: SandboxEnvironment, tag: str) -> None:
    """Restore the sandbox filesystem at /workspace to the given tag.

    Restores tracked files to their tagged state and removes untracked files.
    Raises ValueError if the tag does not exist.
    """
    tags = await _git(sb, f"tag -l {tag}")
    if not tags.strip():
        raise ValueError(f"Checkpoint tag '{tag}' not found in sandbox")

    await _git(sb, f"reset --hard {tag}")
    await _git(sb, "clean -fdx")
