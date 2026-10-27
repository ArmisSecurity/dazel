import os
import shutil
import stat
import subprocess
import sys
import tomllib
from collections.abc import Mapping, Sequence
from importlib.metadata import PackageNotFoundError
from pathlib import Path

import pytest

import dazel
from dazel import cli
from dazel.clean import UnsafeCleanError, clean_workspace, remove_tree
from dazel.docker import rm_tree_argv
from dazel.executor import Output
from dazel.plan import make_plan
from dazel.version import UNKNOWN_VERSION, installed_version
from dazel.workspace import workspace_digest

from fake_support import FakeExecutor, build_config, make_workspace, run_file_of


def test_remove_tree_deletes_read_only_directories(tmp_path: Path) -> None:
    tree = tmp_path / "base"
    nested = tree / "a" / "b"
    nested.mkdir(parents=True)
    (nested / "f").write_text("x", encoding="utf-8")
    nested.chmod(stat.S_IRUSR | stat.S_IXUSR)
    tree.chmod(stat.S_IRUSR | stat.S_IXUSR)
    remove_tree(tree)
    assert not tree.exists()


def test_remove_tree_deletes_a_large_read_only_tree_and_leaves_symlink_targets_alone(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep").touch()
    outside.chmod(stat.S_IRUSR | stat.S_IXUSR)
    tree = tmp_path / "base"
    for index in range(50):
        leaf = tree / f"d{index}" / "nested"
        leaf.mkdir(parents=True)
        (leaf / "file").touch()
        leaf.chmod(stat.S_IRUSR | stat.S_IXUSR)
    (tree / "d0" / "link").symlink_to(outside)
    for directory in sorted(tree.glob("d*"), reverse=True):
        directory.chmod(stat.S_IRUSR | stat.S_IXUSR)
    tree.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        remove_tree(tree)
        assert not tree.exists()
        assert (outside / "keep").exists()
        assert not outside.stat().st_mode & stat.S_IWUSR
    finally:
        outside.chmod(stat.S_IRWXU)


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
    run_file_of(cfg).write_text("x\n", encoding="utf-8")
    executor = FakeExecutor()
    assert clean_workspace(cfg, plan, executor) == 0
    assert executor.lines() == [
        f"docker stop {plan.instance_name}",
        f"docker rm {plan.instance_name}",
    ]
    assert not plan.layout.base.exists()
    assert not run_file_of(cfg).exists()
    assert other_base.exists()


def root_owned_files(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the first removal attempt fail the way Linux does for files the root container created."""
    real = shutil.rmtree
    calls = {"n": 0}

    def rmtree(path: Path) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError(13, "Permission denied", str(path))
        real(path)

    monkeypatch.setattr("dazel.clean.shutil.rmtree", rmtree)


class DockerRemoves(FakeExecutor):
    """An executor whose ``docker run --rm ... rm -rf <path>`` really deletes the path."""

    def call(self, argv: Sequence[str], env: Mapping[str, str] | None = None, output: Output = Output.STDERR) -> int:
        rc = super().call(argv, env, output)
        if list(argv[:3]) == ["docker", "run", "--rm"]:
            shutil.rmtree(argv[-1])
        return rc


def test_clean_removes_root_owned_files_with_docker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = build_config(make_workspace(tmp_path), {"DAZEL_PER_WORKSPACE_CONTAINER": "1"})
    plan = make_plan(cfg)
    assert plan.layout.base is not None
    (plan.layout.base / "execroot").mkdir(parents=True)
    root_owned_files(monkeypatch)
    executor = DockerRemoves(captures={"docker image ls": "abc\n"})

    assert clean_workspace(cfg, plan, executor) == 0

    assert not plan.layout.base.exists()
    run = executor.lines()[-1]
    parent = plan.layout.base.parent
    assert run.startswith("docker run --rm --pull=never --entrypoint rm --mount ")
    assert f"--mount type=bind,src={parent},dst={parent} " in run
    assert run.endswith(f"{cfg.repository}/{plan.image_name} -rf {plan.layout.base}")


@pytest.mark.parametrize(
    ("parent", "mount"),
    [
        ("/data/a:b", "type=bind,src=/data/a:b,dst=/data/a:b"),
        ("/data/a,b", '"type=bind","src=/data/a,b","dst=/data/a,b"'),
        ('/data/a"b', '"type=bind","src=/data/a""b","dst=/data/a""b"'),
    ],
)
def test_rm_tree_mounts_with_the_mount_flag_so_unusual_paths_survive(tmp_path: Path, parent: str, mount: str) -> None:
    cfg = build_config(make_workspace(tmp_path), {"DAZEL_PER_WORKSPACE_CONTAINER": "1"})
    argv = rm_tree_argv(cfg, make_plan(cfg), Path(parent) / "base")
    assert argv[argv.index("--mount") + 1] == mount
    assert "-v" not in argv


def test_clean_names_the_missing_image_instead_of_pulling_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = build_config(make_workspace(tmp_path), {"DAZEL_PER_WORKSPACE_CONTAINER": "1"})
    plan = make_plan(cfg)
    assert plan.layout.base is not None
    plan.layout.base.mkdir(parents=True)
    root_owned_files(monkeypatch)
    executor = FakeExecutor()

    with pytest.raises(UnsafeCleanError, match=rf"image {cfg.repository}/{plan.image_name} is not present"):
        clean_workspace(cfg, plan, executor)

    assert not any(line.startswith("docker run") for line in executor.lines())


def test_clean_explains_the_manual_command_when_docker_cannot_remove_it_either(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = build_config(make_workspace(tmp_path), {"DAZEL_PER_WORKSPACE_CONTAINER": "1"})
    plan = make_plan(cfg)
    assert plan.layout.base is not None
    plan.layout.base.mkdir(parents=True)
    root_owned_files(monkeypatch)

    with pytest.raises(UnsafeCleanError, match=r"owned by root. Run: docker run --rm --pull=never --entrypoint rm"):
        clean_workspace(cfg, plan, FakeExecutor(captures={"docker image ls": "abc\n"}, exit_codes={"docker run": 1}))
    assert plan.layout.base.exists()


def test_clean_refuses_when_the_container_is_shared(tmp_path: Path) -> None:
    cfg = build_config(make_workspace(tmp_path))
    executor = FakeExecutor()
    with pytest.raises(UnsafeCleanError):
        clean_workspace(cfg, make_plan(cfg), executor)
    assert executor.calls == []


def test_cli_clean_flag_exits_with_error_when_not_per_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(make_workspace(tmp_path))
    assert cli.main([cli.CLEAN_FLAG]) == 1
    assert "ERROR: " in capsys.readouterr().err


def test_cli_outside_a_workspace_reports_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    assert cli.main(["version"]) == 1
    assert "WORKSPACE" in capsys.readouterr().err


def test_cli_clean_flag_only_counts_as_sole_argument(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = make_workspace(tmp_path)
    monkeypatch.chdir(workspace)
    seen: list[list[str]] = []

    def fake_send(_self: object, args: list[str]) -> int:
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


def test_cli_returns_start_failure_without_running_the_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(make_workspace(tmp_path))
    monkeypatch.setattr("dazel.instance.DockerInstance.needs_start", lambda _self: True)
    starts: list[bool] = []

    def failing_start(_self: object, *, only_if_needed: bool = False) -> int:
        starts.append(only_if_needed)
        return 9

    monkeypatch.setattr("dazel.instance.DockerInstance.start", failing_start)

    def boom(_self: object, _args: list[str]) -> int:
        msg = "must not run"
        raise AssertionError(msg)

    monkeypatch.setattr("dazel.instance.DockerInstance.send_command", boom)
    assert cli.main(["build"]) == 9
    assert starts == [True]


def test_cli_reports_docker_failures_instead_of_a_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(make_workspace(tmp_path))

    def daemon_down(_self: object) -> bool:
        raise subprocess.CalledProcessError(1, ["docker", "ps"])

    monkeypatch.setattr("dazel.instance.DockerInstance.needs_start", daemon_down)
    assert cli.main(["build"]) == 1
    assert "docker" in capsys.readouterr().err


def no_source_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("dazel.version._source_tree_version", lambda: None)


def test_cli_version_flag_prints_the_installed_version(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    no_source_tree(monkeypatch)
    monkeypatch.setattr("dazel.version.version", lambda _name: "9.8.7")
    assert cli.main([cli.VERSION_FLAG]) == 0
    assert capsys.readouterr().out == "dazel 9.8.7\n"


def test_version_falls_back_when_not_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(_name: str) -> str:
        raise PackageNotFoundError

    no_source_tree(monkeypatch)
    monkeypatch.setattr("dazel.version.version", missing)
    assert installed_version() == UNKNOWN_VERSION


def test_a_source_tree_reports_its_own_version_even_when_another_dazel_is_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("dazel.version.version", lambda _name: "0.0.43")
    pyproject = tomllib.loads(
        (Path(dazel.__file__).resolve().parents[2] / "pyproject.toml").read_text(encoding="utf-8")
    )
    assert installed_version() == pyproject["project"]["version"] != "0.0.43"


def test_python_dash_m_dazel_runs_from_the_source_tree_without_site_packages(tmp_path: Path) -> None:
    source = Path(dazel.__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-S", "-m", "dazel", cli.VERSION_FLAG],
        cwd=tmp_path,
        env={"PYTHONPATH": str(source), "PATH": os.environ["PATH"]},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == f"dazel {installed_version()}\n"


def test_container_name_flag_prints_the_workspace_container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = make_workspace(tmp_path, "DAZEL_PER_WORKSPACE_CONTAINER = True\n")
    monkeypatch.chdir(workspace)
    assert cli.main([cli.CONTAINER_NAME_FLAG]) == 0
    assert capsys.readouterr().out == f"dazel_{workspace_digest(workspace)}\n"


def test_container_name_flag_is_just_the_plain_name_without_per_workspace_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(make_workspace(tmp_path))
    assert cli.main([cli.CONTAINER_NAME_FLAG]) == 0
    assert capsys.readouterr().out == "dazel\n"


def test_version_flag_is_not_special_with_other_arguments(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(make_workspace(tmp_path))
    monkeypatch.setattr("dazel.instance.DockerInstance.needs_start", lambda _self: False)
    seen: list[list[str]] = []
    monkeypatch.setattr("dazel.instance.DockerInstance.send_command", lambda _self, args: seen.append(list(args)) or 0)
    assert cli.main([cli.VERSION_FLAG, "x"]) == 0
    assert seen == [[cli.VERSION_FLAG, "x"]]
