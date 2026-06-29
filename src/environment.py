"""Git-based sandbox checkpointing.

Provides checkpoint/restore primitives backed by git inside the sandbox. Used
by the solver to snapshot the seed state after provisioning, and by
reset_target to restore the sandbox to a clean state between branches.

Each tracked root gets its own git repo. We snapshot BOTH:

  - /workspace — seed files + the target's working tree.
  - /srv       — mock service state (servicenow/splunk/slack/... state.json +
                 audit logs). Critical for branch comparison: a seed's B1 vs B2
                 contrast is only valid if the mock state resets between
                 branches, and the mocks write their state under /srv, not
                 /workspace. (Before this was tracked, /srv mutations from B1 —
                 closed tickets, worknotes, posted messages — bled into B2.)

/home/user is deliberately NOT tracked: it holds the scaffold's own runtime
state (Gemini/Codex/Claude CLI home, ACP session files), and git-cleaning it
mid-run could break the live target.

A root that doesn't exist in a given sandbox (e.g. a toy seed with no /srv) is
skipped, so this is safe for seeds that don't use mock services.
"""

from __future__ import annotations

from inspect_ai.util import SandboxEnvironment

# Filesystem roots snapshotted on checkpoint and reverted on restore. Each gets
# an independent git repo. ROOTS[0] (/workspace) is the primary and must always
# carry the tag; the rest are best-effort.
ROOTS = ("/workspace", "/srv")


async def _git(sb: SandboxEnvironment, workdir: str, args: str) -> str:
    result = await sb.exec(
        ["bash", "-c", f"git -c safe.directory={workdir} -C {workdir} {args}"],
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git command failed (exit {result.returncode}) in {workdir}: git {args}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return result.stdout


async def _dir_exists(sb: SandboxEnvironment, path: str) -> bool:
    result = await sb.exec(["bash", "-c", f"test -d {path}"], timeout=5)
    return result.returncode == 0


async def _has_tag(sb: SandboxEnvironment, workdir: str, tag: str) -> bool:
    has_git = await sb.exec(["bash", "-c", f"test -d {workdir}/.git"], timeout=5)
    if has_git.returncode != 0:
        return False
    return bool((await _git(sb, workdir, f"tag -l {tag}")).strip())


async def checkpoint(sb: SandboxEnvironment, tag: str) -> None:
    """Snapshot each tracked root under the given tag.

    Idempotent: re-running with the same tag force-updates the tag to the
    current state. Roots absent in this sandbox (e.g. a seed with no /srv) are
    skipped. Initializes a git repo + config in any tracked root that lacks one.
    """
    for workdir in ROOTS:
        if not await _dir_exists(sb, workdir):
            continue
        has_git = await sb.exec(["bash", "-c", f"test -d {workdir}/.git"], timeout=5)
        if has_git.returncode != 0:
            init = await sb.exec(["bash", "-c", f"git init {workdir}"], timeout=10)
            if init.returncode != 0:
                raise RuntimeError(f"git init failed in {workdir}: {init.stderr}")
            await _git(sb, workdir, 'config user.email "petri@local"')
            await _git(sb, workdir, 'config user.name "petri"')

        await _git(sb, workdir, "add -A")
        await _git(sb, workdir, f'commit --allow-empty -q -m "checkpoint: {tag}"')
        await _git(sb, workdir, f"tag -f {tag}")


async def restore(sb: SandboxEnvironment, tag: str) -> None:
    """Restore each tracked root to the given tag.

    Restores tracked files to their tagged state and removes untracked files.
    The primary root (/workspace) must carry the tag — a missing tag there means
    checkpoint never ran, which is an error. Other roots are best-effort: a root
    that exists but was never checkpointed under this tag is skipped.
    """
    primary = ROOTS[0]
    if not await _has_tag(sb, primary, tag):
        raise ValueError(f"Checkpoint tag '{tag}' not found in {primary}")

    for workdir in ROOTS:
        if not await _dir_exists(sb, workdir):
            continue
        if not await _has_tag(sb, workdir, tag):
            continue
        await _git(sb, workdir, f"reset --hard {tag}")
        await _git(sb, workdir, "clean -fdx")
