from pathlib import Path

import pytest

from dazel.bazel import OutputLayout, bazel_argv, derive_user_root, output_layout

from fakes import build_config, make_workspace


def test_root_user_gets_container_output_user_root_and_base(tmp_path: Path) -> None:
    cfg = build_config(make_workspace(tmp_path), {"DAZEL_BAZEL_RC_FILE": "deploy/.bazelrc"})
    layout = output_layout(cfg, "abc")
    argv = bazel_argv(cfg, layout, ["build", "//x"])
    base = (tmp_path / "out" / "abc").resolve()
    assert argv == [
        "/usr/bin/bazel",
        "--bazelrc=deploy/.bazelrc",
        "--output_user_root=/var/bazel/workspace/_bazel_tester",
        f"--output_base={base}",
        "build",
        "//x",
    ]


def test_configured_user_gets_only_the_host_user_root(tmp_path: Path) -> None:
    cfg = build_config(make_workspace(tmp_path), {"DAZEL_USER": "1000"})
    argv = bazel_argv(cfg, output_layout(cfg, ""), ["info"])
    assert argv == ["/usr/bin/bazel", f"--output_user_root={tmp_path / 'out'}", "info"]


def test_empty_command_passes_arguments_through(tmp_path: Path) -> None:
    cfg = build_config(make_workspace(tmp_path), {"DAZEL_COMMAND": ""})
    assert bazel_argv(cfg, output_layout(cfg, ""), ["ls", "-l"]) == ["ls", "-l"]


def test_command_with_flags_is_split(tmp_path: Path) -> None:
    cfg = build_config(
        make_workspace(tmp_path), {"DAZEL_COMMAND": "/usr/bin/bazel --noworkspace_rc"}
    )
    argv = bazel_argv(cfg, OutputLayout(), ["version"])
    assert argv == ["/usr/bin/bazel", "--noworkspace_rc", "version"]


def test_without_output_root_no_output_flags(tmp_path: Path) -> None:
    cfg = build_config(make_workspace(tmp_path), {"DAZEL_BAZEL_USER_OUTPUT_ROOT": ""})
    layout = output_layout(cfg, "")
    assert layout == OutputLayout()
    assert bazel_argv(cfg, layout, ["info"]) == ["/usr/bin/bazel", "info"]


def test_user_root_is_derived_from_the_bazel_out_symlink(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    target = tmp_path / "cache" / "_bazel_me" / "hash" / "execroot" / "ws" / "bazel-out"
    target.mkdir(parents=True)
    (workspace / "bazel-out").symlink_to(target)
    assert derive_user_root(workspace) == str((tmp_path / "cache" / "_bazel_me").resolve())


def test_no_bazel_out_means_no_derived_root(tmp_path: Path) -> None:
    assert derive_user_root(make_workspace(tmp_path)) == ""


@pytest.mark.parametrize("digest", ["", "abc"])
def test_layout_mounts_live_under_the_base(tmp_path: Path, digest: str) -> None:
    layout = output_layout(build_config(make_workspace(tmp_path)), digest)
    assert layout.base is not None
    assert [path.name for path in layout.mount_dirs] == [
        "external",
        "action_cache",
        "execroot",
        "ws",
    ]
    assert all(path.parent == layout.base for path in layout.mount_dirs)
    assert layout.base.name == (digest or "out")
