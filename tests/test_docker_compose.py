from pathlib import Path

import pytest

from dazel import docker
from dazel.compose import compose_steps
from dazel.config import RunDep
from dazel.docker import Terminal
from dazel.plan import make_plan

from fakes import build_config, make_workspace

TERMINAL = Terminal(columns=120, lines=40, term="xterm", tty=True)


def test_run_argv_for_a_full_configuration(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    env = {
        "DAZEL_VOLUMES": "/a:/b",
        "DAZEL_PORTS": "1:1,2:2",
        "DAZEL_ENV_VARS": "A=1,B=2",
        "DAZEL_PLATFORM": "linux/arm64",
        "DAZEL_DOCKER_RUN_PRIVILEGED": "True",
        "DAZEL_USER": "1000",
        "DAZEL_GPUS": "all",
        "DAZEL_SHM_SIZE": "1g",
        "DAZEL_NETWORK": "net",
        "DAZEL_REPOSITORY": "repo",
        "DAZEL_IMAGE_NAME": "img",
        "DAZEL_RUN_COMMAND": "/bin/sh -c sleep",
    }
    cfg = build_config(workspace, env)
    plan = make_plan(cfg)
    real = workspace.resolve()
    out = (tmp_path / "out").resolve()
    assert docker.run_argv(cfg, plan) == [
        "docker", "run", "-id", "--name=dazel",
        "--ulimit", "nofile=1048576:1048576",
        "--platform=linux/arm64", "--privileged", "--user=1000",
        "-w", str(real),
        "-v", "/a:/b",
        "-v", f"{real}:{real}",
        *[arg for name in ("external", "action_cache", "execroot", "ws")
          for arg in ("-v", f"{out / name}:{out / name}:delegated")],
        "-p", "1:1", "-p", "2:2",
        "-e", "A=1", "-e", "B=2",
        "--gpus", "all",
        "--shm-size=1g",
        "--net=net",
        "repo/img",
        "/bin/sh", "-c", "sleep",
    ]  # fmt: skip


def test_run_argv_minimal_has_only_the_essentials(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    cfg = build_config(workspace, {"DAZEL_BAZEL_USER_OUTPUT_ROOT": "", "DAZEL_REPOSITORY": ""})
    argv = docker.run_argv(cfg, make_plan(cfg))
    real = str(workspace.resolve())
    assert argv == [
        "docker", "run", "-id", "--name=dazel", "--ulimit", "nofile=1048576:1048576",
        "-w", real, "-v", f"{real}:{real}", "--net=dazel", "dazel", "/bin/bash",
    ]  # fmt: skip


def test_run_argv_never_goes_through_a_shell(tmp_path: Path) -> None:
    cfg = build_config(make_workspace(tmp_path), {"DAZEL_ENV_VARS": "A=b c;rm -rf /"})
    assert "A=b c;rm -rf /" in docker.run_argv(cfg, make_plan(cfg))


def test_exec_argv_with_tty_and_privileges(tmp_path: Path) -> None:
    cfg = build_config(
        make_workspace(tmp_path), {"DAZEL_DOCKER_RUN_PRIVILEGED": "1", "DAZEL_USER": "7"}
    )
    argv = docker.exec_argv(cfg, make_plan(cfg), TERMINAL, ["bazel", "build"])
    assert argv == [
        "docker", "exec", "-i", "-e", "COLUMNS=120", "-e", "LINES=40", "-e", "TERM=xterm",
        "-t", "--privileged", "--user=7", "dazel", "bazel", "build",
    ]  # fmt: skip


def test_exec_argv_without_tty(tmp_path: Path) -> None:
    cfg = build_config(make_workspace(tmp_path))
    argv = docker.exec_argv(cfg, make_plan(cfg), Terminal(80, 24, "", tty=False), ["x"])
    assert "-t" not in argv
    assert argv[-2:] == ["dazel", "x"]


def test_build_argv(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    env = {"DAZEL_DOCKER_BUILD_ARGS": "--platform=linux/arm64", "DAZEL_DOCKERFILE": "d/Dockerfile"}
    cfg = build_config(workspace, env)
    root = workspace.resolve()
    assert docker.build_argv(cfg, make_plan(cfg)) == [
        "docker", "build", "--platform=linux/arm64", "-t", "dazel/dazel",
        "-f", f"{root}/d/Dockerfile", str(root),
    ]  # fmt: skip


@pytest.mark.parametrize(
    ("builder", "expected"),
    [
        (docker.pull_argv, ["docker", "pull", "dazel/dazel"]),
        (docker.image_ls_argv, ["docker", "image", "ls", "--quiet", "dazel/dazel"]),
    ],
)
def test_image_commands(tmp_path: Path, builder, expected: list[str]) -> None:  # noqa: ANN001
    cfg = build_config(make_workspace(tmp_path))
    assert builder(cfg, make_plan(cfg)) == expected


def test_container_commands(tmp_path: Path) -> None:
    cfg = build_config(make_workspace(tmp_path), {"DAZEL_DOCKER_COMMAND": "sudo docker"})
    assert docker.stop_argv(cfg, "n") == ["sudo", "docker", "stop", "n"]
    assert docker.rm_argv(cfg, "n") == ["sudo", "docker", "rm", "n"]
    assert docker.ps_argv(cfg, "n") == [
        "sudo", "docker", "ps", "--filter", "name=^n$", "--format", "{{.Names}}",
    ]  # fmt: skip
    assert docker.inspect_argv(cfg, "n", "T") == ["sudo", "docker", "inspect", "--format", "T", "n"]
    assert docker.network_ls_argv(cfg) == [
        "sudo",
        "docker",
        "network",
        "ls",
        "--format",
        "{{.Name}}",
    ]
    assert docker.network_create_argv(cfg, make_plan(cfg)) == [
        "sudo", "docker", "network", "create", "dazel",
    ]  # fmt: skip


def test_run_dep_argv(tmp_path: Path) -> None:
    cfg = build_config(make_workspace(tmp_path), {"DAZEL_DOCKER_RUN_PRIVILEGED": "1"})
    argv = docker.run_dep_argv(cfg, make_plan(cfg), RunDep("postgres", "armis_postgres"))
    assert argv == [
        "docker", "run", "-id", "--name=armis_postgres", "--privileged", "--net=dazel", "postgres",
    ]  # fmt: skip


COMPOSE_ENV = {
    "DAZEL_DOCKER_COMPOSE_FILE": "c.yml",
    "DAZEL_DOCKER_COMPOSE_PROJECT_NAME": "proj",
    "DAZEL_DOCKER_COMPOSE_SERVICES": "a,b",
}


def test_compose_steps(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    cfg = build_config(workspace, COMPOSE_ENV)
    steps = compose_steps(cfg, make_plan(cfg))
    base = ["docker-compose", "-f", f"{workspace.resolve()}/c.yml"]
    assert [list(step.argv) for step in steps] == [
        [*base, "pull", "--ignore-pull-failures", "a", "b"],
        [*base, "build", "a", "b"],
        [*base, "up", "--force-recreate", "-d", "a", "b"],
    ]
    assert all(step.env == {"COMPOSE_PROJECT_NAME": "proj"} for step in steps)


def test_compose_up_does_not_force_recreate_shared_services_per_workspace(tmp_path: Path) -> None:
    cfg = build_config(
        make_workspace(tmp_path), {**COMPOSE_ENV, "DAZEL_PER_WORKSPACE_CONTAINER": "1"}
    )
    up = compose_steps(cfg, make_plan(cfg))[-1]
    assert "--force-recreate" not in up.argv
    assert up.env == {"COMPOSE_PROJECT_NAME": "proj"}


def test_no_compose_file_no_steps(tmp_path: Path) -> None:
    cfg = build_config(make_workspace(tmp_path))
    assert compose_steps(cfg, make_plan(cfg)) == []
