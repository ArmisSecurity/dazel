"""Pure builders of docker argv lists; nothing here touches the system."""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from dazel.config import Config, RunDep
from dazel.plan import Plan

NOFILE_ULIMIT = "nofile=1048576:1048576"


@dataclass(frozen=True, slots=True)
class Terminal:
    """Terminal properties forwarded to the exec'd process."""

    columns: int
    lines: int
    term: str
    tty: bool


def _each(flag: str, values: Sequence[str]) -> list[str]:
    return [part for value in values for part in (flag, value)]


def _bind_mount(path: Path) -> str:
    """Return a ``--mount`` value binding ``path`` at itself; unlike ``-v`` it allows a ``:`` in the path."""
    text = str(path)
    if "," not in text and '"' not in text:
        return f"type=bind,src={text},dst={text}"
    quoted = text.replace('"', '""')
    return f'"type=bind","src={quoted}","dst={quoted}"'


def image_ref(cfg: Config, plan: Plan) -> str:
    """Return ``<repository>/<image>`` or just the image when there is no repository."""
    return f"{cfg.repository}/{plan.image_name}" if cfg.repository else plan.image_name


def exec_argv(cfg: Config, plan: Plan, terminal: Terminal, inner: Sequence[str]) -> list[str]:
    """Build ``docker exec`` running ``inner`` in the workspace container."""
    return [
        *cfg.docker_command,
        "exec",
        "-i",
        *("-e", f"COLUMNS={terminal.columns}"),
        *("-e", f"LINES={terminal.lines}"),
        *("-e", f"TERM={terminal.term}"),
        *(["-t"] if terminal.tty else []),
        *(["--privileged"] if cfg.docker_run_privileged else []),
        *([f"--user={cfg.user}"] if cfg.user else []),
        plan.instance_name,
        *inner,
    ]


def run_argv(cfg: Config, plan: Plan) -> list[str]:
    """Build ``docker run`` creating the workspace container."""
    return [
        *cfg.docker_command,
        "run",
        "-id",
        f"--name={plan.instance_name}",
        *("--ulimit", NOFILE_ULIMIT),
        *([f"--platform={cfg.platform}"] if cfg.platform else []),
        *(["--privileged"] if cfg.docker_run_privileged else []),
        *([f"--user={cfg.user}"] if cfg.user else []),
        *("-w", str(plan.workdir)),
        *_each("-v", plan.volumes),
        *_each("-p", plan.ports),
        *_each("-e", cfg.env_vars),
        *(["--gpus", ",".join(cfg.gpus)] if cfg.gpus else []),
        *_each("--group-add", cfg.groups),
        *([f"--shm-size={cfg.shm_size}"] if cfg.shm_size else []),
        *([f"--net={plan.network}"] if plan.network else []),
        image_ref(cfg, plan),
        *cfg.run_command,
    ]


def run_dep_argv(cfg: Config, plan: Plan, dep: RunDep) -> list[str]:
    """Build ``docker run`` for a run dependency joined to the dazel network."""
    return [
        *cfg.docker_command,
        "run",
        "-id",
        f"--name={dep.name}",
        *(["--privileged"] if cfg.docker_run_privileged else []),
        *([f"--net={plan.network}"] if plan.network else []),
        dep.image,
    ]


def build_argv(cfg: Config, plan: Plan) -> list[str]:
    """Build ``docker build`` for the image from the configured Dockerfile.

    The build context is ``DAZEL_BUILD_DIRECTORY`` when set, the workspace root otherwise.
    """
    return [
        *cfg.docker_command,
        "build",
        *cfg.docker_build_args,
        *("-t", image_ref(cfg, plan)),
        *("-f", str(cfg.dockerfile)),
        str(cfg.build_directory or cfg.directory),
    ]


def pull_argv(cfg: Config, plan: Plan) -> list[str]:
    """Build ``docker pull`` for the image."""
    return [*cfg.docker_command, "pull", image_ref(cfg, plan)]


def image_ls_argv(cfg: Config, plan: Plan) -> list[str]:
    """Build ``docker image ls`` listing the image."""
    return [*cfg.docker_command, "image", "ls", "--quiet", image_ref(cfg, plan)]


def ps_argv(cfg: Config, name: str, *, include_stopped: bool = False) -> list[str]:
    """Build ``docker ps`` printing the names of containers called exactly ``name``.

    Only running containers are listed unless ``include_stopped``.
    """
    return [
        *cfg.docker_command,
        "ps",
        *(["--all"] if include_stopped else []),
        *("--filter", f"name=^{name}$"),
        *("--format", "{{.Names}}"),
    ]


def inspect_argv(cfg: Config, name: str, template: str) -> list[str]:
    """Build ``docker inspect`` rendering ``template`` for container ``name``."""
    return [*cfg.docker_command, "inspect", "--format", template, name]


def network_ls_argv(cfg: Config) -> list[str]:
    """Build ``docker network ls`` printing network names."""
    return [*cfg.docker_command, "network", "ls", "--format", "{{.Name}}"]


def network_create_argv(cfg: Config, plan: Plan) -> list[str]:
    """Build ``docker network create`` for the dazel network."""
    return [*cfg.docker_command, "network", "create", plan.network]


def stop_argv(cfg: Config, name: str) -> list[str]:
    """Build ``docker stop`` for a container."""
    return [*cfg.docker_command, "stop", name]


def rm_argv(cfg: Config, name: str) -> list[str]:
    """Build ``docker rm`` for a container."""
    return [*cfg.docker_command, "rm", name]


def rm_tree_argv(cfg: Config, plan: Plan, path: Path) -> list[str]:
    """Build ``docker run`` deleting ``path`` as root, for files the container left root-owned."""
    return [
        *cfg.docker_command,
        "run",
        "--rm",
        "--pull=never",
        *("--entrypoint", "rm"),
        *("--mount", _bind_mount(path.parent)),
        image_ref(cfg, plan),
        *("-rf", str(path)),
    ]
