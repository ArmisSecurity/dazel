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


def _worktree_gitdir(directory: Path) -> Path | None:
    dot_git = directory / ".git"
    if not dot_git.is_file():
        return None
    pointer = directory / dot_git.read_text(encoding="utf-8").strip().removeprefix("gitdir:").strip()
    is_worktree_entry = pointer.parent.name == "worktrees" and (pointer / "commondir").is_file()
    return pointer if is_worktree_entry else None


def is_linked_worktree(directory: Path) -> bool:
    """Return whether ``directory`` is a linked git worktree rather than a primary checkout.

    Only a ``.git`` file pointing at a ``<common-dir>/worktrees/<name>`` entry holding a ``commondir``
    file counts; a submodule's, a ``--separate-git-dir`` clone's or a ``.git`` directory does not.
    """
    return _worktree_gitdir(directory) is not None


def primary_checkout(directory: Path) -> Path:
    """Return the primary checkout ``directory`` is a linked worktree of, else ``directory`` itself.

    The primary is the parent of the common git directory (``<common-dir>/worktrees/<name>`` is
    where the linked worktree's ``.git`` file points). A common directory not called ``.git``
    (``--separate-git-dir``) does not reveal the checkout, so ``directory`` is kept.
    """
    gitdir = _worktree_gitdir(directory)
    if gitdir is None:
        return directory
    common = gitdir.parent.parent
    return common.parent if common.name == ".git" else directory
