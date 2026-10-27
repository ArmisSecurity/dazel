from pathlib import Path

import pytest

from dazel import cli
from dazel.clean import UnsafeCleanError
from dazel.config import Config
from dazel.legacy import clean_legacy, legacy_paths
from dazel.plan import Plan, make_plan
from fake_support import FakeExecutor, build_config, make_workspace

MD5 = "0123456789abcdef0123456789abcdef"


def legacy_tree(root: Path) -> Path:
    """The shared output base the old dazel left under ``root``, next to things that must survive."""
    for name in ("external", "execroot", "action_cache", "server"):
        (root / name / "deep").mkdir(parents=True)
        (root / name / "deep" / "file").write_text("x", encoding="utf-8")
    (root / "ws").mkdir()
    (root / "README").write_text("WORKSPACE: /x\n", encoding="utf-8")
    (root / MD5 / "execroot").mkdir(parents=True)
    (root / "install").mkdir()
    (root / ".dazel.lock").touch()
    (root / "unknown").mkdir()
    (root / "unknown" / "keep").touch()
    (root / "empty-md5-lookalike").mkdir()
    (root / ("f" * 32)).mkdir()
    return root


def survivors(root: Path) -> set[str]:
    return {entry.name for entry in root.iterdir()}


def test_legacy_paths_are_exactly_the_shared_base_entries(tmp_path: Path) -> None:
    root = legacy_tree(tmp_path)
    names = {path.name for path in legacy_paths(root)}
    assert names == {"external", "execroot", "action_cache", "server", "README", "ws", "empty-md5-lookalike"}


def test_empty_directories_are_not_touched_without_a_legacy_base(tmp_path: Path) -> None:
    for name in ("some-checkout", "another"):
        (tmp_path / name).mkdir()
    (tmp_path / "install").mkdir()
    assert legacy_paths(tmp_path) == []


def test_a_lone_marker_is_enough_to_list_the_leftover_mount_points(tmp_path: Path) -> None:
    (tmp_path / "action_cache").mkdir()
    (tmp_path / "ws").mkdir()
    (tmp_path / "ws2").mkdir()
    assert {path.name for path in legacy_paths(tmp_path)} == {"action_cache", "ws", "ws2"}


def test_only_empty_direct_children_are_leftover_mount_points(tmp_path: Path) -> None:
    (tmp_path / "execroot").mkdir()
    (tmp_path / "outer" / "inner").mkdir(parents=True)
    names = {path.name for path in legacy_paths(tmp_path)}
    assert names == {"execroot"}


def test_legacy_paths_of_a_missing_root_is_empty(tmp_path: Path) -> None:
    assert legacy_paths(tmp_path / "nope") == []


def per_workspace(tmp_path: Path, **captures: str) -> tuple[Path, FakeExecutor, Config, Plan]:
    workspace = make_workspace(tmp_path)
    cfg = build_config(workspace, {"DAZEL_PER_WORKSPACE_CONTAINER": "1"})
    root = Path(make_plan(cfg).layout.user_root)
    root.mkdir(parents=True)
    return legacy_tree(root), FakeExecutor(captures=captures), cfg, make_plan(cfg)


def test_dry_run_lists_and_removes_nothing(tmp_path: Path) -> None:
    root, executor, cfg, plan = per_workspace(tmp_path)
    before = survivors(root)
    assert len(clean_legacy(cfg, plan, executor, delete=False)) == 7
    assert survivors(root) == before


def test_delete_removes_only_the_legacy_entries(tmp_path: Path) -> None:
    root, executor, cfg, plan = per_workspace(tmp_path)
    clean_legacy(cfg, plan, executor, delete=True)
    assert survivors(root) == {MD5, "install", ".dazel.lock", "unknown", "f" * 32}
    assert (root / MD5 / "execroot").is_dir()
    assert (root / "install").is_dir()


def test_delete_handles_read_only_directories(tmp_path: Path) -> None:
    root, executor, cfg, plan = per_workspace(tmp_path)
    (root / "execroot" / "deep").chmod(0o500)
    clean_legacy(cfg, plan, executor, delete=True)
    assert not (root / "execroot").exists()


def test_refuses_while_the_legacy_container_exists(tmp_path: Path) -> None:
    root, executor, cfg, plan = per_workspace(tmp_path, **{"docker ps --all --filter name=^dazel$": "dazel\n"})
    before = survivors(root)
    with pytest.raises(UnsafeCleanError, match="legacy container 'dazel'"):
        clean_legacy(cfg, plan, executor, delete=True)
    assert survivors(root) == before


def test_refuses_without_per_workspace_mode(tmp_path: Path) -> None:
    cfg = build_config(make_workspace(tmp_path))
    with pytest.raises(UnsafeCleanError, match="PER_WORKSPACE"):
        clean_legacy(cfg, make_plan(cfg), FakeExecutor(), delete=True)


def test_cli_lists_by_default_and_deletes_with_yes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = make_workspace(tmp_path, 'DAZEL_PER_WORKSPACE_CONTAINER = True\nDAZEL_BAZEL_USER_OUTPUT_ROOT = "out"\n')
    root = workspace.parent / "out"
    root.mkdir()
    legacy_tree(root)
    monkeypatch.chdir(workspace)
    monkeypatch.setattr("dazel.instance.executor_for", lambda _machine: FakeExecutor())
    monkeypatch.setenv("DAZEL_BAZEL_USER_OUTPUT_ROOT", str(root))

    assert cli.main([cli.CLEAN_LEGACY_FLAG]) == 0
    listing = capsys.readouterr().out
    assert f"Would remove {root / 'execroot'}" in listing
    assert "--yes" in listing
    assert (root / "execroot").exists()

    assert cli.main([cli.CLEAN_LEGACY_FLAG, cli.CONFIRM_FLAG]) == 0
    assert f"Removed {root / 'execroot'}" in capsys.readouterr().out
    assert not (root / "execroot").exists()
    assert (root / "install").exists()

    assert cli.main([cli.CLEAN_LEGACY_FLAG, cli.CONFIRM_FLAG]) == 0
    assert "No legacy shared output base" in capsys.readouterr().out


def test_cli_reports_the_refusal_on_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(make_workspace(tmp_path))
    assert cli.main([cli.CLEAN_LEGACY_FLAG]) == 1
    assert "DAZEL_PER_WORKSPACE_CONTAINER" in capsys.readouterr().err


def test_yes_alone_is_a_bazel_argument(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(make_workspace(tmp_path))
    monkeypatch.setattr("dazel.instance.DockerInstance.needs_start", lambda _self: False)
    seen: list[list[str]] = []
    monkeypatch.setattr("dazel.instance.DockerInstance.send_command", lambda _self, args: seen.append(list(args)) or 0)
    assert cli.main([cli.CONFIRM_FLAG]) == 0
    assert cli.main([cli.CLEAN_LEGACY_FLAG, cli.CONFIRM_FLAG, "extra"]) == 0
    assert seen == [[cli.CONFIRM_FLAG], [cli.CLEAN_LEGACY_FLAG, cli.CONFIRM_FLAG, "extra"]]
