"""Pure builders of the docker-compose steps that bring up the shared services."""

from dataclasses import dataclass

from dazel.config import Config
from dazel.plan import Plan


@dataclass(frozen=True, slots=True)
class ComposeStep:
    """One docker-compose invocation and the environment it needs."""

    argv: tuple[str, ...]
    env: dict[str, str]


def compose_steps(cfg: Config, plan: Plan) -> list[ComposeStep]:
    """Return the pull, build and up steps for the configured compose file.

    The shared project in per-workspace mode must not be torn down by every new container, so
    ``up`` only recreates services when their definition changed instead of forcing a recreate.
    """
    if cfg.compose_file is None:
        return []
    base = (*cfg.compose_command, "-f", str(cfg.compose_file))
    services = tuple(cfg.compose_services)
    recreate = () if cfg.per_workspace_container else ("--force-recreate",)
    env = {"COMPOSE_PROJECT_NAME": plan.compose_project_name}
    return [
        ComposeStep((*base, "pull", "--ignore-pull-failures", *services), env),
        ComposeStep((*base, "build", *services), env),
        ComposeStep((*base, "up", *recreate, "-d", *services), env),
    ]
