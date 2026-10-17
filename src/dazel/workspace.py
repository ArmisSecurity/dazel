"""Workspace discovery and identity."""

import hashlib
from pathlib import Path

WORKSPACE_MARKERS = ("WORKSPACE", "WORKSPACE.bazel", "MODULE.bazel")


class WorkspaceNotFoundError(FileNotFoundError):
    """Raised when no bazel workspace root is found above the starting directory."""


def find_workspace(start: Path) -> Path:
    """Return the closest ancestor of ``start`` (inclusive) holding a bazel workspace marker."""
    resolved = start.resolve()
    for candidate in (resolved, *resolved.parents):
        if any((candidate / marker).exists() for marker in WORKSPACE_MARKERS):
            return candidate
    msg = f"No {' or '.join(WORKSPACE_MARKERS)} file found above {resolved}"
    raise WorkspaceNotFoundError(msg)


def workspace_digest(directory: Path) -> str:
    """Return the md5 hex digest identifying a workspace by its real path."""
    return hashlib.md5(str(directory.resolve()).encode(), usedforsecurity=False).hexdigest()


def is_linked_worktree(directory: Path) -> bool:
    """Return whether ``directory`` is a linked git worktree rather than a primary checkout.

    A linked worktree has a ``.git`` file pointing into ``<common-dir>/worktrees/<name>``,
    whereas a primary checkout has a ``.git`` directory.
    """
    dot_git = directory / ".git"
    if not dot_git.is_file():
        return False
    pointer = dot_git.read_text(encoding="utf-8").strip().removeprefix("gitdir:").strip()
    return "worktrees" in Path(pointer).parts
