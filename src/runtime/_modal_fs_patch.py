"""Compatibility shim: make ``inspect_sandboxes``' Modal provider use Modal's
**new** sandbox filesystem API.

Modal removed the *legacy* Sandbox filesystem API server-side (the
``ContainerFilesystemExec`` RPC behind ``sandbox.open`` / ``sandbox.mkdir``),
returning ``ConflictError: The legacy Sandbox filesystem API is no longer
supported``. ``inspect-sandboxes`` (through at least 0.5.0) still calls the
legacy API when provisioning ``setup_files``, so every Modal audit dies during
environment setup with 0 samples completed.

This was a dated, server-side removal — which is why Modal runs that worked in
mid-2025 stopped working with no change on our side. Bumping ``modal`` or
``inspect-sandboxes`` does not help (both still call the legacy API).

The installed ``modal`` already exposes the replacement API under
``sandbox.filesystem`` (``modal.sandbox_fs``): ``make_directory``,
``write_text`` / ``write_bytes``, ``read_text`` / ``read_bytes``. We rebind the
three ``ModalSandboxEnvironment`` helpers that touched the legacy API onto it,
preserving the provider's retry decorator and its expected exception contract
(so the public ``read_file`` / ``write_file`` error handling still maps to
``FileNotFoundError`` / ``IsADirectoryError``).

Remove this shim once ``inspect-sandboxes`` migrates upstream. See:
https://modal.com/docs/guide/migrate-sandbox-filesystem
"""

from __future__ import annotations

import errno
import logging

logger = logging.getLogger(__name__)


def apply() -> None:
    """Idempotently patch inspect_sandboxes' Modal provider. No-op if the
    ``modal`` extra isn't installed or the shim is already applied."""
    try:
        from inspect_sandboxes.modal import _modal as m
    except Exception:
        return  # modal extra not installed — nothing to patch

    cls = getattr(m, "ModalSandboxEnvironment", None)
    if cls is None or getattr(cls, "_fs_api_patched", False):
        return

    import modal.exception as mex

    retry = m._standard_retry  # reuse the provider's own retry policy

    @retry
    async def _write_file_content(self, file: str, contents: str | bytes) -> None:
        try:
            if isinstance(contents, str):
                await self.sandbox.filesystem.write_text.aio(contents, file)
            else:
                await self.sandbox.filesystem.write_bytes.aio(bytes(contents), file)
        except mex.SandboxFilesystemIsADirectoryError as e:
            # Preserve the contract the public write_file() catches.
            raise IsADirectoryError(errno.EISDIR, "Is a directory", file) from e

    @retry
    async def _read_file_content(self, file: str) -> bytes:
        try:
            return await self.sandbox.filesystem.read_bytes.aio(file)
        except mex.SandboxFilesystemError as e:
            # The provider's read_file() maps FilesystemExecutionError to
            # FileNotFoundError / IsADirectoryError; re-raise as that so the
            # existing handler keeps working with the new-API exceptions.
            raise mex.FilesystemExecutionError(str(e)) from e

    @retry
    async def _create_parent_folder(self, path: str) -> None:
        try:
            await self.sandbox.filesystem.make_directory.aio(path, create_parents=True)
        except mex.SandboxFilesystemPathAlreadyExistsError:
            pass
        except FileExistsError:
            pass

    cls._write_file_content = _write_file_content
    cls._read_file_content = _read_file_content
    cls._create_parent_folder = _create_parent_folder
    cls._fs_api_patched = True
    logger.info(
        "Applied Modal filesystem-API compatibility shim to "
        "inspect_sandboxes.modal.ModalSandboxEnvironment"
    )
