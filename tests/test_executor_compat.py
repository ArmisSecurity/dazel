import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

import dazel
from dazel.executor import Output, SubprocessExecutor, executor_for, machine_env

from conftest import FIXTURES
from fakes import FakeExecutor, make_workspace


def test_subprocess_executor_captures_stdout() -> None:
    assert SubprocessExecutor().capture([sys.executable, "-c", "print('hi')"]) == "hi\n"


def test_subprocess_executor_capture_raises_on_failure() -> None:
    with pytest.raises(subprocess.CalledProcessError):
        SubprocessExecutor().capture([sys.executable, "-c", "raise SystemExit(3)"])


@pytest.mark.parametrize("output", list(Output))
def test_subprocess_executor_returns_the_exit_status(output: Output) -> None:
    assert (
        SubprocessExecutor().call([sys.executable, "-c", "raise SystemExit(4)"], output=output) == 4
    )


def test_subprocess_executor_merges_environment_layers() -> None:
    executor = SubprocessExecutor({"BASE": "b"})
    code = "import os;print(os.environ['BASE'], os.environ['EXTRA'], 'HOME' in os.environ)"
    assert executor.capture([sys.executable, "-c", code], {"EXTRA": "e"}) == "b e True\n"


def test_subprocess_executor_does_not_interpret_shell_syntax() -> None:
    assert (
        SubprocessExecutor().capture(
            [sys.executable, "-c", "import sys;print(sys.argv[1])", "$HOME;x"]
        )
        == "$HOME;x\n"
    )


def test_exists() -> None:
    executor = SubprocessExecutor()
    assert executor.exists("sh")
    assert not executor.exists("definitely-not-a-command-xyz")


def test_machine_env_parses_exports() -> None:
    executor = FakeExecutor(
        captures={"docker-machine env m": 'export A="1"\n# comment\nexport B="x=y"\n'}
    )
    assert machine_env(executor, "m") == {"A": "1", "B": "x=y"}


def test_executor_for_without_machine_is_plain() -> None:
    assert isinstance(executor_for(""), SubprocessExecutor)


def test_library_api_used_by_acli_dtest(tmp_path: Path) -> None:
    rc = (FIXTURES / "armis.dazelrc").read_text(encoding="utf-8")
    workspace = make_workspace(tmp_path, rc)
    env = {**os.environ, "DAZEL_PER_WORKSPACE_CONTAINER": "True"}
    instance = dazel.DockerInstance.from_config(env, workspace)
    exec_prefix = f"{instance.docker_command} exec {instance.instance_name}"
    assert shlex.split(exec_prefix)[:2] == ["docker", "exec"]
    assert instance.instance_name.startswith("dazel_")
    assert isinstance(dazel.__version__, str)
    assert callable(dazel.main)
