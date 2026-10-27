from pathlib import Path

import pytest

from dazel.config import Config, ConfigError, DiskCache, RunDep, default_user_output_root, load_config, load_rc
from dazel.docker import build_argv
from dazel.plan import make_plan

from fake_support import CI_DAZELRC, LOCAL_DAZELRC, make_workspace


def load(workspace: Path, env: dict[str, str] | None = None) -> Config:
    return load_config(env or {}, workspace)


def test_defaults_without_rc_file(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    cfg = load(workspace)
    assert cfg == Config(
        directory=workspace.resolve(),
        dockerfile=workspace.resolve() / "Dockerfile.dazel",
        run_file=workspace.resolve() / ".dazel_run",
        bazel_user_output_root=default_user_output_root(),
    )


def test_rc_file_is_executed_python(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path, 'import os\nDAZEL_INSTANCE_NAME = "x" + os.sep.join(["", "y"])\nlocal = 1\n')
    assert load(workspace).instance_name == "x/y"


def test_load_rc_keeps_only_dazel_keys(tmp_path: Path) -> None:
    rc = tmp_path / "rc"
    rc.write_text("DAZEL_A = 1\nother = 2\n", encoding="utf-8")
    assert load_rc(rc) == {"DAZEL_A": 1}


def test_environment_overrides_rc_file(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path, 'DAZEL_PLATFORM = "linux/arm64"\nDAZEL_SHM_SIZE = "1g"\n')
    cfg = load(workspace, {"DAZEL_PLATFORM": "linux/amd64"})
    assert (cfg.platform, cfg.shm_size) == ("linux/amd64", "1g")


def test_rc_file_env_var_selects_another_file(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path, 'DAZEL_REPOSITORY = "from-default"\n')
    other = tmp_path / "other.rc"
    other.write_text('DAZEL_REPOSITORY = "from-other"\n', encoding="utf-8")
    assert load(workspace, {"DAZEL_RC_FILE": str(other)}).repository == "from-other"


def test_directory_env_var_selects_the_workspace_search_start(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    nested = workspace / "deep"
    nested.mkdir()
    cfg = load_config({"DAZEL_DIRECTORY": str(nested)}, tmp_path)
    assert cfg.directory == workspace.resolve()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("a,b", ("a", "b")),
        (" a , b ,, ", ("a", "b")),
        (["a", "b"], ("a", "b")),
        (("a",), ("a",)),
        ("", ()),
    ],
)
def test_comma_lists_accept_strings_and_iterables(
    tmp_path: Path, value: str | list[str] | tuple[str, ...], expected: tuple[str, ...]
) -> None:
    workspace = make_workspace(tmp_path, f"DAZEL_PORTS = {value!r}\n")
    assert load(workspace).ports == expected


def test_non_iterable_list_value_is_rejected(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path, "DAZEL_VOLUMES = 5\n")
    with pytest.raises(ConfigError, match="DAZEL_VOLUMES"):
        load(workspace)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("True", True), ("1", True), ("yes", True), ("False", False), ("0", False), ("", False)],
)
def test_boolean_env_values(tmp_path: Path, raw: str, expected: bool) -> None:
    cfg = load(make_workspace(tmp_path), {"DAZEL_DOCKER_RUN_PRIVILEGED": raw})
    assert cfg.docker_run_privileged is expected


def test_python_boolean_in_rc_file(tmp_path: Path) -> None:
    cfg = load(make_workspace(tmp_path, "DAZEL_DOCKER_RUN_PRIVILEGED = True\n"))
    assert cfg.docker_run_privileged is True


def test_home_is_expanded_in_volumes_ports_and_env_vars(tmp_path: Path, isolated_home: Path) -> None:
    rc = 'DAZEL_VOLUMES = "$HOME/.aws:/root/.aws,${HOME}/.ssh:/root/.ssh"\n'
    rc += "DAZEL_ENV_VARS = \"A=${UNSET_VAR:-''},B=$HOME\"\n"
    cfg = load(make_workspace(tmp_path, rc), {"HOME": str(isolated_home)})
    assert cfg.volumes == (f"{isolated_home}/.aws:/root/.aws", f"{isolated_home}/.ssh:/root/.ssh")
    assert cfg.env_vars == ("A=''", f"B={isolated_home}")


def test_command_lines_are_shell_split(tmp_path: Path) -> None:
    rc = 'DAZEL_COMMAND = "/usr/bin/bazel --noworkspace_rc"\n'
    rc += "DAZEL_DOCKER_BUILD_ARGS = \"--platform=linux/arm64 --build-arg 'A=b c'\"\n"
    rc += 'DAZEL_DOCKER_COMMAND = "sudo docker"\n'
    cfg = load(make_workspace(tmp_path, rc))
    assert cfg.command == ("/usr/bin/bazel", "--noworkspace_rc")
    assert cfg.docker_build_args == ("--platform=linux/arm64", "--build-arg", "A=b c")
    assert cfg.docker_command == ("sudo", "docker")


@pytest.mark.parametrize(
    ("entry", "network_line", "expected"),
    [
        ("postgres::armis_postgres", "", RunDep("postgres", "armis_postgres")),
        ("org/img:1.0", "", RunDep("org/img:1.0", "dazel_org_img_1.0")),
        ("org/img:1.0", 'DAZEL_NETWORK = "net"\n', RunDep("org/img:1.0", "net_org_img_1.0")),
        # Upstream named the dependency from the network *after* the compose project prefix.
        (
            "org/img:1.0",
            'DAZEL_NETWORK = "net"\nDAZEL_DOCKER_COMPOSE_FILE = "c.yml"\nDAZEL_DOCKER_COMPOSE_PROJECT_NAME = "proj"\n',
            RunDep("org/img:1.0", "proj_net_org_img_1.0"),
        ),
        (
            "img",
            'DAZEL_DOCKER_COMPOSE_FILE = "c.yml"\nDAZEL_NETWORK = "host"\n',
            RunDep("img", "host_img"),
        ),
    ],
    ids=["named", "default-network", "custom-network", "compose-prefixed-network", "predefined-network-unprefixed"],
)
def test_run_deps(tmp_path: Path, entry: str, network_line: str, expected: RunDep) -> None:
    cfg = load(make_workspace(tmp_path, f"DAZEL_RUN_DEPS = {entry!r}\n{network_line}"))
    assert make_plan(cfg).run_deps == (expected,)


def test_directory_env_var_is_the_mounted_working_directory(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    nested = workspace / "deep"
    nested.mkdir()
    cfg = load_config({"DAZEL_DIRECTORY": str(nested)}, tmp_path)
    plan = make_plan(cfg)

    assert cfg.directory == workspace.resolve()
    assert plan.workdir == nested.resolve()
    assert f"{nested.resolve()}:{nested.resolve()}" in plan.volumes
    assert f"{workspace.resolve()}:{workspace.resolve()}" not in plan.volumes


def test_without_directory_the_discovered_workspace_root_is_mounted(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    assert make_plan(load(workspace)).workdir == workspace.resolve()


@pytest.mark.parametrize("env", [{"DAZEL_RUN_FILE": ""}, {}], ids=["env", "rc"])
def test_empty_run_file_disables_the_run_file(tmp_path: Path, env: dict[str, str]) -> None:
    rc = 'DAZEL_RUN_FILE = ""\n' if not env else ""
    assert load(make_workspace(tmp_path, rc), env).run_file is None


def test_relative_paths_resolve_against_the_workspace(tmp_path: Path) -> None:
    rc = 'DAZEL_DOCKERFILE = "./deploy/Dockerfile"\nDAZEL_DOCKER_COMPOSE_FILE = "c.yml"\n'
    rc += 'DAZEL_RUN_FILE = ".run"\n'
    workspace = make_workspace(tmp_path, rc)
    cfg = load(workspace)
    root = workspace.resolve()
    assert cfg.dockerfile == root / "deploy" / "Dockerfile"
    assert cfg.compose_file == root / "c.yml"
    assert cfg.run_file == root / ".run"


@pytest.mark.parametrize(("raw", "expected"), [(None, None), ("True", True), ("False", False), ("0", False)])
def test_ports_only_primary_is_tri_state(
    tmp_path: Path,
    raw: str | None,
    expected: bool | None,
) -> None:
    env = {} if raw is None else {"DAZEL_PORTS_ONLY_PRIMARY": raw}
    assert load(make_workspace(tmp_path), env).ports_only_primary is expected


@pytest.mark.parametrize(
    ("spec", "host", "container"),
    [
        ("$HOME/disk", "{home}/disk", "{home}/disk"),
        ("$HOME/disk:/root/.cache/disk", "{home}/disk", "/root/.cache/disk"),
        ("/abs/disk", "/abs/disk", "/abs/disk"),
        ("rel/disk", "{ws}/rel/disk", "{ws}/rel/disk"),
    ],
)
def test_disk_cache_spec(tmp_path: Path, isolated_home: Path, spec: str, host: str, container: str) -> None:
    workspace = make_workspace(tmp_path)
    cfg = load(workspace, {"HOME": str(isolated_home), "DAZEL_BAZEL_DISK_CACHE": spec})
    names = {"home": str(isolated_home), "ws": str(workspace.resolve())}
    assert cfg.bazel_disk_cache == DiskCache(Path(host.format(**names)), container.format(**names))


def test_disk_cache_container_path_must_be_absolute(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="BAZEL_DISK_CACHE"):
        load(make_workspace(tmp_path), {"DAZEL_BAZEL_DISK_CACHE": "/host:relative"})


def test_no_disk_cache_by_default(tmp_path: Path) -> None:
    assert load(make_workspace(tmp_path)).bazel_disk_cache is None


@pytest.mark.parametrize("rc_file", [LOCAL_DAZELRC, CI_DAZELRC], ids=["local", "ci"])
def test_armis_rc_files_load_unchanged(tmp_path: Path, isolated_home: Path, rc_file: Path) -> None:
    rc = rc_file.read_text(encoding="utf-8")
    cfg = load(make_workspace(tmp_path, rc), {"HOME": str(isolated_home)})
    assert cfg.repository == "armis"
    assert cfg.docker_run_privileged is True


def test_armis_local_rc_values(tmp_path: Path, isolated_home: Path) -> None:
    rc = LOCAL_DAZELRC.read_text(encoding="utf-8")
    cfg = load(make_workspace(tmp_path, rc), {"HOME": str(isolated_home)})
    assert cfg.network == "default"
    assert cfg.run_deps == (
        RunDep("postgres", "armis_postgres"),
        RunDep("rabbitmq", "armis_rabbitmq"),
    )
    assert cfg.compose_project_name == "dazel"
    assert cfg.ports == ("127.0.0.1:20000-20006:20000-20006", "127.0.0.1:4445:4445")
    assert f"{isolated_home}/.aws:/root/.aws" in cfg.volumes
    assert f"{isolated_home}/.docker/config.json:/root/.docker/config.json" in cfg.volumes
    assert not any("cli-plugins" in volume for volume in cfg.volumes)
    assert not any("$" in volume for volume in cfg.volumes)
    assert cfg.compose_file == cfg.directory / "deploy/build/docker-compose.dazel.yml"
    assert cfg.per_workspace_container is True
    assert cfg.bazel_disk_cache is None
    cache_volume = f"{isolated_home}/.cache/bazel-disk:/root/.cache/bazel-disk"
    assert cfg.volumes.count(cache_volume) == 1
    assert (isolated_home / ".cache/bazel-disk").is_dir()


def test_armis_ci_rc_values(tmp_path: Path, isolated_home: Path) -> None:
    rc = CI_DAZELRC.read_text(encoding="utf-8")
    workspace = make_workspace(tmp_path, rc)
    env = {"HOME": str(isolated_home), "PWD": "/stale", "OKTA_CLIENT_ID": "id"}
    cfg = load(workspace, env)
    assert cfg.command == ("/usr/bin/bazel", "--noworkspace_rc")
    assert cfg.bazel_rc_file == "deploy/.bazelrc"
    assert cfg.workspace_hex is True
    assert cfg.per_workspace_container is False
    assert cfg.bazel_disk_cache is None
    assert cfg.shm_size == "1024m"
    assert "/mnt/jenkins_data/workspace/bazel_disk_cache:/mnt/jenkins_data/workspace/bazel_disk_cache" in cfg.volumes
    assert cfg.env_vars == (
        "OKTA_CLIENT_ID=id",
        "OKTA_CLIENT_SECRET=",
        "CA_CERT_PATH=",
        f"GIT_ASKPASS={workspace}/.github.com",
    )


@pytest.mark.parametrize(
    ("setting", "expected"),
    [
        ('"$HOME/run"', "{home}/run"),
        ('"~/run"', "{home}/run"),
        ('"${RUN_DIR:-state}/id"', "{workspace}/state/id"),
        ('".dazel_run"', "{workspace}/.dazel_run"),
    ],
)
def test_run_file_expands_variables_and_the_home_directory(
    tmp_path: Path, isolated_home: Path, setting: str, expected: str
) -> None:
    workspace = make_workspace(tmp_path, f"DAZEL_RUN_FILE = {setting}\n")
    cfg = load(workspace, {"HOME": str(isolated_home)})
    assert cfg.run_file == Path(expected.format(home=isolated_home, workspace=workspace.resolve()))


@pytest.mark.parametrize("key", ["DOCKERFILE", "DOCKER_COMPOSE_FILE"])
def test_file_settings_expand_variables_and_the_home_directory(tmp_path: Path, isolated_home: Path, key: str) -> None:
    workspace = make_workspace(tmp_path, f'DAZEL_{key} = "~/$NAME"\n')
    cfg = load(workspace, {"HOME": str(isolated_home), "NAME": "file"})
    value = cfg.dockerfile if key == "DOCKERFILE" else cfg.compose_file
    assert value == isolated_home / "file"


def test_pwd_in_a_value_is_the_real_working_directory_not_the_stale_environment_one(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path, 'DAZEL_ENV_VARS = "ASKPASS=${PWD}/x"\n')
    assert load(workspace, {"PWD": "/stale"}).env_vars == (f"ASKPASS={workspace}/x",)


CI_CACHE_FROM = "--cache-from 123456789012.dkr.ecr.us-east-1.amazonaws.com/armis/dazel"


@pytest.mark.parametrize(
    ("previous", "expected"),
    [
        ("dazel_abc123", ["--cache-from", "armis/dazel_abc123"]),
        ("", []),
    ],
)
def test_the_build_args_ci_passes_reach_docker_build_as_plain_flags(
    tmp_path: Path, previous: str, expected: list[str]
) -> None:
    prev_flag = f" --cache-from armis/{previous}" if previous else ""
    workspace = make_workspace(tmp_path)
    cfg = load(workspace, {"DAZEL_DOCKER_BUILD_ARGS": f"{CI_CACHE_FROM}{prev_flag}"})
    argv = build_argv(cfg, make_plan(cfg))
    flags = argv[argv.index("build") + 1 : argv.index("-t")]
    assert flags == ["--cache-from", CI_CACHE_FROM.split()[1], *expected]


SHM = 'DAZEL_SHM_SIZE = "{}"\n'


@pytest.mark.parametrize(
    ("rc_files", "env", "expected"),
    [
        ((SHM.format("1g"), "", ""), {}, "1g"),
        ((SHM.format("1g"), SHM.format("2g"), ""), {}, "2g"),
        ((SHM.format("1g"), SHM.format("2g"), SHM.format("3g")), {}, "3g"),
        (("", SHM.format("2g"), SHM.format("3g")), {"DAZEL_SHM_SIZE": "4g"}, "4g"),
        (("", SHM.format("2g"), 'DAZEL_PLATFORM = "linux/arm64"\n'), {}, "2g"),
    ],
    ids=["home", "project-over-home", "local-over-project", "env-over-local", "local-leaves-other-keys"],
)
def test_rc_files_layer_home_project_local_then_environment(
    tmp_path: Path, isolated_home: Path, rc_files: tuple[str, str, str], env: dict[str, str], expected: str
) -> None:
    home_rc, project_rc, local_rc = rc_files
    workspace = make_workspace(tmp_path, project_rc)
    if home_rc:
        (isolated_home / ".dazelrc").write_text(home_rc, encoding="utf-8")
    if local_rc:
        (workspace / ".dazelrc.local").write_text(local_rc, encoding="utf-8")
    assert load(workspace, env).shm_size == expected


def test_rc_files_lists_only_the_files_read_lowest_precedence_first(tmp_path: Path, isolated_home: Path) -> None:
    workspace = make_workspace(tmp_path, 'DAZEL_SHM_SIZE = "2g"\n')
    (isolated_home / ".dazelrc").write_text("", encoding="utf-8")
    (workspace / ".dazelrc.local").write_text("", encoding="utf-8")
    assert load(workspace).rc_files == (
        isolated_home / ".dazelrc",
        workspace / ".dazelrc",
        workspace / ".dazelrc.local",
    )
    (workspace / ".dazelrc.local").unlink()
    assert load(workspace).rc_files == (isolated_home / ".dazelrc", workspace / ".dazelrc")


def test_a_list_in_the_local_rc_replaces_the_project_list(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path, 'DAZEL_GPUS = ["0", "1"]\n')
    (workspace / ".dazelrc.local").write_text('DAZEL_GPUS = ["2"]\n', encoding="utf-8")
    assert load(workspace).gpus == ("2",)


def test_the_local_rc_still_applies_over_a_selected_rc_file(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    selected = tmp_path / "ci.dazelrc"
    selected.write_text('DAZEL_SHM_SIZE = "2g"\nDAZEL_PLATFORM = "linux/amd64"\n', encoding="utf-8")
    (workspace / ".dazelrc.local").write_text('DAZEL_SHM_SIZE = "3g"\n', encoding="utf-8")
    cfg = load(workspace, {"DAZEL_RC_FILE": str(selected)})
    assert (cfg.shm_size, cfg.platform) == ("3g", "linux/amd64")


def test_a_workspace_at_home_reads_its_rc_file_once(isolated_home: Path) -> None:
    (isolated_home / "WORKSPACE").touch()
    (isolated_home / ".dazelrc").write_text('DAZEL_SHM_SIZE = "1g"\n', encoding="utf-8")
    assert load(isolated_home).rc_files == (isolated_home / ".dazelrc",)


@pytest.mark.parametrize(
    ("value", "expected"),
    [("", None), ("docker", "docker"), ("/abs/context", "/abs/context")],
    ids=["unset", "relative", "absolute"],
)
def test_build_directory_resolves_against_the_workspace(tmp_path: Path, value: str, expected: str | None) -> None:
    workspace = make_workspace(tmp_path)
    cfg = load(workspace, {"DAZEL_BUILD_DIRECTORY": value} if value else {})
    assert cfg.build_directory == (None if expected is None else workspace.resolve() / expected)


@pytest.mark.parametrize(
    ("rc", "expected"),
    [
        ("", ()),
        ('DAZEL_GROUPS = "docker, video"\n', ("docker", "video")),
        ('DAZEL_GROUPS = ["docker", 44]\n', ("docker", "44")),
    ],
    ids=["unset", "comma-string", "list"],
)
def test_groups_accept_a_comma_string_or_a_list(tmp_path: Path, rc: str, expected: tuple[str, ...]) -> None:
    assert load(make_workspace(tmp_path, rc)).groups == expected
