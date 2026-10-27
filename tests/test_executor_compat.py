import os
import shlex
import signal
import subprocess
import sys
import threading
from pathlib import Path

import pytest

import dazel
from dazel.executor import Output, SubprocessExecutor, executor_for, machine_env

from fake_support import LOCAL_DAZELRC, FakeExecutor, make_workspace


def test_subprocess_executor_captures_stdout() -> None:
    assert SubprocessExecutor().capture([sys.executable, "-c", "print('hi')"]) == "hi\n"


def test_subprocess_executor_capture_raises_on_failure() -> None:
    with pytest.raises(subprocess.CalledProcessError):
        SubprocessExecutor().capture([sys.executable, "-c", "raise SystemExit(3)"])


@pytest.mark.parametrize("output", list(Output))
def test_subprocess_executor_returns_the_exit_status(output: Output) -> None:
    assert SubprocessExecutor().call([sys.executable, "-c", "raise SystemExit(4)"], output=output) == 4


def die_by(sig: signal.Signals) -> list[str]:
    """A child that resets the signal to its default, then kills itself with it."""
    reset = "" if sig is signal.SIGKILL else f"signal.signal({sig.value},signal.SIG_DFL);"
    code = f"import os,signal;{reset}os.kill(os.getpid(),{sig.value})"
    return [sys.executable, "-c", code]


@pytest.mark.parametrize("sig", [signal.SIGINT, signal.SIGQUIT, signal.SIGTERM, signal.SIGKILL])
def test_subprocess_executor_reports_death_by_signal_as_128_plus_the_signal(sig: signal.Signals) -> None:
    assert SubprocessExecutor().call(die_by(sig)) == 128 + sig.value


def test_a_sigint_to_the_parent_is_left_to_the_child_and_raises_nothing() -> None:
    """Ctrl-C reaches parent and child alike; the parent must wait for the child, not die with a traceback."""
    before = signal.getsignal(signal.SIGINT)
    child = [sys.executable, "-c", "import time;time.sleep(0.6)"]
    timer = threading.Timer(0.2, os.kill, [os.getpid(), signal.SIGINT])
    timer.start()
    try:
        assert SubprocessExecutor().call(child) == 0
    finally:
        timer.cancel()
    assert signal.getsignal(signal.SIGINT) is before


@pytest.mark.parametrize("sig", ["SIGINT", "SIGQUIT"])
def test_the_child_does_not_inherit_an_ignored_signal(sig: str) -> None:
    probe = f"import signal,sys;sys.exit(1 if signal.getsignal(signal.{sig}) is signal.SIG_IGN else 0)"
    assert SubprocessExecutor().call([sys.executable, "-c", probe]) == 0


def test_runs_from_a_worker_thread_where_signals_cannot_be_rebound() -> None:
    results: list[int] = []
    thread = threading.Thread(target=lambda: results.append(SubprocessExecutor().call([sys.executable, "-c", "pass"])))
    thread.start()
    thread.join()
    assert results == [0]


def test_signals_are_restored_even_when_the_child_cannot_start() -> None:
    before = (signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGQUIT))
    with pytest.raises(FileNotFoundError):
        SubprocessExecutor().call(["definitely-not-a-command-xyz"])
    assert (signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGQUIT)) == before


def test_subprocess_executor_merges_environment_layers() -> None:
    executor = SubprocessExecutor({"BASE": "b"})
    code = "import os;print(os.environ['BASE'], os.environ['EXTRA'], 'HOME' in os.environ)"
    assert executor.capture([sys.executable, "-c", code], {"EXTRA": "e"}) == "b e True\n"


def test_subprocess_executor_does_not_interpret_shell_syntax() -> None:
    assert (
        SubprocessExecutor().capture([sys.executable, "-c", "import sys;print(sys.argv[1])", "$HOME;x"]) == "$HOME;x\n"
    )


def test_exists() -> None:
    executor = SubprocessExecutor()
    assert executor.exists("sh")
    assert not executor.exists("definitely-not-a-command-xyz")


def test_machine_env_parses_exports() -> None:
    executor = FakeExecutor(captures={"docker-machine env m": 'export A="1"\n# comment\nexport B="x=y"\n'})
    assert machine_env(executor, "m") == {"A": "1", "B": "x=y"}


def test_executor_for_without_machine_is_plain() -> None:
    assert isinstance(executor_for(""), SubprocessExecutor)


def test_library_api_used_by_acli_dtest(tmp_path: Path) -> None:
    rc = LOCAL_DAZELRC.read_text(encoding="utf-8")
    workspace = make_workspace(tmp_path, rc)
    env = {**os.environ, "DAZEL_PER_WORKSPACE_CONTAINER": "True"}
    instance = dazel.DockerInstance.from_config(env, workspace)
    exec_prefix = f"{instance.docker_command} exec {instance.instance_name}"
    assert shlex.split(exec_prefix)[:2] == ["docker", "exec"]
    assert instance.instance_name.startswith("dazel_")
    assert isinstance(dazel.__version__, str)
    assert callable(dazel.main)
