"""Process execution behind a small protocol so everything above it is testable without docker."""

import os
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from enum import Enum
from typing import Protocol


class Output(Enum):
    """Where a child's stdout goes."""

    INHERIT = "inherit"
    STDERR = "stderr"
    DISCARD = "discard"


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
        return subprocess.call(argv, env=self._environment(env), stdout=stdout, stderr=stderr)

    def capture(self, argv: Sequence[str], env: Mapping[str, str] | None = None) -> str:
        """Run ``argv`` and return its stdout; raises ``CalledProcessError`` on failure."""
        return subprocess.check_output(argv, env=self._environment(env), text=True)

    def exists(self, command: str) -> bool:
        """Return whether ``command`` resolves on ``PATH``."""
        return shutil.which(command) is not None


def machine_env(executor: Executor, machine: str) -> dict[str, str]:
    """Return the environment ``docker-machine env`` would export for ``machine``."""
    lines = executor.capture(["docker-machine", "env", machine, "--shell", "sh"]).splitlines()
    pairs = (
        line.removeprefix("export ").partition("=") for line in lines if line.startswith("export ")
    )
    return {key: value.strip('"') for key, _, value in pairs}


def executor_for(machine: str) -> Executor:
    """Return an executor targeting ``machine`` when docker-machine is configured and installed."""
    plain = SubprocessExecutor()
    if machine and plain.exists("docker-machine"):
        return SubprocessExecutor(machine_env(plain, machine))
    return plain
