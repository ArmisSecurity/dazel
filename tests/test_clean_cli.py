import stat
import subprocess
from pathlib import Path

import pytest

from dazel import cli
from dazel.clean import UnsafeCleanError, clean_workspace, remove_tree
from dazel.plan import make_plan

from fakes import FakeExecutor, build_config, make_workspace


def test_remove_tree_deletes_read_only_directories(tmp_path: Path) -> None:
    tree = tmp_path / "base"
    nested = tree / "a" / "b"
    nested.mkdir(parents=True)
    (nested / "f").write_text("x", encoding="utf-8")
    nested.chmod(stat.S_IRUSR | stat.S_IXUSR)
    tree.chmod(stat.S_IRUSR | stat.S_IXUSR)
    remove_tree(tree)
    assert not tree.exists()


def test_remove_tree_does_not_follow_symlinks(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    (target / "keep").touch()
    link = tmp_path / "link"
    link.symlink_to(target)
    remove_tree(link)
    assert (target / "keep").exists()


def test_remove_tree_ignores_missing_path(tmp_path: Path) -> None:
    remove_tree(tmp_path / "nothing")


def test_clean_removes_container_output_base_and_run_file(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    cfg = build_config(workspace, {"DAZEL_PER_WORKSPACE_CONTAINER": "1"})
    plan = make_plan(cfg)
    assert plan.layout.base is not None
    (plan.layout.base / "execroot").mkdir(parents=True)
    other_base = tmp_path / "out" / "other"
    other_base.mkdir()
    cfg.run_file.write_text("x\n", encoding="utf-8")
    executor = FakeExecutor()
    assert clean_workspace(cfg, plan, executor) == 0
    assert executor.lines() == [
        f"docker stop {plan.instance_name}",
        f"docker rm {plan.instance_name}",
    ]
    assert not plan.layout.base.exists()
    assert not cfg.run_file.exists()
    assert other_base.exists()


def test_clean_refuses_when_the_container_is_shared(tmp_path: Path) -> None:
    cfg = build_config(make_workspace(tmp_path))
    executor = FakeExecutor()
    with pytest.raises(UnsafeCleanError):
        clean_workspace(cfg, make_plan(cfg), executor)
    assert executor.calls == []


def test_cli_clean_flag_exits_with_error_when_not_per_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.chdir(make_workspace(tmp_path))
    assert cli.main([cli.CLEAN_FLAG]) == 1
    assert "DAZEL_PER_WORKSPACE_CONTAINER" in caplog.text


def test_cli_outside_a_workspace_reports_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.chdir(tmp_path)
    assert cli.main(["version"]) == 1
    assert "WORKSPACE" in caplog.text


def test_cli_clean_flag_only_counts_as_sole_argument(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = make_workspace(tmp_path)
    monkeypatch.chdir(workspace)
    seen: list[list[str]] = []

    def fake_send(self: object, args: list[str]) -> int:  # noqa: ARG001
        seen.append(args)
        return 0

    monkeypatch.setattr("dazel.instance.DockerInstance.needs_start", lambda _self: False)
    monkeypatch.setattr("dazel.instance.DockerInstance.send_command", fake_send)
    assert cli.main([cli.CLEAN_FLAG, "extra"]) == 0
    assert seen == [[cli.CLEAN_FLAG, "extra"]]


def test_cli_forwards_arguments_and_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(make_workspace(tmp_path))
    monkeypatch.setattr("dazel.instance.DockerInstance.needs_start", lambda _self: False)
    monkeypatch.setattr("dazel.instance.DockerInstance.send_command", lambda _self, _args: 7)
    assert cli.main(["build", "//..."]) == 7


def test_cli_returns_start_failure_without_running_the_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(make_workspace(tmp_path))
    monkeypatch.setattr("dazel.instance.DockerInstance.needs_start", lambda _self: True)
    monkeypatch.setattr("dazel.instance.DockerInstance.start", lambda _self: 9)

    def boom(_self: object, _args: list[str]) -> int:
        msg = "must not run"
        raise AssertionError(msg)

    monkeypatch.setattr("dazel.instance.DockerInstance.send_command", boom)
    assert cli.main(["build"]) == 9


def test_cli_reports_docker_failures_instead_of_a_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.chdir(make_workspace(tmp_path))

    def daemon_down(_self: object) -> bool:
        raise subprocess.CalledProcessError(1, ["docker", "ps"])

    monkeypatch.setattr("dazel.instance.DockerInstance.needs_start", daemon_down)
    assert cli.main(["build"]) == 1
    assert "docker" in caplog.text
