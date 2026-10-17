"""The dazel container lifecycle: build, start, check and talk to the container."""

import json
import logging
import os
import shutil
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Self

from dazel import docker
from dazel.bazel import bazel_argv
from dazel.clean import clean_workspace
from dazel.compose import compose_steps
from dazel.config import Config, load_config
from dazel.docker import Terminal
from dazel.executor import Executor, Output, executor_for
from dazel.plan import Plan, host_dirs_to_create, is_predefined_network, make_plan

logger = logging.getLogger("dazel")

BINDS_TEMPLATE = "{{json .HostConfig.Binds}}"
NETWORKS_TEMPLATE = "{{json .NetworkSettings.Networks}}"


def current_terminal() -> Terminal:
    """Describe the terminal dazel is attached to."""
    size = shutil.get_terminal_size()
    return Terminal(size.columns, size.lines, os.environ.get("TERM", ""), sys.stdout.isatty())


class DockerInstance:
    """Manages the dazel container of one workspace.

    Streams command output directly and blocks until the command finishes. Also the entry point
    for programs that import dazel as a library.
    """

    def __init__(
        self,
        config: Config,
        executor: Executor | None = None,
        terminal: Callable[[], Terminal] = current_terminal,
    ) -> None:
        self.config = config
        self.plan: Plan = make_plan(config)
        self._executor = executor or executor_for(config.docker_machine)
        self._terminal = terminal

    @classmethod
    def from_config(cls, env: Mapping[str, str] | None = None, cwd: Path | None = None) -> Self:
        """Load the configuration for the current directory's workspace."""
        return cls(load_config(os.environ if env is None else env, cwd or Path.cwd()))

    @property
    def instance_name(self) -> str:
        """The container name, including the workspace suffix when one applies."""
        return self.plan.instance_name

    @property
    def docker_command(self) -> str:
        """The configured docker command line, as a string."""
        return " ".join(self.config.docker_command)

    def _exec_prefix(self) -> list[str]:
        return [*self.config.docker_command, "exec", self.plan.instance_name]

    def needs_start(self) -> bool:
        """Return whether the container must be (re)started before running a command."""
        cfg = self.config
        if not cfg.run_file.exists() or not self.is_running():
            return True
        return (
            cfg.dockerfile.exists()
            and cfg.dockerfile.stat().st_ctime > cfg.run_file.stat().st_ctime
        )

    def is_running(self) -> bool:
        """Return whether the container runs with this workspace bound and on the right network."""
        cfg, plan = self.config, self.plan
        names = self._executor.capture(docker.ps_argv(cfg, plan.instance_name)).split()
        if plan.instance_name not in names:
            return False
        workspace_bind = f"{plan.workdir}:{plan.workdir}"
        binds = self._inspect(BINDS_TEMPLATE)
        if not any(
            bind == workspace_bind or bind.startswith(f"{workspace_bind}:") for bind in binds
        ):
            return False
        return not plan.network or plan.network in self._inspect(NETWORKS_TEMPLATE)

    def _inspect(self, template: str) -> list[str]:
        argv = docker.inspect_argv(self.config, self.plan.instance_name, template)
        data = json.loads(self._executor.capture(argv) or "null")
        return list(data or [])

    def send_command(self, args: Sequence[str]) -> int:
        """Run a bazel command inside the container and return its exit status."""
        inner = bazel_argv(self.config, self.plan.layout, args)
        argv = docker.exec_argv(self.config, self.plan, self._terminal(), inner)
        return self._executor.call(argv, output=Output.INHERIT)

    def start(self) -> int:
        """Build or pull the image, start its dependencies, then run the container."""
        cfg, plan, executor = self.config, self.plan, self._executor
        if not executor.exists(cfg.docker_command[0]):
            logger.error("ERROR: Docker executable could not be found!")
            return 1
        if (rc := self._ensure_image()) or (rc := self._start_dependencies()):
            return rc
        return self._run_container(docker.run_argv(cfg, plan))

    def _ensure_image(self) -> int:
        cfg, plan = self.config, self.plan
        if cfg.dockerfile.exists():
            return self._executor.call(docker.build_argv(cfg, plan))
        rc = self._executor.call(docker.pull_argv(cfg, plan))
        if rc and self._executor.capture(docker.image_ls_argv(cfg, plan)).strip():
            return 0
        return rc

    def _start_dependencies(self) -> int:
        cfg = self.config
        if cfg.compose_file and self._executor.exists(cfg.compose_command[0]):
            return self._start_compose()
        return self._start_network() or self._start_run_deps()

    def _start_compose(self) -> int:
        for step in compose_steps(self.config, self.plan):
            if rc := self._executor.call(step.argv, step.env):
                return rc
        return 0

    def _start_network(self) -> int:
        cfg, plan = self.config, self.plan
        if not plan.network or is_predefined_network(plan.network):
            return 0
        existing = self._executor.capture(docker.network_ls_argv(cfg)).split()
        if plan.network in existing:
            return 0
        logger.info("Creating network: '%s'", plan.network)
        return self._executor.call(docker.network_create_argv(cfg, plan))

    def _start_run_deps(self) -> int:
        cfg, plan = self.config, self.plan
        for dep in cfg.run_deps:
            if dep.name in self._executor.capture(docker.ps_argv(cfg, dep.name)).split():
                continue
            logger.info("Starting run dependency: '%s' (name: '%s')", dep.image, dep.name)
            self._executor.call(docker.stop_argv(cfg, dep.name), output=Output.DISCARD)
            self._executor.call(docker.rm_argv(cfg, dep.name), output=Output.DISCARD)
            if rc := self._executor.call(docker.run_dep_argv(cfg, plan, dep)):
                return rc
        return 0

    def _run_container(self, run: list[str]) -> int:
        cfg, plan = self.config, self.plan
        logger.info("Starting docker container '%s'...", plan.instance_name)
        for path in host_dirs_to_create(plan, cfg):
            path.mkdir(parents=True, exist_ok=True)
        self._executor.call(docker.stop_argv(cfg, plan.instance_name), output=Output.DISCARD)
        self._executor.call(docker.rm_argv(cfg, plan.instance_name), output=Output.DISCARD)
        if rc := self._executor.call(run):
            return rc
        cfg.run_file.write_text(f"{plan.instance_name}\n", encoding="utf-8")
        return 0

    def clean_workspace(self) -> int:
        """Remove this workspace's container and output base."""
        return clean_workspace(self.config, self.plan, self._executor)
