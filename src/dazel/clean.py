"""Removal of one workspace's container and bazel output base."""

import logging
import shutil
import stat
from pathlib import Path

from dazel import docker
from dazel.config import Config
from dazel.executor import Executor, Output
from dazel.plan import Plan

logger = logging.getLogger("dazel")


class UnsafeCleanError(RuntimeError):
    """Raised when cleaning would touch state shared with other workspaces."""


def _make_writable(path: Path) -> None:
    for entry in (path, *path.rglob("*")):
        if not entry.is_symlink() and entry.is_dir():
            entry.chmod(entry.stat().st_mode | stat.S_IRWXU)


def remove_tree(path: Path) -> None:
    """Remove a directory tree, including the read-only directories bazel leaves behind."""
    if path.is_dir() and not path.is_symlink():
        _make_writable(path)
        shutil.rmtree(path)


def clean_workspace(cfg: Config, plan: Plan, executor: Executor) -> int:
    """Remove this workspace's container, output base and run file; return an exit status.

    Refuses to run unless the workspace has its own container, since the container and the
    output base are otherwise shared by every workspace.
    """
    if not plan.digest or plan.layout.base is None:
        msg = "Cleaning needs DAZEL_PER_WORKSPACE_CONTAINER (or DAZEL_WORKSPACE_HEX) to be enabled"
        raise UnsafeCleanError(msg)
    logger.info("Removing container '%s'", plan.instance_name)
    executor.call(docker.stop_argv(cfg, plan.instance_name), output=Output.DISCARD)
    executor.call(docker.rm_argv(cfg, plan.instance_name), output=Output.DISCARD)
    remove_tree(plan.layout.base)
    cfg.run_file.unlink(missing_ok=True)
    return 0
