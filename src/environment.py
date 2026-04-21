"""Git-based sandbox checkpointing.

Provides checkpoint/restore primitives backed by git inside the Docker sandbox.
Used by the solver to snapshot the seed state after provisioning, and by
reset_target to restore the sandbox to a clean state between branches.

Covers multiple roots (by default /workspace and /srv) — /srv holds mock
service state (gh, splunk, slack, etc.) that directory-structured seeds
provision alongside /workspace. Without /srv-level restore, mock state leaked
across branches on reset_target — an audit that e.g. closed a PR in Branch 1
would see that PR still closed in Branch 2.
"""

from __future__ import annotations

from inspect_ai.util import SandboxEnvironment

WORKDIR = "/workspace"
SRVDIR = "/srv"

DEFAULT_CHECKPOINT_ROOTS: tuple[str, ...] = (WORKDIR, SRVDIR)


def _safe_flag(path: str) -> str:
    return f"-c safe.directory={path}"


async def _git(sb: SandboxEnvironment, root: str, args: str) -> str:
    result = await sb.exec(
        ["bash", "-c", f"git {_safe_flag(root)} -C {root} {args}"], timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git command failed (exit {result.returncode}) at {root}: git {args}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return result.stdout


async def _dir_exists(sb: SandboxEnvironment, path: str) -> bool:
    result = await sb.exec(["bash", "-c", f"test -d {path}"], timeout=5)
    return result.returncode == 0


async def _ensure_git_repo(sb: SandboxEnvironment, root: str) -> None:
    has_git = await sb.exec(["bash", "-c", f"test -d {root}/.git"], timeout=5)
    if has_git.returncode == 0:
        return
    init = await sb.exec(["bash", "-c", f"git init {root}"], timeout=10)
    if init.returncode != 0:
        raise RuntimeError(f"git init failed at {root}: {init.stderr}")
    await _git(sb, root, 'config user.email "petri@local"')
    await _git(sb, root, 'config user.name "petri"')


async def checkpoint(
    sb: SandboxEnvironment,
    tag: str,
    roots: tuple[str, ...] = DEFAULT_CHECKPOINT_ROOTS,
) -> None:
    """Snapshot the sandbox filesystem at each root under ``tag``.

    Idempotent: re-running with the same tag force-updates the tag to the
    current state. Roots that don't exist in the sandbox are skipped silently
    (so the default ``(/workspace, /srv)`` is safe for seeds that only use
    /workspace).
    """
    for root in roots:
        if not await _dir_exists(sb, root):
            continue
        await _ensure_git_repo(sb, root)
        await _git(sb, root, "add -A")
        await _git(sb, root, f'commit --allow-empty -q -m "checkpoint: {tag}"')
        await _git(sb, root, f"tag -f {tag}")


async def restore(
    sb: SandboxEnvironment,
    tag: str,
    roots: tuple[str, ...] = DEFAULT_CHECKPOINT_ROOTS,
) -> None:
    """Restore each root to ``tag``.

    Non-existent roots and roots without the given tag are skipped — this
    keeps the default root tuple robust for seeds that don't provision /srv,
    while still resetting it for those that do.

    Raises ValueError if none of the roots has the requested tag (almost
    always indicates the seed's checkpoint phase didn't run).
    """
    restored_any = False
    for root in roots:
        if not await _dir_exists(sb, root):
            continue
        tags = await _git(sb, root, f"tag -l {tag}")
        if not tags.strip():
            continue
        await _git(sb, root, f"reset --hard {tag}")
        await _git(sb, root, "clean -fdx")
        restored_any = True
    if not restored_any:
        raise ValueError(
            f"Checkpoint tag {tag!r} not found in any of roots {list(roots)}"
        )
