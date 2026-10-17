"""Configuration: ``.dazelrc`` (executed Python) overlaid with ``DAZEL_*`` environment variables."""

import getpass
import shlex
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dazel.env import expand_variables
from dazel.workspace import find_workspace

RC_FILE_NAME = ".dazelrc"
ENV_PREFIX = "DAZEL_"
FALSE_WORDS = frozenset({"", "0", "false", "no", "off", "none"})

DEFAULT_INSTANCE_NAME = "dazel"
DEFAULT_IMAGE_NAME = "dazel"
DEFAULT_RUN_COMMAND = "/bin/bash"
DEFAULT_DOCKER_COMMAND = "docker"
DEFAULT_DOCKERFILE = "Dockerfile.dazel"
DEFAULT_REPOSITORY = "dazel"
DEFAULT_COMMAND = "/usr/bin/bazel"
DEFAULT_NETWORK = "dazel"
DEFAULT_COMPOSE_COMMAND = "docker-compose"
DEFAULT_COMPOSE_PROJECT_NAME = "dazel"
DEFAULT_RUN_FILE = ".dazel_run"

RawConfig = dict[str, Any]


class ConfigError(ValueError):
    """Raised when a configuration value has an unusable type."""


@dataclass(frozen=True, slots=True)
class RunDep:
    """A container started next to the dazel container when no compose file is configured."""

    image: str
    name: str


@dataclass(frozen=True, slots=True)
class Config:
    """Fully resolved dazel configuration; every ``DAZEL_*`` key maps to one field."""

    directory: Path
    instance_name: str = DEFAULT_INSTANCE_NAME
    image_name: str = DEFAULT_IMAGE_NAME
    run_command: tuple[str, ...] = (DEFAULT_RUN_COMMAND,)
    docker_command: tuple[str, ...] = (DEFAULT_DOCKER_COMMAND,)
    dockerfile: Path = Path(DEFAULT_DOCKERFILE)
    repository: str = DEFAULT_REPOSITORY
    command: tuple[str, ...] = (DEFAULT_COMMAND,)
    volumes: tuple[str, ...] = ()
    ports: tuple[str, ...] = ()
    env_vars: tuple[str, ...] = ()
    gpus: tuple[str, ...] = ()
    platform: str = ""
    shm_size: str = ""
    network: str = DEFAULT_NETWORK
    run_deps: tuple[RunDep, ...] = ()
    compose_file: Path | None = None
    compose_command: tuple[str, ...] = (DEFAULT_COMPOSE_COMMAND,)
    compose_project_name: str = DEFAULT_COMPOSE_PROJECT_NAME
    compose_services: tuple[str, ...] = ()
    bazel_rc_file: str = ""
    bazel_user_output_root: str = ""
    docker_run_privileged: bool = False
    docker_machine: str = ""
    run_file: Path = Path(DEFAULT_RUN_FILE)
    workspace_hex: bool = False
    delegated_volume: bool = True
    user: str = ""
    docker_build_args: tuple[str, ...] = ()
    per_workspace_container: bool = False
    ports_only_primary: bool | None = None
    bazel_disk_cache: Path | None = None


def default_user_output_root() -> str:
    """Return bazel's conventional per-user output root."""
    return str(Path("~/.cache/bazel").expanduser() / f"_bazel_{getpass.getuser()}")


def load_rc(path: Path) -> RawConfig:
    """Execute a ``.dazelrc`` file and return the names it defines."""
    namespace: RawConfig = {}
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)  # noqa: S102  # .dazelrc is Python by contract
    return {key: value for key, value in namespace.items() if key.startswith(ENV_PREFIX)}


def load_config(env: Mapping[str, str], cwd: Path) -> Config:
    """Build the configuration for the workspace containing ``cwd``.

    Precedence, lowest to highest: defaults, ``.dazelrc``, ``DAZEL_*`` environment variables.
    ``DAZEL_RC_FILE`` selects another rc file and ``DAZEL_DIRECTORY`` the search start.
    """
    directory = find_workspace(Path(env.get("DAZEL_DIRECTORY", cwd)))
    rc_path = Path(env.get("DAZEL_RC_FILE", directory / RC_FILE_NAME))
    raw = load_rc(rc_path) if rc_path.exists() else {}
    raw.update({k: v for k, v in env.items() if k.startswith(ENV_PREFIX)})
    return resolve(raw, directory, env)


def _split_words(key: str, value: object) -> tuple[str, ...]:
    """Split a comma separated string, or accept any iterable of strings."""
    if isinstance(value, str):
        items: Iterable[object] = value.split(",")
    elif isinstance(value, Iterable):
        items = value
    else:
        msg = f"{key} must be a comma-separated string or an iterable of strings"
        raise ConfigError(msg)
    return tuple(text for item in items if (text := str(item).strip()))


def _split_argv(value: object) -> tuple[str, ...]:
    """Split a command line the way a shell would; accept ready-made sequences."""
    if isinstance(value, str):
        return tuple(shlex.split(value))
    return tuple(str(part) for part in value) if isinstance(value, Iterable) else ()


def _to_flag(value: object, *, default: bool) -> bool:
    """Interpret booleans, including the strings an environment variable can only hold."""
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() not in FALSE_WORDS
    return bool(value)


def _run_dep(entry: str, network: str) -> RunDep:
    image, separator, name = entry.partition("::")
    if separator:
        return RunDep(image, name)
    return RunDep(entry, f"{network}_{entry.replace('/', '_').replace(':', '_')}")


class _Source:
    """Typed access to raw ``DAZEL_*`` values by their unprefixed key."""

    def __init__(self, raw: RawConfig, env: Mapping[str, str]) -> None:
        self._raw = raw
        self._env = env

    def _get(self, key: str) -> object:
        return self._raw.get(ENV_PREFIX + key)

    def text(self, key: str, default: str = "") -> str:
        value = self._get(key)
        return default if value is None else str(value)

    def argv(self, key: str, default: str = "") -> tuple[str, ...]:
        return _split_argv(self.text(key, default))

    def words(self, key: str) -> tuple[str, ...]:
        return _split_words(ENV_PREFIX + key, self._get(key) or ())

    def expanded(self, key: str) -> tuple[str, ...]:
        return tuple(expand_variables(word, self._env) for word in self.words(key))

    def flag(self, key: str, *, default: bool) -> bool:
        return _to_flag(self._get(key), default=default)

    def path(self, key: str, directory: Path) -> Path | None:
        value = self.text(key)
        if not value:
            return None
        return directory / Path(expand_variables(value, self._env)).expanduser()


def resolve(raw: RawConfig, directory: Path, env: Mapping[str, str]) -> Config:
    """Turn raw ``DAZEL_*`` values into a validated ``Config``.

    Variables such as ``$HOME`` in volumes, ports and environment entries are expanded from ``env``.
    """
    source = _Source(raw, env)
    network = source.text("NETWORK", DEFAULT_NETWORK)
    only_primary = source.text("PORTS_ONLY_PRIMARY")
    return Config(
        directory=directory,
        instance_name=source.text("INSTANCE_NAME", DEFAULT_INSTANCE_NAME),
        image_name=source.text("IMAGE_NAME", DEFAULT_IMAGE_NAME),
        run_command=source.argv("RUN_COMMAND", DEFAULT_RUN_COMMAND),
        docker_command=source.argv("DOCKER_COMMAND", DEFAULT_DOCKER_COMMAND),
        dockerfile=source.path("DOCKERFILE", directory) or directory / DEFAULT_DOCKERFILE,
        repository=source.text("REPOSITORY", DEFAULT_REPOSITORY),
        command=source.argv("COMMAND", DEFAULT_COMMAND),
        volumes=source.expanded("VOLUMES"),
        ports=source.expanded("PORTS"),
        env_vars=source.expanded("ENV_VARS"),
        gpus=source.words("GPUS"),
        platform=source.text("PLATFORM"),
        shm_size=source.text("SHM_SIZE"),
        network=network,
        run_deps=tuple(_run_dep(entry, network) for entry in source.words("RUN_DEPS")),
        compose_file=source.path("DOCKER_COMPOSE_FILE", directory),
        compose_command=source.argv("DOCKER_COMPOSE_COMMAND", DEFAULT_COMPOSE_COMMAND),
        compose_project_name=source.text(
            "DOCKER_COMPOSE_PROJECT_NAME", DEFAULT_COMPOSE_PROJECT_NAME
        ),
        compose_services=source.words("DOCKER_COMPOSE_SERVICES"),
        bazel_rc_file=source.text("BAZEL_RC_FILE"),
        bazel_user_output_root=source.text("BAZEL_USER_OUTPUT_ROOT", default_user_output_root()),
        docker_run_privileged=source.flag("DOCKER_RUN_PRIVILEGED", default=False),
        docker_machine=source.text("DOCKER_MACHINE"),
        run_file=directory / source.text("RUN_FILE", DEFAULT_RUN_FILE),
        workspace_hex=source.flag("WORKSPACE_HEX", default=False),
        delegated_volume=source.flag("DELEGATED_VOLUME", default=True),
        user=source.text("USER"),
        docker_build_args=source.argv("DOCKER_BUILD_ARGS"),
        per_workspace_container=source.flag("PER_WORKSPACE_CONTAINER", default=False),
        ports_only_primary=_to_flag(only_primary, default=True) if only_primary else None,
        bazel_disk_cache=source.path("BAZEL_DISK_CACHE", directory),
    )
