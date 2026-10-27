"""End to end tests against a real docker daemon: skipped when docker (or git) is unavailable."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from dazel import cli
from dazel.clean import UnsafeCleanError
from docker_support import (
    BASE_IMAGE,
    Lab,
    compose_command,
    container_exists,
    container_id,
    container_running,
    container_started_at,
    created_containers,
    daemon_time,
    docker,
    free_port,
    mount_sources,
    skip_unless_required,
)

pytestmark = pytest.mark.integration


def compose_settings() -> dict[str, object]:
    command = compose_command()
    if command is None:
        skip_unless_required("docker-compose or the docker compose plugin")
    return {"DOCKER_COMPOSE_FILE": "compose.yml", "DOCKER_COMPOSE_COMMAND": command, "NETWORK": "default"}


def test_per_workspace_containers_share_an_image_and_leave_each_other_alone(lab: Lab) -> None:
    primary = lab.primary()
    first, second = lab.instance(primary), lab.instance(lab.linked(primary))
    assert first.start() == 0
    before = (container_id(first.instance_name), container_started_at(first.instance_name))
    assert second.start() == 0

    assert first.instance_name != second.instance_name
    assert first.instance_name.startswith(f"{lab.instance_name}_")
    assert container_running(first.instance_name)
    assert container_running(second.instance_name)
    assert docker("inspect", "--format", "{{.Config.Image}}", first.instance_name) == lab.image_ref
    assert docker("inspect", "--format", "{{.Config.Image}}", second.instance_name) == lab.image_ref
    assert len(docker("image", "ls", "--quiet", lab.image_ref).split()) == 1
    assert (container_id(first.instance_name), container_started_at(first.instance_name)) == before
    assert not first.needs_start()
    assert not second.needs_start()


def test_shared_container_is_recreated_by_another_workspace_without_the_flag(lab: Lab) -> None:
    primary = lab.primary(PER_WORKSPACE_CONTAINER=False)
    first, second = lab.instance(primary), lab.instance(lab.linked(primary))
    assert first.start() == 0
    original = container_id(first.instance_name)

    assert first.instance_name == second.instance_name
    assert second.needs_start()
    assert second.start() == 0
    assert container_id(second.instance_name) != original
    assert first.needs_start()


def test_only_the_primary_checkout_publishes_ports(lab: Lab) -> None:
    port = free_port()
    primary = lab.primary(PORTS=f"127.0.0.1:{port}:8000")
    first, second = lab.instance(primary), lab.instance(lab.linked(primary))
    assert first.start() == 0
    assert second.start() == 0

    assert f"127.0.0.1:{port}" in docker("port", first.instance_name)
    assert docker("port", second.instance_name) == ""


def test_ports_are_published_everywhere_when_only_primary_is_disabled(lab: Lab) -> None:
    primary = lab.primary(PORTS=f"127.0.0.1:{free_port()}:8000", PORTS_ONLY_PRIMARY=False)
    linked = lab.instance(lab.linked(primary))
    assert linked.start() == 0
    assert docker("port", linked.instance_name) != ""


def test_compose_services_and_network_are_shared_and_never_recreated(lab: Lab) -> None:
    primary = lab.primary(**compose_settings())
    first, second = lab.instance(primary), lab.instance(lab.linked(primary))
    assert first.start() == 0
    service = f"{lab.project}-svc-1"
    service_id = container_id(service)
    assert second.start() == 0

    assert container_id(service) == service_id
    assert docker("ps", "--filter", f"label=com.docker.compose.project={lab.project}", "--quiet").split() == [
        service_id[:12]
    ]
    network = f"{lab.project}_default"
    for instance in (first, second):
        attached = docker("inspect", "--format", "{{json .NetworkSettings.Networks}}", instance.instance_name)
        assert network in attached


def test_disk_cache_is_created_and_mounted_at_the_same_path(lab: Lab) -> None:
    cache = lab.root / "disk" / "cache"
    instance = lab.instance(lab.primary(BAZEL_DISK_CACHE=str(cache)))
    assert not cache.exists()
    assert instance.start() == 0
    assert cache.is_dir()

    (cache / "from-host").write_text("host", encoding="utf-8")
    assert docker("exec", instance.instance_name, "cat", f"{cache}/from-host") == "host"
    docker("exec", instance.instance_name, "sh", "-c", f"echo container > {cache}/from-container")
    assert (cache / "from-container").read_text(encoding="utf-8").strip() == "container"


def test_disk_cache_can_be_mounted_at_a_different_container_path(lab: Lab) -> None:
    cache = lab.root / "disk"
    instance = lab.instance(lab.primary(BAZEL_DISK_CACHE=f"{cache}:/root/.cache/bazel-disk"))
    assert instance.start() == 0
    assert cache.is_dir()

    docker("exec", instance.instance_name, "sh", "-c", "echo hi > /root/.cache/bazel-disk/marker")
    assert (cache / "marker").read_text(encoding="utf-8").strip() == "hi"


def test_run_file_names_the_container_for_docker_exec(lab: Lab) -> None:
    workspace = lab.primary()
    instance = lab.instance(workspace)
    assert instance.start() == 0

    name = (workspace / ".dazel_run").read_text(encoding="utf-8").strip()
    assert name == instance.instance_name
    assert docker("exec", name, "cat", "/marker") == "tiny"


def test_the_cli_reuses_the_running_container_and_forwards_exit_codes(
    lab: Lab, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = lab.primary()
    monkeypatch.chdir(workspace)
    assert cli.main(["true"]) == 0
    name = lab.instance(workspace).instance_name
    before = container_id(name)

    assert cli.main(["sh", "-c", "exit 7"]) == 7
    assert container_id(name) == before


def test_clean_removes_only_this_workspace(lab: Lab) -> None:
    primary = lab.primary(**compose_settings())
    linked_dir = lab.linked(primary)
    first, second = lab.instance(primary), lab.instance(linked_dir)
    assert first.start() == 0
    assert second.start() == 0
    second_base = second.plan.layout.base
    assert second_base is not None
    assert second_base.is_dir()
    (second_base / "execroot").mkdir(exist_ok=True)
    (second_base / "execroot").chmod(0o500)

    assert second.clean_workspace() == 0

    assert not container_exists(second.instance_name)
    assert not second_base.exists()
    assert not (linked_dir / ".dazel_run").exists()
    assert container_running(first.instance_name)
    assert first.plan.layout.base is not None
    assert first.plan.layout.base.is_dir()
    assert container_running(f"{lab.project}-svc-1")
    assert docker("image", "ls", "--quiet", lab.image_ref) != ""


def start_legacy_container(lab: Lab, port: int) -> None:
    """Start the pre-per-workspace shared container: unsuffixed name, holding the published port."""
    docker("run", "-d", "--name", lab.instance_name, "-p", f"127.0.0.1:{port}:8000", BASE_IMAGE, "sleep", "600")


def test_a_legacy_container_holding_the_ports_is_replaced(lab: Lab) -> None:
    port = free_port()
    start_legacy_container(lab, port)
    instance = lab.instance(lab.primary(PORTS=f"127.0.0.1:{port}:8000"))
    assert container_running(lab.instance_name)

    assert instance.start() == 0

    assert not container_exists(lab.instance_name)
    assert container_running(instance.instance_name)
    assert f"127.0.0.1:{port}" in docker("port", instance.instance_name)


def test_the_container_sees_the_workspace_at_the_host_realpath_that_the_marker_records(lab: Lab) -> None:
    primary = lab.primary()
    instance = lab.instance(primary)
    assert instance.start() == 0
    base = instance.plan.layout.base
    assert base is not None

    inside = docker("exec", instance.instance_name, "pwd", "-P")
    assert inside == str(primary.resolve())
    assert (base / "README").read_text(encoding="utf-8").splitlines()[0] == f"WORKSPACE: {inside}"


def test_clean_legacy_refuses_until_the_legacy_container_is_gone_then_keeps_workspace_bases(lab: Lab) -> None:
    start_legacy_container(lab, free_port())
    primary = lab.primary()
    root = lab.output_root
    for name in ("external", "execroot", "action_cache"):
        (root / name).mkdir(parents=True)
    instance = lab.instance(primary)
    with pytest.raises(UnsafeCleanError, match="legacy container"):
        instance.clean_legacy(delete=True)
    assert (root / "execroot").is_dir()

    assert instance.start() == 0
    base = instance.plan.layout.base
    assert base is not None
    removed = instance.clean_legacy(delete=True)

    assert {path.name for path in removed} >= {"external", "execroot", "action_cache"}
    assert not (root / "execroot").exists()
    assert base.is_dir()
    assert container_running(instance.instance_name)


def test_starting_from_another_worktree_does_not_recreate_the_compose_sidecar(lab: Lab) -> None:
    primary = lab.primary(**compose_settings())
    first, second = lab.instance(primary), lab.instance(lab.linked(primary, "worktree-b"))
    assert first.start() == 0
    service = f"{lab.project}-svc-1"
    original = container_id(service)
    assert mount_sources(service) == [str(primary.resolve() / "data")]

    assert second.start() == 0

    assert container_id(service) == original
    assert mount_sources(service) == [str(primary.resolve() / "data")]


def test_editing_the_compose_file_does_recreate_the_sidecar(lab: Lab) -> None:
    primary = lab.primary(**compose_settings())
    linked = lab.linked(primary, "worktree-b")
    first, second = lab.instance(primary), lab.instance(linked)
    assert first.start() == 0
    service = f"{lab.project}-svc-1"
    original = container_id(service)

    compose = linked / "compose.yml"
    compose.write_text(
        compose.read_text(encoding="utf-8") + "    environment:\n      CHANGED: 'yes'\n", encoding="utf-8"
    )
    assert second.start() == 0

    assert container_id(service) != original
    assert "CHANGED=yes" in docker("inspect", "--format", "{{json .Config.Env}}", service)
    assert mount_sources(service) == [str(primary.resolve() / "data")]


def test_worktrees_starting_together_share_one_set_of_sidecars(lab: Lab) -> None:
    primary = lab.primary(**compose_settings())
    instances = [lab.instance(primary), lab.instance(lab.linked(primary, "worktree-b"))]

    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = list(pool.map(lambda instance: instance.start(), instances))

    assert codes == [0, 0]
    sidecars = docker("ps", "--filter", f"label=com.docker.compose.project={lab.project}", "--quiet").split()
    assert len(sidecars) == 1
    assert all(container_running(instance.instance_name) for instance in instances)


def test_dazels_started_together_in_one_workspace_create_the_container_once(lab: Lab) -> None:
    workspace = lab.primary()
    instances = [lab.instance(workspace), lab.instance(workspace)]
    assert all(instance.needs_start() for instance in instances)
    since = daemon_time()

    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = list(pool.map(lambda instance: instance.start(only_if_needed=True), instances))

    assert codes == [0, 0]
    name = instances[0].instance_name
    assert len(created_containers(name, since, daemon_time())) == 1
    assert container_running(name)
    assert not instances[0].needs_start()
