"""Pure resolution of names, ports and mounts for one workspace."""

from dataclasses import dataclass
from pathlib import Path

from dazel.bazel import OutputLayout, output_layout
from dazel.config import Config, RunDep
from dazel.workspace import is_linked_worktree, workspace_digest

PREDEFINED_NETWORKS = frozenset({"host", "bridge", "none"})


@dataclass(frozen=True, slots=True)
class Plan:
    """Everything docker needs to know about a workspace, derived from a ``Config``."""

    instance_name: str
    image_name: str
    compose_project_name: str
    network: str
    ports: tuple[str, ...]
    volumes: tuple[str, ...]
    run_deps: tuple[RunDep, ...]
    layout: OutputLayout
    digest: str
    workdir: Path
    workspace: Path


def is_predefined_network(network: str) -> bool:
    """Return whether ``network`` is one of docker's built-in network modes."""
    return network in PREDEFINED_NETWORKS


def publish_ports(cfg: Config) -> bool:
    """Return whether this checkout may publish host ports.

    With ``ports_only_primary`` (the default in per-workspace mode), only the primary checkout
    publishes, so linked git worktrees never collide on fixed host ports.
    """
    only_primary = cfg.per_workspace_container if cfg.ports_only_primary is None else cfg.ports_only_primary
    return not (only_primary and is_linked_worktree(cfg.directory))


def mount(host: Path | str, *, options: str = "") -> str:
    """Return a bind mount that keeps the host path inside the container."""
    return f"{host}:{host}{options}"


def disk_cache_mounts(cfg: Config) -> tuple[str, ...]:
    """Return the bind mount for the configured bazel disk cache, if any."""
    cache = cfg.bazel_disk_cache
    return (f"{cache.host}:{cache.container}",) if cache else ()


def make_plan(cfg: Config) -> Plan:
    """Resolve the per-workspace plan.

    ``workspace_hex`` is the legacy mode suffixing container, image and compose project.
    ``per_workspace_container`` suffixes only the container and the bazel output base, leaving
    the image, compose project and network shared.

    Names and the output base are keyed on the workspace root, never on ``DAZEL_DIRECTORY``'s
    mounted subdirectory, so external cleanup tools can find them by the md5 of the workspace root.
    """
    workdir = (cfg.mount_directory or cfg.directory).resolve()
    workspace = cfg.directory.resolve()
    digest = workspace_digest(workspace)
    isolated = cfg.workspace_hex or cfg.per_workspace_container
    layout = output_layout(cfg, digest if isolated else "")

    instance_name = f"{cfg.instance_name}_{digest}" if isolated else cfg.instance_name
    image_name = cfg.image_name
    project = cfg.compose_project_name
    if cfg.workspace_hex:
        project = f"{project}{digest}"
        if cfg.dockerfile.exists():
            image_name = f"{image_name}_{digest}"

    network = cfg.network
    if cfg.compose_file and not is_predefined_network(network):
        network = f"{project}_{network}"

    run_deps = tuple(
        dep if dep.name else RunDep(dep.image, f"{network}_{dep.image.replace('/', '_').replace(':', '_')}")
        for dep in cfg.run_deps
    )

    delegated = ":delegated" if cfg.delegated_volume else ""
    volumes = (
        *cfg.volumes,
        mount(workdir),
        *(mount(path, options=delegated) for path in layout.mount_dirs),
        *disk_cache_mounts(cfg),
    )
    return Plan(
        instance_name=instance_name,
        image_name=image_name,
        compose_project_name=project,
        network=network,
        ports=cfg.ports if publish_ports(cfg) else (),
        volumes=volumes,
        run_deps=run_deps,
        layout=layout,
        digest=digest if isolated else "",
        workdir=workdir,
        workspace=workspace,
    )


def host_dirs_to_create(plan: Plan, cfg: Config) -> tuple[Path, ...]:
    """Return host directories that must exist before docker bind mounts them."""
    root = (Path(plan.layout.user_root),) if plan.layout.user_root else ()
    cache = (cfg.bazel_disk_cache.host,) if cfg.bazel_disk_cache else ()
    return (*root, *plan.layout.mount_dirs, *cache)
