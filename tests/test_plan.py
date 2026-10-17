from pathlib import Path

import pytest

from dazel.plan import host_dirs_to_create, make_plan, publish_ports
from dazel.workspace import workspace_digest

from fakes import build_config, make_linked_worktree, make_workspace

PORTS = {"DAZEL_PORTS": "127.0.0.1:1:1"}


def test_default_mode_shares_one_container_and_output_base(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    plan = make_plan(build_config(workspace))
    assert plan.instance_name == "dazel"
    assert plan.digest == ""
    assert plan.layout.base == (tmp_path / "out").resolve()


def test_per_workspace_mode_suffixes_container_and_output_base(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    digest = workspace_digest(workspace)
    plan = make_plan(build_config(workspace, {"DAZEL_PER_WORKSPACE_CONTAINER": "True"}))
    assert plan.instance_name == f"dazel_{digest}"
    assert plan.layout.base == (tmp_path / "out" / digest).resolve()
    assert plan.digest == digest


def test_per_workspace_mode_shares_image_project_and_network(tmp_path: Path) -> None:
    env = {"DAZEL_DOCKER_COMPOSE_FILE": "c.yml", "DAZEL_NETWORK": "default"}
    shared = make_plan(build_config(make_workspace(tmp_path, name="a"), env))
    isolated = make_plan(
        build_config(
            make_workspace(tmp_path, name="b"), {**env, "DAZEL_PER_WORKSPACE_CONTAINER": "1"}
        )
    )
    assert (isolated.image_name, isolated.compose_project_name, isolated.network) == (
        shared.image_name,
        shared.compose_project_name,
        shared.network,
    )
    assert isolated.network == "dazel_default"


def test_per_workspace_names_differ_between_workspaces(tmp_path: Path) -> None:
    env = {"DAZEL_PER_WORKSPACE_CONTAINER": "1"}
    first = make_plan(build_config(make_workspace(tmp_path, name="a"), env))
    second = make_plan(build_config(make_workspace(tmp_path, name="b"), env))
    assert first.instance_name != second.instance_name
    assert first.layout.base != second.layout.base


def test_legacy_workspace_hex_suffixes_image_and_compose_project(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    (workspace / "Dockerfile.dazel").touch()
    digest = workspace_digest(workspace)
    plan = make_plan(build_config(workspace, {"DAZEL_WORKSPACE_HEX": "1"}))
    assert plan.instance_name == f"dazel_{digest}"
    assert plan.image_name == f"dazel_{digest}"
    assert plan.compose_project_name == f"dazel{digest}"


def test_legacy_workspace_hex_keeps_image_without_dockerfile(tmp_path: Path) -> None:
    plan = make_plan(build_config(make_workspace(tmp_path), {"DAZEL_WORKSPACE_HEX": "1"}))
    assert plan.image_name == "dazel"


@pytest.mark.parametrize(
    ("network", "compose", "expected"),
    [
        ("default", "c.yml", "dazel_default"),
        ("default", "", "default"),
        ("host", "c.yml", "host"),
        ("bridge", "c.yml", "bridge"),
    ],
)
def test_network_name(tmp_path: Path, network: str, compose: str, expected: str) -> None:
    env = {"DAZEL_NETWORK": network, "DAZEL_DOCKER_COMPOSE_FILE": compose}
    assert make_plan(build_config(make_workspace(tmp_path), env)).network == expected


@pytest.mark.parametrize(
    ("env", "linked", "published"),
    [
        ({"DAZEL_PER_WORKSPACE_CONTAINER": "1"}, False, True),
        ({"DAZEL_PER_WORKSPACE_CONTAINER": "1"}, True, False),
        ({"DAZEL_PER_WORKSPACE_CONTAINER": "1", "DAZEL_PORTS_ONLY_PRIMARY": "False"}, True, True),
        ({}, True, True),
        ({"DAZEL_PORTS_ONLY_PRIMARY": "True"}, True, False),
        ({"DAZEL_PORTS_ONLY_PRIMARY": "True"}, False, True),
    ],
)
def test_ports_are_published_only_by_the_primary_checkout(
    tmp_path: Path,
    env: dict[str, str],
    linked: bool,
    published: bool,
) -> None:
    primary = make_workspace(tmp_path)
    (primary / ".git").mkdir(exist_ok=True)
    workspace = make_linked_worktree(primary) if linked else primary
    cfg = build_config(workspace, {**PORTS, **env})
    assert publish_ports(cfg) is published
    assert make_plan(cfg).ports == (PORTS["DAZEL_PORTS"],) * published


def test_volumes_hold_user_mounts_workspace_and_output_dirs(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    plan = make_plan(build_config(workspace, {"DAZEL_VOLUMES": "/a:/b"}))
    out = (tmp_path / "out").resolve()
    real = workspace.resolve()
    assert plan.volumes == (
        "/a:/b",
        f"{real}:{real}",
        f"{out / 'external'}:{out / 'external'}:delegated",
        f"{out / 'action_cache'}:{out / 'action_cache'}:delegated",
        f"{out / 'execroot'}:{out / 'execroot'}:delegated",
        f"{out / 'ws'}:{out / 'ws'}:delegated",
    )


def test_delegated_flag_can_be_disabled(tmp_path: Path) -> None:
    plan = make_plan(build_config(make_workspace(tmp_path), {"DAZEL_DELEGATED_VOLUME": "False"}))
    assert not any(volume.endswith(":delegated") for volume in plan.volumes)


def test_disk_cache_is_mounted_at_the_same_path(tmp_path: Path) -> None:
    cache = tmp_path / "disk" / "cache"
    cfg = build_config(make_workspace(tmp_path), {"DAZEL_BAZEL_DISK_CACHE": str(cache)})
    plan = make_plan(cfg)
    assert plan.volumes[-1] == f"{cache}:{cache}"
    assert cache in host_dirs_to_create(plan, cfg)


def test_no_disk_cache_means_no_extra_mount(tmp_path: Path) -> None:
    cfg = build_config(make_workspace(tmp_path))
    assert cfg.bazel_disk_cache is None
    plan = make_plan(cfg)
    assert len(plan.volumes) == 1 + len(plan.layout.mount_dirs)


def test_host_dirs_cover_output_root_and_mounts(tmp_path: Path) -> None:
    cfg = build_config(make_workspace(tmp_path))
    plan = make_plan(cfg)
    dirs = host_dirs_to_create(plan, cfg)
    assert Path(plan.layout.user_root) in dirs
    assert set(plan.layout.mount_dirs) <= set(dirs)
