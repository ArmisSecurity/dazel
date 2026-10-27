"""Removal of the shared output base the pre-per-workspace dazel left directly under the output root."""

import re
from pathlib import Path

from dazel import docker
from dazel.clean import UnsafeCleanError, remove_tree_as_root
from dazel.config import Config
from dazel.executor import Executor
from dazel.plan import Plan

LEGACY_MARKERS = frozenset({"external", "execroot", "action_cache"})
LEGACY_ENTRIES = LEGACY_MARKERS | {"server", "README", "DO_NOT_BUILD_HERE"}
KEPT_NAMES = frozenset({"install"})
_DIGEST = re.compile(r"[0-9a-f]{32}")


def _is_leftover_mount_point(entry: Path) -> bool:
    is_empty_dir = entry.is_dir() and not entry.is_symlink() and not any(entry.iterdir())
    return is_empty_dir and entry.name not in KEPT_NAMES and not _DIGEST.fullmatch(entry.name)


def legacy_paths(root: Path) -> list[Path]:
    """List the legacy shared output base entries directly under ``root``.

    Nothing is listed unless ``root`` holds one of the legacy markers (``execroot``, ``external``,
    ``action_cache``). Then the known legacy entries and the empty directories dazel bind mounted
    there are listed. Per-workspace bases (``<md5>``), ``install`` and everything else never are.
    """
    if not root.is_dir():
        return []
    entries = sorted(root.iterdir())
    if not any(entry.name in LEGACY_MARKERS for entry in entries):
        return []
    return [entry for entry in entries if entry.name in LEGACY_ENTRIES or _is_leftover_mount_point(entry)]


def clean_legacy(cfg: Config, plan: Plan, executor: Executor, *, delete: bool) -> list[Path]:
    """Return the legacy entries under the output root, deleting them when ``delete``.

    Refuses unless per-workspace mode is on and no legacy container exists: that container has
    these directories bind mounted and bazel inside it is using them.
    """
    if not cfg.per_workspace_container:
        msg = "Cleaning the legacy output base needs DAZEL_PER_WORKSPACE_CONTAINER to be enabled"
        raise UnsafeCleanError(msg)
    legacy = cfg.instance_name
    if legacy in executor.capture(docker.ps_argv(cfg, legacy, include_stopped=True)).split():
        msg = f"The legacy container '{legacy}' still exists; start dazel once (it removes it) or remove it first"
        raise UnsafeCleanError(msg)
    paths = legacy_paths(Path(plan.layout.user_root)) if plan.layout.user_root else []
    if delete:
        for path in paths:
            if path.is_symlink() or path.is_file():
                path.unlink()
            else:
                remove_tree_as_root(cfg, plan, executor, path)
    return paths
