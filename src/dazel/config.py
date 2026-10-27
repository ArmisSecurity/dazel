"""Configuration: ``.dazelrc`` (executed Python) overlaid with ``DAZEL_*`` environment variables."""

import getpass
import runpy
import shlex
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from dazel.env import expand_variables
from dazel.workspace import find_workspace

RC_FILE_NAME = ".dazelrc"
LOCAL_RC_FILE_NAME = ".dazelrc.local"
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
    """A container started next to the dazel container when no compose file is configured.

    ``name`` is empty until resolved against the network (see ``plan.make_plan``) unless the entry
    spelled it out as ``image::name``.
    """

    image: str
    name: str = ""


@dataclass(frozen=True, slots=True)
class DiskCache:
    """A host directory bind mounted into the container for bazel's disk cache."""

    host: Path
    container: str


@dataclass(frozen=True, slots=True)
class Config:
    """Fully resolved dazel configuration; each recognised ``DAZEL_*`` key maps to one field."""

    directory: Path
    mount_directory: Path | None = None
    instance_name: str = DEFAULT_INSTANCE_NAME
    image_name: str = DEFAULT_IMAGE_NAME
    run_command: tuple[str, ...] = (DEFAULT_RUN_COMMAND,)
    docker_command: tuple[str, ...] = (DEFAULT_DOCKER_COMMAND,)
    dockerfile: Path = Path(DEFAULT_DOCKERFILE)
    build_directory: Path | None = None
    repository: str = DEFAULT_REPOSITORY
    command: tuple[str, ...] = (DEFAULT_COMMAND,)
    volumes: tuple[str, ...] = ()
    ports: tuple[str, ...] = ()
    env_vars: tuple[str, ...] = ()
    gpus: tuple[str, ...] = ()
    groups: tuple[str, ...] = ()
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
    run_file: Path | None = Path(DEFAULT_RUN_FILE)
    workspace_hex: bool = False
    delegated_volume: bool = True
    user: str = ""
    docker_build_args: tuple[str, ...] = ()
    per_workspace_container: bool = False
    ports_only_primary: bool | None = None
    bazel_disk_cache: DiskCache | None = None
    rc_files: tuple[Path, ...] = ()


def default_user_output_root() -> str:
    """Return bazel's conventional per-user output root."""
    return str(Path("~/.cache/bazel").expanduser() / f"_bazel_{getpass.getuser()}")


def load_rc(path: Path) -> RawConfig:
    """Execute a ``.dazelrc`` file and return the names it defines."""
    namespace: RawConfig = runpy.run_path(str(path))
    return {key: value for key, value in namespace.items() if key.startswith(ENV_PREFIX)}


def rc_candidates(env: Mapping[str, str], directory: Path) -> tuple[Path, ...]:
    """Return the rc files dazel reads for ``directory``, lowest precedence first.

    ``~/.dazelrc`` holds per-user defaults, the workspace ``.dazelrc`` (or ``DAZEL_RC_FILE``) the
    project's configuration, and an uncommitted ``.dazelrc.local`` beside it a developer's overrides.
    A file reached twice (a workspace at ``~``) is read once.
    """
    home = Path(env.get("HOME", "~")).expanduser()
    project = Path(env.get("DAZEL_RC_FILE", directory / RC_FILE_NAME))
    paths = (home / RC_FILE_NAME, project, directory / LOCAL_RC_FILE_NAME)
    return tuple(dict.fromkeys(path.absolute() for path in paths))


def load_config(env: Mapping[str, str], cwd: Path) -> Config:
    """Build the configuration for the workspace containing ``cwd``.

    Precedence, lowest to highest: defaults, ``~/.dazelrc``, ``.dazelrc``, ``.dazelrc.local``,
    ``DAZEL_*`` environment variables. A key set in a later file replaces the earlier value whole.
    ``DAZEL_RC_FILE`` selects another project rc file. ``DAZEL_DIRECTORY`` is where the workspace
    search starts and, when set, the directory that is mounted and used as the container's working
    directory instead of the workspace root found.
    """
    directory = find_workspace(Path(env.get("DAZEL_DIRECTORY", cwd)))
    rc_files = tuple(path for path in rc_candidates(env, directory) if path.is_file())
    raw: RawConfig = {}
    for path in rc_files:
        raw.update(load_rc(path))
    raw.update({k: v for k, v in env.items() if k.startswith(ENV_PREFIX)})
    return replace(resolve(raw, directory, {**env, "PWD": str(cwd)}), rc_files=rc_files)


def _split_words(key: str, value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        items: Iterable[object] = value.split(",")
    elif isinstance(value, Iterable):
        items = value
    else:
        msg = f"{key} must be a comma-separated string or an iterable of strings"
        raise ConfigError(msg)
    return tuple(text for item in items if (text := str(item).strip()))


def _split_argv(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(shlex.split(value))
    return tuple(str(part) for part in value) if isinstance(value, Iterable) else ()


def _to_flag(value: object, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() not in FALSE_WORDS
    return bool(value)


def _run_dep(entry: str) -> RunDep:
    image, _, name = entry.partition("::")
    return RunDep(image, name)


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

    def path(self, key: str, directory: Path, default: str = "") -> Path | None:
        value = self.text(key, default)
        if not value:
            return None
        return directory / Path(expand_variables(value, self._env)).expanduser()


def _disk_cache(spec: str, directory: Path, env: Mapping[str, str]) -> DiskCache | None:
    if not spec:
        return None
    host_part, separator, container = expand_variables(spec, env).partition(":")
    host = directory / Path(host_part).expanduser()
    if separator and not container.startswith("/"):
        msg = f"{ENV_PREFIX}BAZEL_DISK_CACHE container path must be absolute, got {container!r}"
        raise ConfigError(msg)
    return DiskCache(host, container if separator else str(host))


def resolve(raw: RawConfig, directory: Path, env: Mapping[str, str]) -> Config:
    """Turn raw ``DAZEL_*`` values into a validated ``Config``.

    Variables such as ``$HOME`` in volumes, ports and environment entries are expanded from ``env``.
    """
    source = _Source(raw, env)
    only_primary = source.text("PORTS_ONLY_PRIMARY")
    mount = source.text("DIRECTORY")
    return Config(
        directory=directory,
        mount_directory=Path(mount) if mount else None,
        instance_name=source.text("INSTANCE_NAME", DEFAULT_INSTANCE_NAME),
        image_name=source.text("IMAGE_NAME", DEFAULT_IMAGE_NAME),
        run_command=source.argv("RUN_COMMAND", DEFAULT_RUN_COMMAND),
        docker_command=source.argv("DOCKER_COMMAND", DEFAULT_DOCKER_COMMAND),
        dockerfile=source.path("DOCKERFILE", directory) or directory / DEFAULT_DOCKERFILE,
        build_directory=source.path("BUILD_DIRECTORY", directory),
        repository=source.text("REPOSITORY", DEFAULT_REPOSITORY),
        command=source.argv("COMMAND", DEFAULT_COMMAND),
        volumes=source.expanded("VOLUMES"),
        ports=source.expanded("PORTS"),
        env_vars=source.expanded("ENV_VARS"),
        gpus=source.words("GPUS"),
        groups=source.words("GROUPS"),
        platform=source.text("PLATFORM"),
        shm_size=source.text("SHM_SIZE"),
        network=source.text("NETWORK", DEFAULT_NETWORK),
        run_deps=tuple(_run_dep(entry) for entry in source.words("RUN_DEPS")),
        compose_file=source.path("DOCKER_COMPOSE_FILE", directory),
        compose_command=source.argv("DOCKER_COMPOSE_COMMAND", DEFAULT_COMPOSE_COMMAND),
        compose_project_name=source.text("DOCKER_COMPOSE_PROJECT_NAME", DEFAULT_COMPOSE_PROJECT_NAME),
        compose_services=source.words("DOCKER_COMPOSE_SERVICES"),
        bazel_rc_file=source.text("BAZEL_RC_FILE"),
        bazel_user_output_root=source.text("BAZEL_USER_OUTPUT_ROOT", default_user_output_root()),
        docker_run_privileged=source.flag("DOCKER_RUN_PRIVILEGED", default=False),
        docker_machine=source.text("DOCKER_MACHINE"),
        run_file=source.path("RUN_FILE", directory, DEFAULT_RUN_FILE),
        workspace_hex=source.flag("WORKSPACE_HEX", default=False),
        delegated_volume=source.flag("DELEGATED_VOLUME", default=True),
        user=source.text("USER"),
        docker_build_args=source.argv("DOCKER_BUILD_ARGS"),
        per_workspace_container=source.flag("PER_WORKSPACE_CONTAINER", default=False),
        ports_only_primary=_to_flag(only_primary, default=True) if only_primary else None,
        bazel_disk_cache=_disk_cache(source.text("BAZEL_DISK_CACHE"), directory, env),
    )
