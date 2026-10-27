"""Command line entry point: forwards arguments to bazel inside the dazel container."""

import logging
import subprocess
import sys
from collections.abc import Sequence

from dazel.clean import UnsafeCleanError
from dazel.config import ConfigError
from dazel.instance import DockerInstance
from dazel.version import installed_version
from dazel.workspace import WorkspaceNotFoundError

CLEAN_FLAG = "--dazel-clean-workspace"
CLEAN_LEGACY_FLAG = "--dazel-clean-legacy"
CONFIRM_FLAG = "--yes"
CONTAINER_NAME_FLAG = "--dazel-container-name"
VERSION_FLAG = "--dazel-version"


def main(argv: Sequence[str] | None = None) -> int:
    """Run dazel.

    ``--dazel-clean-workspace``, ``--dazel-version``, ``--dazel-container-name`` and
    ``--dazel-clean-legacy [--yes]`` as the whole command line are handled by dazel itself; any
    other arguments are bazel arguments, forwarded verbatim.
    """
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    args = list(sys.argv[1:] if argv is None else argv)
    if args == [VERSION_FLAG]:
        sys.stdout.write(f"dazel {installed_version()}\n")
        return 0
    try:
        return _dispatch(DockerInstance.from_config(), args)
    except (
        WorkspaceNotFoundError,
        ConfigError,
        UnsafeCleanError,
        subprocess.CalledProcessError,
        OSError,
    ) as error:
        sys.stderr.write(f"ERROR: {error}\n")
        return 1


def _dispatch(instance: DockerInstance, args: list[str]) -> int:
    if args == [CONTAINER_NAME_FLAG]:
        sys.stdout.write(f"{instance.instance_name}\n")
        return 0
    if args == [CLEAN_FLAG]:
        return instance.clean_workspace()
    if args in ([CLEAN_LEGACY_FLAG], [CLEAN_LEGACY_FLAG, CONFIRM_FLAG]):
        return _clean_legacy(instance, delete=CONFIRM_FLAG in args)
    if instance.needs_start() and (rc := instance.start(only_if_needed=True)):
        return rc
    return instance.send_command(args)


def _clean_legacy(instance: DockerInstance, *, delete: bool) -> int:
    paths = instance.clean_legacy(delete=delete)
    verb = "Removed" if delete else "Would remove"
    sys.stdout.write("".join(f"{verb} {path}\n" for path in paths))
    if not paths:
        sys.stdout.write("No legacy shared output base found\n")
    elif not delete:
        sys.stdout.write(f"Re-run with `dazel {CLEAN_LEGACY_FLAG} {CONFIRM_FLAG}` to delete them\n")
    return 0
