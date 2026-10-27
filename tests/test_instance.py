import fcntl
import hashlib
import json
import logging
import os
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from dazel import DockerInstance
from dazel import instance as instance_module
from dazel.docker import Terminal
from dazel.executor import Output

from fake_support import FakeExecutor, build_config, make_workspace, run_file_of

TERMINAL = Terminal(100, 30, "xterm", tty=False)


def instance(workspace: Path, executor: FakeExecutor, **env: str) -> DockerInstance:
    return DockerInstance(build_config(workspace, env), executor, lambda: TERMINAL)


def running(inst: DockerInstance, binds: list[str] | None = None, networks: str = "dazel") -> dict[str, str]:
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
    run_file_of(inst.config).write_text("dazel\n", encoding="utf-8")
    assert not inst.needs_start()


def test_needs_start_when_dockerfile_is_newer_than_run_file(tmp_path: Path) -> None:
    executor = FakeExecutor()
    workspace = make_workspace(tmp_path)
    inst = instance(workspace, executor)
    executor.captures = running(inst)
    run_file_of(inst.config).write_text("dazel\n", encoding="utf-8")
    dockerfile = workspace / "Dockerfile.dazel"
    dockerfile.touch()
    later = run_file_of(inst.config).stat().st_ctime + 100
    os.utime(dockerfile, (later, later))
    dockerfile.chmod(0o644)
    if dockerfile.stat().st_ctime <= run_file_of(inst.config).stat().st_ctime:
        pytest.skip("filesystem does not advance ctime")
    assert inst.needs_start()


def test_without_a_run_file_nothing_is_written_and_a_running_container_is_reused(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path, 'DAZEL_RUN_FILE = ""\n')
    executor = FakeExecutor()
    inst = instance(workspace, executor)
    executor.captures = running(inst)
    before = {path.name for path in workspace.iterdir()}

    assert not inst.needs_start()
    assert inst.start() == 0
    assert {path.name for path in workspace.iterdir()} == before


def test_without_a_run_file_a_stopped_container_is_started(tmp_path: Path) -> None:
    assert instance(make_workspace(tmp_path, 'DAZEL_RUN_FILE = ""\n'), FakeExecutor()).needs_start()


def test_send_command_execs_bazel_inside_the_container(tmp_path: Path) -> None:
    executor = FakeExecutor(exit_codes={"docker exec": 3})
    workspace = make_workspace(tmp_path)
    inst = instance(workspace, executor, DAZEL_BAZEL_USER_OUTPUT_ROOT="")
    assert inst.send_command(["version"]) == 3
    [call] = executor.calls
    assert call.output is Output.INHERIT
    assert call.argv[-2:] == ("/usr/bin/bazel", "version")
    assert call.argv[:8] == (
        "docker",
        "exec",
        "-i",
        "-e",
        "COLUMNS=100",
        "-e",
        "LINES=30",
        "-e",
    )


def test_start_builds_image_when_dockerfile_exists_and_runs_container(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    (workspace / "Dockerfile.dazel").touch()
    executor = FakeExecutor()
    inst = instance(workspace, executor)
    assert inst.start() == 0
    verbs = [line.split()[1] for line in executor.lines() if line.startswith("docker ")]
    assert verbs == ["build", "network", "network", "stop", "rm", "run"]
    assert run_file_of(inst.config).read_text(encoding="utf-8") == "dazel\n"


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
    assert not run_file_of(inst.config).exists()


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
    workspace = make_workspace(tmp_path, 'DAZEL_INSTANCE_NAME = "named"\nDAZEL_DOCKER_COMMAND = "podman"\n')
    inst = DockerInstance.from_config({}, workspace)
    assert (inst.instance_name, inst.docker_command) == ("named", "podman")


def legacy_present(name: str = "dazel") -> dict[str, str]:
    return {f"docker ps --all --filter name=^{name}$": f"{name}\n"}


def test_start_removes_a_legacy_container_holding_the_ports(tmp_path: Path) -> None:
    executor = FakeExecutor(captures=legacy_present())
    inst = instance(make_workspace(tmp_path), executor, DAZEL_PER_WORKSPACE_CONTAINER="1", DAZEL_PORTS="1:1")
    assert inst.start() == 0
    lines = executor.lines()
    run = next(i for i, line in enumerate(lines) if line.startswith("docker run"))
    assert lines.index("docker stop dazel") < lines.index("docker rm dazel") < run


def test_start_says_which_legacy_container_it_removes(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    executor = FakeExecutor(captures=legacy_present())
    instance(make_workspace(tmp_path), executor, DAZEL_PER_WORKSPACE_CONTAINER="1").start()
    [record] = [r for r in caplog.records if "legacy" in r.getMessage()]
    assert "'dazel'" in record.getMessage()
    assert "ports" in record.getMessage()


def test_start_leaves_other_containers_alone_in_per_workspace_mode(tmp_path: Path) -> None:
    executor = FakeExecutor()
    instance(make_workspace(tmp_path), executor, DAZEL_PER_WORKSPACE_CONTAINER="1").start()
    assert "docker stop dazel" not in executor.lines()
    assert "docker rm dazel" not in executor.lines()


def test_start_does_not_look_for_a_legacy_container_in_shared_mode(tmp_path: Path) -> None:
    executor = FakeExecutor(captures=legacy_present())
    instance(make_workspace(tmp_path), executor).start()
    assert not any(" --all " in line for line in executor.lines())


def test_start_leaves_the_unsuffixed_container_alone_in_workspace_hex_mode(tmp_path: Path) -> None:
    executor = FakeExecutor(captures=legacy_present())
    inst = instance(make_workspace(tmp_path), executor, DAZEL_WORKSPACE_HEX="1")
    assert inst.instance_name != "dazel"
    inst.start()
    assert "docker rm dazel" not in executor.lines()


def test_start_takes_the_lock_around_every_docker_step(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    executor = FakeExecutor()
    events: list[str] = []

    @contextmanager
    def recording_lock(path: Path, _on_contended: Callable[[], None] | None = None) -> Iterator[None]:
        events.append(f"lock {path.name} after {len(executor.calls)} calls")
        yield
        events.append(f"unlock after {len(executor.calls)} calls")

    monkeypatch.setattr(instance_module, "exclusive_lock", recording_lock)
    workspace = make_workspace(tmp_path)
    (workspace / "Dockerfile.dazel").touch()
    inst = instance(workspace, executor, DAZEL_PER_WORKSPACE_CONTAINER="1")
    assert inst.start() == 0
    assert len(executor.calls) >= 5
    assert events == ["lock .dazel.lock after 0 calls", f"unlock after {len(executor.calls)} calls"]


def started_by_another_dazel_while_waiting(
    inst: DockerInstance, executor: FakeExecutor, monkeypatch: pytest.MonkeyPatch
) -> None:
    @contextmanager
    def lock_released_after_another_start(
        _path: Path, _on_contended: Callable[[], None] | None = None
    ) -> Iterator[None]:
        executor.captures = running(inst)
        run_file_of(inst.config).write_text(f"{inst.instance_name}\n", encoding="utf-8")
        yield

    monkeypatch.setattr(instance_module, "exclusive_lock", lock_released_after_another_start)


def test_start_that_waited_for_the_lock_does_nothing_when_another_dazel_started_the_container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executor = FakeExecutor()
    inst = instance(make_workspace(tmp_path), executor)
    started_by_another_dazel_while_waiting(inst, executor, monkeypatch)

    assert inst.needs_start()
    assert inst.start(only_if_needed=True) == 0

    assert not any(line.startswith(("docker run", "docker stop", "docker rm")) for line in executor.lines())


def test_unconditional_start_still_recreates_the_container(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    executor = FakeExecutor()
    inst = instance(make_workspace(tmp_path), executor)
    started_by_another_dazel_while_waiting(inst, executor, monkeypatch)
    assert inst.start() == 0
    assert any(line.startswith("docker run") for line in executor.lines())


def test_start_logs_once_that_it_waits_for_another_start_up(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    inst = instance(make_workspace(tmp_path), FakeExecutor())
    inst.lock_path.parent.mkdir(parents=True, exist_ok=True)
    holder = inst.lock_path.open("a", encoding="utf-8")
    fcntl.flock(holder, fcntl.LOCK_EX)
    thread = threading.Thread(target=inst.start)
    with caplog.at_level(logging.WARNING, logger="dazel"):
        thread.start()
        deadline = time.monotonic() + 5
        while "Waiting for another dazel start-up" not in caplog.text and time.monotonic() < deadline:
            time.sleep(0.02)
        fcntl.flock(holder, fcntl.LOCK_UN)
        holder.close()
        thread.join(5)
    assert caplog.text.count("Waiting for another dazel start-up") == 1


def test_the_lock_lives_in_the_bazel_output_root(tmp_path: Path) -> None:
    inst = instance(make_workspace(tmp_path), FakeExecutor())
    assert inst.lock_path == tmp_path / "out" / ".dazel.lock"


def test_start_records_the_workspace_next_to_the_mounted_directories(tmp_path: Path) -> None:
    inst = instance(make_workspace(tmp_path), FakeExecutor(), DAZEL_PER_WORKSPACE_CONTAINER="1")
    inst.start()
    base = inst.plan.layout.base
    assert base is not None
    assert (base / "README").read_text(encoding="utf-8").splitlines()[0] == f"WORKSPACE: {inst.plan.workdir}"
    assert base.name == hashlib.md5(str(inst.plan.workdir).encode(), usedforsecurity=False).hexdigest()


def test_start_records_the_workspace_root_when_a_subdirectory_is_mounted(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    nested = workspace / "deep"
    nested.mkdir()
    inst = instance(workspace, FakeExecutor(), DAZEL_PER_WORKSPACE_CONTAINER="1", DAZEL_DIRECTORY=str(nested))
    inst.start()
    base = inst.plan.layout.base
    assert base is not None
    assert (base / "README").read_text(encoding="utf-8").splitlines()[0] == f"WORKSPACE: {workspace.resolve()}"
    assert base.name == hashlib.md5(str(workspace.resolve()).encode(), usedforsecurity=False).hexdigest()


def test_start_writes_no_workspace_record_in_shared_mode(tmp_path: Path) -> None:
    inst = instance(make_workspace(tmp_path), FakeExecutor())
    inst.start()
    assert not (tmp_path / "out" / "README").exists()


@pytest.mark.parametrize("rc_name", [".dazelrc", ".dazelrc.local", "home"], ids=["project", "local", "home"])
@pytest.mark.parametrize("changed", [True, False], ids=["changed", "unchanged"])
def test_needs_start_when_an_rc_file_changed_after_the_run_file(
    tmp_path: Path, isolated_home: Path, rc_name: str, *, changed: bool
) -> None:
    workspace = make_workspace(tmp_path)
    rc = isolated_home / ".dazelrc" if rc_name == "home" else workspace / rc_name
    rc.write_text('DAZEL_SHM_SIZE = "1g"\n', encoding="utf-8")
    executor = FakeExecutor()
    inst = instance(workspace, executor)
    executor.captures = running(inst)
    run_file = run_file_of(inst.config)
    run_file.write_text("dazel\n", encoding="utf-8")
    if changed:
        rc.chmod(0o600)
        if rc.stat().st_ctime <= run_file.stat().st_ctime:
            pytest.skip("filesystem does not advance ctime")
    else:
        assert rc.stat().st_ctime <= run_file.stat().st_ctime
    assert inst.needs_start() is changed
