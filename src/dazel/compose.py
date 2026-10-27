"""Pure builders of the docker-compose steps that bring up the shared services."""

from dataclasses import dataclass
from pathlib import Path

from dazel.config import Config
from dazel.plan import Plan
from dazel.workspace import primary_checkout


@dataclass(frozen=True, slots=True)
class ComposeStep:
    """One docker-compose invocation and the environment it needs."""

    argv: tuple[str, ...]
    env: dict[str, str]


def project_directory(cfg: Config) -> Path:
    """Return where compose resolves the compose file's relative paths (bind mounts) from.

    In per-workspace mode every worktree shares one compose project, and compose recreates a
    service whose resolved mount paths change. Resolving them against the primary checkout, at the
    compose file's own location within it, keeps them identical whichever worktree starts the
    services. The compose file itself is still read from the current worktree.
    """
    if cfg.compose_file is None:
        msg = "project_directory needs DAZEL_DOCKER_COMPOSE_FILE"
        raise ValueError(msg)
    compose_dir = cfg.compose_file.parent
    try:
        relative = compose_dir.resolve().relative_to(cfg.directory.resolve())
    except ValueError:
        return compose_dir
    return primary_checkout(cfg.directory.resolve()) / relative


def compose_steps(cfg: Config, plan: Plan) -> list[ComposeStep]:
    """Return the pull, build and up steps for the configured compose file.

    In per-workspace mode the compose project is shared by every worktree, so ``up`` has no
    ``--force-recreate``: compose then recreates exactly the services whose configuration changed,
    and with ``--project-directory`` pinned to the primary checkout (see ``project_directory``) a
    different worktree is not such a change, while an edit of the compose file is.
    """
    if cfg.compose_file is None:
        return []
    base = (*cfg.compose_command, "-f", str(cfg.compose_file))
    if cfg.per_workspace_container:
        base = (*base, "--project-directory", str(project_directory(cfg)))
    services = tuple(cfg.compose_services)
    recreate = [] if cfg.per_workspace_container else ["--force-recreate"]
    env = {"COMPOSE_PROJECT_NAME": plan.compose_project_name}
    return [
        ComposeStep((*base, "pull", "--ignore-pull-failures", *services), env),
        ComposeStep((*base, "build", *services), env),
        ComposeStep((*base, "up", *recreate, "-d", *services), env),
    ]
