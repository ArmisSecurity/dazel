"""Process execution behind a small protocol so everything above it is testable without docker."""

import contextlib
import os
import shutil
import signal
import subprocess
import sys
from collections.abc import Iterator, Mapping, Sequence
from enum import Enum
from typing import Protocol


class Output(Enum):
    """Where a child's stdout goes."""

    INHERIT = "inherit"
    STDERR = "stderr"
    DISCARD = "discard"


INTERRUPT_SIGNALS = (signal.SIGINT, signal.SIGQUIT)
SIGNAL_EXIT_BASE = 128


# A handler, unlike SIG_IGN, is reset to the default disposition by exec.
def _ignore_signal(_signum: int, _frame: object) -> None:
    return


@contextlib.contextmanager
def interrupts_left_to_child() -> Iterator[None]:
    """Leave SIGINT and SIGQUIT to the child while it runs, like ``os.system`` does.

    A terminal delivers Ctrl-C to the whole foreground process group. The parent must neither die
    with a traceback nor stop waiting; the child decides how to react and its status is returned.
    A handler (not ``SIG_IGN``) is installed so the child still starts with default dispositions.
    Signals can only be rebound from the main thread; elsewhere this is a no-op.
    """
    try:
        previous = {sig: signal.signal(sig, _ignore_signal) for sig in INTERRUPT_SIGNALS}
    except ValueError:
        yield
        return
    try:
        yield
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def exit_status(returncode: int) -> int:
    """Map a ``subprocess`` return code to a shell exit status: death by signal N is ``128 + N``."""
    return SIGNAL_EXIT_BASE - returncode if returncode < 0 else returncode


class Executor(Protocol):
    """The only way dazel touches the system."""

    def call(
        self,
        argv: Sequence[str],
        env: Mapping[str, str] | None = None,
        output: Output = Output.STDERR,
    ) -> int:
        """Run ``argv`` to completion and return its exit status."""
        ...

    def capture(self, argv: Sequence[str], env: Mapping[str, str] | None = None) -> str:
        """Run ``argv`` and return its stdout; raises ``CalledProcessError`` on failure."""
        ...

    def exists(self, command: str) -> bool:
        """Return whether ``command`` resolves on ``PATH``."""
        ...


class SubprocessExecutor:
    """Executor backed by ``subprocess``; arguments are always argv lists, never shell strings."""

    def __init__(self, base_env: Mapping[str, str] | None = None) -> None:
        self._base_env = dict(base_env or {})

    def _environment(self, env: Mapping[str, str] | None) -> dict[str, str] | None:
        merged = {**self._base_env, **(env or {})}
        if not merged:
            return None
        return {**os.environ, **merged}

    def call(
        self,
        argv: Sequence[str],
        env: Mapping[str, str] | None = None,
        output: Output = Output.STDERR,
    ) -> int:
        """Run ``argv`` to completion and return its exit status."""
        stdout = {
            Output.INHERIT: None,
            Output.STDERR: sys.stderr,
            Output.DISCARD: subprocess.DEVNULL,
        }[output]
        stderr = subprocess.DEVNULL if output is Output.DISCARD else None
        with (
            interrupts_left_to_child(),
            subprocess.Popen(argv, env=self._environment(env), stdout=stdout, stderr=stderr) as child,
        ):
            return exit_status(child.wait())

    def capture(self, argv: Sequence[str], env: Mapping[str, str] | None = None) -> str:
        """Run ``argv`` and return its stdout; raises ``CalledProcessError`` on failure."""
        return subprocess.check_output(argv, env=self._environment(env), text=True)

    def exists(self, command: str) -> bool:
        """Return whether ``command`` resolves on ``PATH``."""
        return shutil.which(command) is not None


def machine_env(executor: Executor, machine: str) -> dict[str, str]:
    """Return the environment ``docker-machine env`` would export for ``machine``."""
    lines = executor.capture(["docker-machine", "env", machine, "--shell", "sh"]).splitlines()
    pairs = (line.removeprefix("export ").partition("=") for line in lines if line.startswith("export "))
    return {key: value.strip('"') for key, _, value in pairs}


def executor_for(machine: str) -> Executor:
    """Return an executor targeting ``machine`` when docker-machine is configured and installed."""
    plain = SubprocessExecutor()
    if machine and plain.exists("docker-machine"):
        return SubprocessExecutor(machine_env(plain, machine))
    return plain
