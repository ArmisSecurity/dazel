"""Test doubles: a recording executor, workspace builders and the shared sandbox fixture."""

import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeVar

from dazel.config import Config, load_config
from dazel.executor import Output

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class Call:
    """One recorded executor invocation."""

    argv: tuple[str, ...]
    env: dict[str, str] | None
    output: Output | None


@dataclass
class FakeExecutor:
    """Records calls; answers captures and exit codes by argv prefix (longest match wins)."""

    captures: dict[str, str] = field(default_factory=dict)
    exit_codes: dict[str, int] = field(default_factory=dict)
    missing: set[str] = field(default_factory=set)
    calls: list[Call] = field(default_factory=list)

    def _lookup(self, table: Mapping[str, T], argv: Sequence[str], default: T) -> T:
        line = " ".join(argv)
        matches = [key for key in table if line.startswith(key)]
        return table[max(matches, key=len)] if matches else default

    def call(
        self,
        argv: Sequence[str],
        env: Mapping[str, str] | None = None,
        output: Output = Output.STDERR,
    ) -> int:
        self.calls.append(Call(tuple(argv), None if env is None else dict(env), output))
        return self._lookup(self.exit_codes, argv, 0)

    def capture(self, argv: Sequence[str], env: Mapping[str, str] | None = None) -> str:
        self.calls.append(Call(tuple(argv), None if env is None else dict(env), None))
        result = self._lookup(self.captures, argv, "")
        if result == "FAIL":
            raise subprocess.CalledProcessError(1, list(argv))
        return result

    def exists(self, command: str) -> bool:
        return command not in self.missing

    def lines(self) -> list[str]:
        return [" ".join(call.argv) for call in self.calls]


def make_workspace(root: Path, rc: str = "", name: str = "ws") -> Path:
    """Create a bazel workspace directory with an optional ``.dazelrc``."""
    workspace = root / name
    workspace.mkdir(parents=True)
    (workspace / "WORKSPACE").touch()
    if rc:
        (workspace / ".dazelrc").write_text(rc, encoding="utf-8")
    return workspace


def make_linked_worktree(primary: Path, name: str = "linked") -> Path:
    """Create a linked git worktree of ``primary`` (as ``git worktree add`` lays it out)."""
    git_dir = primary / ".git"
    entry = git_dir / "worktrees" / name
    entry.mkdir(parents=True, exist_ok=True)
    (entry / "commondir").write_text("../..\n", encoding="utf-8")
    linked = primary.parent / name
    linked.mkdir()
    (linked / "WORKSPACE").touch()
    (linked / ".git").write_text(f"gitdir: {git_dir}/worktrees/{name}\n", encoding="utf-8")
    return linked


def build_config(workspace: Path, env: Mapping[str, str] | None = None) -> Config:
    """Load the workspace configuration with its bazel output root inside the test sandbox."""
    root = str(workspace.parent / "out")
    return load_config({"DAZEL_BAZEL_USER_OUTPUT_ROOT": root, **(env or {})}, workspace)


def run_file_of(cfg: Config) -> Path:
    """Return the configured run file, which the test expects to be enabled."""
    assert cfg.run_file is not None
    return cfg.run_file


# Real-world rc files, kept in sync with the ones Armis runs dazel with.
FIXTURES = Path(__file__).parent / "fixtures"
LOCAL_DAZELRC = FIXTURES / "armis.dazelrc"
CI_DAZELRC = FIXTURES / "armis_ci.dazelrc"
