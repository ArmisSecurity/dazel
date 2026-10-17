from pathlib import Path

import pytest

from dazel.config import (
    Config,
    ConfigError,
    RunDep,
    default_user_output_root,
    load_config,
    load_rc,
)

from conftest import FIXTURES
from fakes import make_workspace


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
    workspace = make_workspace(
        tmp_path, 'import os\nDAZEL_INSTANCE_NAME = "x" + os.sep.join(["", "y"])\nlocal = 1\n'
    )
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


def test_home_is_expanded_in_volumes_ports_and_env_vars(
    tmp_path: Path, isolated_home: Path
) -> None:
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
    ("entry", "expected"),
    [
        ("postgres::armis_postgres", RunDep("postgres", "armis_postgres")),
        ("org/img:1.0", RunDep("org/img:1.0", "dazel_org_img_1.0")),
    ],
)
def test_run_deps(tmp_path: Path, entry: str, expected: RunDep) -> None:
    cfg = load(make_workspace(tmp_path, f"DAZEL_RUN_DEPS = {entry!r}\n"))
    assert cfg.run_deps == (expected,)


def test_relative_paths_resolve_against_the_workspace(tmp_path: Path) -> None:
    rc = 'DAZEL_DOCKERFILE = "./deploy/Dockerfile"\nDAZEL_DOCKER_COMPOSE_FILE = "c.yml"\n'
    rc += 'DAZEL_RUN_FILE = ".run"\n'
    workspace = make_workspace(tmp_path, rc)
    cfg = load(workspace)
    root = workspace.resolve()
    assert cfg.dockerfile == root / "deploy" / "Dockerfile"
    assert cfg.compose_file == root / "c.yml"
    assert cfg.run_file == root / ".run"


@pytest.mark.parametrize(
    ("raw", "expected"), [(None, None), ("True", True), ("False", False), ("0", False)]
)
def test_ports_only_primary_is_tri_state(
    tmp_path: Path,
    raw: str | None,
    expected: bool | None,
) -> None:
    env = {} if raw is None else {"DAZEL_PORTS_ONLY_PRIMARY": raw}
    assert load(make_workspace(tmp_path), env).ports_only_primary is expected


def test_disk_cache_expands_home(tmp_path: Path, isolated_home: Path) -> None:
    cfg = load(
        make_workspace(tmp_path),
        {"HOME": str(isolated_home), "DAZEL_BAZEL_DISK_CACHE": "$HOME/disk"},
    )
    assert cfg.bazel_disk_cache == isolated_home / "disk"


@pytest.mark.parametrize("name", ["armis.dazelrc", "armis_ci.dazelrc"])
def test_armis_rc_files_load_unchanged(tmp_path: Path, isolated_home: Path, name: str) -> None:
    rc = (FIXTURES / name).read_text(encoding="utf-8")
    cfg = load(make_workspace(tmp_path, rc), {"HOME": str(isolated_home)})
    assert cfg.repository == "armis"
    assert cfg.docker_run_privileged is True


def test_armis_local_rc_values(tmp_path: Path, isolated_home: Path) -> None:
    rc = (FIXTURES / "armis.dazelrc").read_text(encoding="utf-8")
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


def test_armis_ci_rc_values(tmp_path: Path, isolated_home: Path) -> None:
    rc = (FIXTURES / "armis_ci.dazelrc").read_text(encoding="utf-8")
    env = {"HOME": str(isolated_home), "PWD": "/w", "OKTA_CLIENT_ID": "id"}
    cfg = load(make_workspace(tmp_path, rc), env)
    assert cfg.command == ("/usr/bin/bazel", "--noworkspace_rc")
    assert cfg.bazel_rc_file == "deploy/.bazelrc"
    assert cfg.workspace_hex is True
    assert cfg.shm_size == "1024m"
    assert (
        "/mnt/jenkins_data/workspace/bazel_disk_cache:/mnt/jenkins_data/workspace/bazel_disk_cache"
        in cfg.volumes
    )
    assert cfg.env_vars == (
        "OKTA_CLIENT_ID=id",
        "OKTA_CLIENT_SECRET=''",
        "CA_CERT_PATH=''",
        "GIT_ASKPASS=/w/.github.com",
    )
