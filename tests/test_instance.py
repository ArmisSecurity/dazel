import json
import os
from pathlib import Path

import pytest

from dazel import DockerInstance
from dazel.docker import Terminal
from dazel.executor import Output

from fakes import FakeExecutor, build_config, make_workspace

TERMINAL = Terminal(100, 30, "xterm", tty=False)


def instance(workspace: Path, executor: FakeExecutor, **env: str) -> DockerInstance:
    return DockerInstance(build_config(workspace, env), executor, lambda: TERMINAL)


def running(inst: DockerInstance, binds: list[str] | None = None, networks: str = "dazel") -> dict:
    real = inst.plan.workdir
    return {
        f"docker ps --filter name=^{inst.instance_name}$": f"{inst.instance_name}\n",
        "docker inspect --format {{json .HostConfig.Binds}}": json.dumps(
            binds if binds is not None else [f"{real}:{real}:delegated"]
        ),
        "docker inspect --format {{json .NetworkSettings.Networks}}": json.dumps({networks: {}}),
    }


def test_is_running_true_when_name_bind_and_network_match(tmp_path: Path) -> None:
    executor = FakeExecutor()
    inst = instance(make_workspace(tmp_path), executor)
    executor.captures = running(inst)
    assert inst.is_running()


def test_is_running_false_when_container_absent(tmp_path: Path) -> None:
    assert not instance(make_workspace(tmp_path), FakeExecutor()).is_running()


def test_is_running_false_when_name_is_only_a_prefix(tmp_path: Path) -> None:
    executor = FakeExecutor(captures={"docker ps": "dazel_other\n"})
    assert not instance(make_workspace(tmp_path), executor).is_running()


def test_is_running_false_when_bound_to_another_workspace(tmp_path: Path) -> None:
    executor = FakeExecutor()
    inst = instance(make_workspace(tmp_path), executor)
    executor.captures = running(inst, binds=["/elsewhere:/elsewhere"])
    assert not inst.is_running()


def test_is_running_does_not_confuse_a_longer_host_path(tmp_path: Path) -> None:
    executor = FakeExecutor()
    inst = instance(make_workspace(tmp_path), executor)
    real = inst.plan.workdir
    executor.captures = running(inst, binds=[f"/prefix{real}:{real}"])
    assert not inst.is_running()


def test_is_running_false_on_wrong_network(tmp_path: Path) -> None:
    executor = FakeExecutor()
    inst = instance(make_workspace(tmp_path), executor)
    executor.captures = running(inst, networks="other")
    assert not inst.is_running()


def test_worktrees_in_per_workspace_mode_do_not_restart_each_other(tmp_path: Path) -> None:
    executors = [FakeExecutor(), FakeExecutor()]
    first, other = (
        instance(make_workspace(tmp_path, name=name), executor, DAZEL_PER_WORKSPACE_CONTAINER="1")
        for name, executor in zip("ab", executors, strict=True)
    )
    for inst, executor in zip((first, other), executors, strict=True):
        executor.captures = running(inst)
    assert first.is_running()
    assert other.is_running()
    assert first.instance_name != other.instance_name


def test_needs_start_without_run_file(tmp_path: Path) -> None:
    executor = FakeExecutor()
    inst = instance(make_workspace(tmp_path), executor)
    executor.captures = running(inst)
    assert inst.needs_start()


def test_needs_start_false_when_run_file_exists_and_container_runs(tmp_path: Path) -> None:
    executor = FakeExecutor()
    inst = instance(make_workspace(tmp_path), executor)
    executor.captures = running(inst)
    inst.config.run_file.write_text("dazel\n", encoding="utf-8")
    assert not inst.needs_start()


def test_needs_start_when_dockerfile_is_newer_than_run_file(tmp_path: Path) -> None:
    executor = FakeExecutor()
    workspace = make_workspace(tmp_path)
    inst = instance(workspace, executor)
    executor.captures = running(inst)
    inst.config.run_file.write_text("dazel\n", encoding="utf-8")
    dockerfile = workspace / "Dockerfile.dazel"
    dockerfile.touch()
    later = inst.config.run_file.stat().st_ctime + 100
    os.utime(dockerfile, (later, later))
    dockerfile.chmod(0o644)
    if dockerfile.stat().st_ctime <= inst.config.run_file.stat().st_ctime:
        pytest.skip("filesystem does not advance ctime")
    assert inst.needs_start()


def test_send_command_execs_bazel_inside_the_container(tmp_path: Path) -> None:
    executor = FakeExecutor(exit_codes={"docker exec": 3})
    workspace = make_workspace(tmp_path)
    inst = instance(workspace, executor, DAZEL_BAZEL_USER_OUTPUT_ROOT="")
    assert inst.send_command(["version"]) == 3
    [call] = executor.calls
    assert call.output is Output.INHERIT
    assert call.argv[-2:] == ("/usr/bin/bazel", "version")
    assert call.argv[:8] == (
        "docker", "exec", "-i", "-e", "COLUMNS=100", "-e", "LINES=30", "-e",
    )  # fmt: skip


def test_start_builds_image_when_dockerfile_exists_and_runs_container(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    (workspace / "Dockerfile.dazel").touch()
    executor = FakeExecutor()
    inst = instance(workspace, executor)
    assert inst.start() == 0
    verbs = [line.split()[1] for line in executor.lines() if line.startswith("docker ")]
    assert verbs == ["build", "network", "network", "stop", "rm", "run"]
    assert inst.config.run_file.read_text(encoding="utf-8") == "dazel\n"


def test_start_pulls_when_there_is_no_dockerfile(tmp_path: Path) -> None:
    executor = FakeExecutor()
    instance(make_workspace(tmp_path), executor).start()
    assert "docker pull dazel/dazel" in executor.lines()


def test_start_tolerates_failed_pull_when_image_exists(tmp_path: Path) -> None:
    executor = FakeExecutor(exit_codes={"docker pull": 1}, captures={"docker image ls": "abc\n"})
    assert instance(make_workspace(tmp_path), executor).start() == 0


def test_start_fails_on_failed_pull_without_image(tmp_path: Path) -> None:
    executor = FakeExecutor(exit_codes={"docker pull": 1})
    assert instance(make_workspace(tmp_path), executor).start() == 1
    assert not any(line.startswith("docker run") for line in executor.lines())


def test_start_fails_without_docker(tmp_path: Path) -> None:
    executor = FakeExecutor(missing={"docker"})
    assert instance(make_workspace(tmp_path), executor).start() == 1
    assert executor.calls == []


def test_failed_run_leaves_no_run_file(tmp_path: Path) -> None:
    executor = FakeExecutor(exit_codes={"docker run": 125})
    inst = instance(make_workspace(tmp_path), executor)
    assert inst.start() == 125
    assert not inst.config.run_file.exists()


def test_start_creates_host_directories_before_run(tmp_path: Path) -> None:
    cache = tmp_path / "disk-cache"
    inst = instance(make_workspace(tmp_path), FakeExecutor(), DAZEL_BAZEL_DISK_CACHE=str(cache))
    inst.start()
    assert cache.is_dir()
    assert all(path.is_dir() for path in inst.plan.layout.mount_dirs)


def test_start_with_compose_runs_compose_instead_of_network_and_run_deps(tmp_path: Path) -> None:
    executor = FakeExecutor()
    inst = instance(
        make_workspace(tmp_path),
        executor,
        DAZEL_DOCKER_COMPOSE_FILE="c.yml",
        DAZEL_RUN_DEPS="postgres::pg",
    )
    inst.start()
    lines = executor.lines()
    assert sum("docker-compose" in line for line in lines) == 3
    assert not any("network" in line or "--name=pg" in line for line in lines)
    compose_calls = [call for call in executor.calls if call.argv[0] == "docker-compose"]
    assert all(call.env == {"COMPOSE_PROJECT_NAME": "dazel"} for call in compose_calls)


def test_start_stops_at_first_failing_compose_step(tmp_path: Path) -> None:
    executor = FakeExecutor(exit_codes={"docker-compose": 2})
    inst = instance(make_workspace(tmp_path), executor, DAZEL_DOCKER_COMPOSE_FILE="c.yml")
    assert inst.start() == 2
    assert sum("docker-compose" in line for line in executor.lines()) == 1


def test_missing_compose_binary_falls_back_to_network_setup(tmp_path: Path) -> None:
    executor = FakeExecutor(missing={"docker-compose"})
    instance(make_workspace(tmp_path), executor, DAZEL_DOCKER_COMPOSE_FILE="c.yml").start()
    assert any(line.startswith("docker network create") for line in executor.lines())


def test_existing_network_is_not_recreated(tmp_path: Path) -> None:
    executor = FakeExecutor(captures={"docker network ls": "bridge\ndazel\n"})
    instance(make_workspace(tmp_path), executor).start()
    assert not any(line.startswith("docker network create") for line in executor.lines())


def test_predefined_network_is_never_created(tmp_path: Path) -> None:
    executor = FakeExecutor()
    instance(make_workspace(tmp_path), executor, DAZEL_NETWORK="host").start()
    assert not any(line.startswith("docker network") for line in executor.lines())


def test_only_missing_run_deps_are_started(tmp_path: Path) -> None:
    executor = FakeExecutor(captures={"docker ps --filter name=^up$": "up\n"})
    instance(make_workspace(tmp_path), executor, DAZEL_RUN_DEPS="a::up,b::down").start()
    runs = [line for line in executor.lines() if line.startswith("docker run -id --name=")]
    assert [line.split("--name=")[1].split()[0] for line in runs] == ["down", "dazel"]


def test_from_config_reads_the_current_workspace(tmp_path: Path) -> None:
    workspace = make_workspace(
        tmp_path, 'DAZEL_INSTANCE_NAME = "named"\nDAZEL_DOCKER_COMMAND = "podman"\n'
    )
    inst = DockerInstance.from_config({}, workspace)
    assert (inst.instance_name, inst.docker_command) == ("named", "podman")
