"""Removal of one workspace's container and bazel output base."""

import logging
import os
import shlex
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
    pending = [path]
    while pending:
        directory = pending.pop()
        directory.chmod(directory.stat().st_mode | stat.S_IRWXU)
        with os.scandir(directory) as entries:
            pending.extend(Path(entry.path) for entry in entries if entry.is_dir(follow_symlinks=False))


def remove_tree(path: Path) -> None:
    """Remove a directory tree, including the read-only directories bazel leaves behind."""
    if path.is_dir() and not path.is_symlink():
        _make_writable(path)
        shutil.rmtree(path)


def remove_tree_as_root(cfg: Config, plan: Plan, executor: Executor, path: Path) -> None:
    """Remove ``path``; on Linux fall back to removing what the root container created as root.

    Raises ``UnsafeCleanError`` with the manual command when even that fails, or when the image
    that would run it is not present (it is never pulled for this).
    """
    try:
        remove_tree(path)
    except PermissionError:
        logger.warning("Some files in %s are owned by root; removing them with docker", path)
        argv = docker.rm_tree_argv(cfg, plan, path)
        if not executor.capture(docker.image_ls_argv(cfg, plan)).strip():
            msg = (
                f"Could not remove {path}: files created by the container are owned by root, and the image "
                f"{docker.image_ref(cfg, plan)} is not present to remove them with. "
                f"Run as root: rm -rf {shlex.quote(str(path))}"
            )
            raise UnsafeCleanError(msg) from None
        if executor.call(argv) or path.exists():
            msg = f"Could not remove {path}: files created by the container are owned by root. Run: {shlex.join(argv)}"
            raise UnsafeCleanError(msg) from None


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
    remove_tree_as_root(cfg, plan, executor, plan.layout.base)
    if cfg.run_file:
        cfg.run_file.unlink(missing_ok=True)
    return 0
