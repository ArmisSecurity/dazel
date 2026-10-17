"""Command line entry point: forwards arguments to bazel inside the dazel container."""

import logging
import subprocess
import sys
from collections.abc import Sequence

from dazel.clean import UnsafeCleanError
from dazel.config import ConfigError
from dazel.instance import DockerInstance
from dazel.workspace import WorkspaceNotFoundError

CLEAN_FLAG = "--dazel-clean-workspace"

logger = logging.getLogger("dazel")


def main(argv: Sequence[str] | None = None) -> int:
    """Run dazel; ``--dazel-clean-workspace`` as the sole argument cleans this workspace.

    Any other arguments are bazel arguments, forwarded verbatim.
    """
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        instance = DockerInstance.from_config()
        if args == [CLEAN_FLAG]:
            return instance.clean_workspace()
        if instance.needs_start() and (rc := instance.start()):
            return rc
        return instance.send_command(args)
    except (
        WorkspaceNotFoundError,
        ConfigError,
        UnsafeCleanError,
        subprocess.CalledProcessError,
        OSError,
    ) as error:
        logger.error("ERROR: %s", error)  # noqa: TRY400  # a user-facing message, not a bug
        return 1
