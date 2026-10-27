"""Helpers for the integration tests that drive a real docker daemon.

A missing daemon skips the tests, unless ``DAZEL_REQUIRE_DOCKER`` is set (CI does) which fails them.

Every resource a test creates carries a unique tag, so tests never touch (or depend on) the
developer's real dazel container, image or compose project, and tear everything down afterwards.
"""

import functools
import os
import shutil
import socket
import subprocess
import sys
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from dazel import DockerInstance

from fake_support import make_workspace

# The ECR Public mirror of Docker Hub's official image: no anonymous pull rate limit on CI runners.
BASE_IMAGE = "public.ecr.aws/docker/library/alpine:3.20"
REQUIRE_DOCKER_VARIABLE = "DAZEL_REQUIRE_DOCKER"
GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
}
COMPOSE_FILE = f"""\
services:
  svc:
    image: {BASE_IMAGE}
    command: sleep 600
    volumes:
      - ./data:/data:ro
"""


def docker(*args: str, check: bool = True) -> str:
    """Run a docker command and return its stdout."""
    result = subprocess.run(["docker", *args], capture_output=True, text=True, check=check)
    return result.stdout.strip()


def git(cwd: Path, *args: str) -> None:
    """Run git in ``cwd`` with a fixed identity."""
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, env={**os.environ, **GIT_ENV})


def skip_unless_required(need: str) -> None:
    """Skip the test for lack of ``need``; fail instead when ``DAZEL_REQUIRE_DOCKER`` is set."""
    if os.environ.get(REQUIRE_DOCKER_VARIABLE):
        pytest.fail(f"{REQUIRE_DOCKER_VARIABLE} is set, so a test that needs {need} cannot be skipped")
    pytest.skip(f"needs {need}")


def daemon_time() -> str:
    """Return the docker daemon's clock, the reference for ``docker events`` time windows."""
    return docker("info", "--format", "{{.SystemTime}}")


def created_containers(name: str, since: str, until: str) -> list[str]:
    """Return the ids of the containers called ``name`` that were created between the two daemon times."""
    events = docker(
        *("events", "--since", since, "--until", until),
        *("--filter", f"container={name}", "--filter", "event=create", "--format", "{{.Actor.ID}}"),
    )
    return events.split()


@functools.cache
def docker_ready() -> bool:
    """Return whether a docker daemon answers and the base image is available."""
    if shutil.which("docker") is None or shutil.which("git") is None:
        return False
    if subprocess.run(["docker", "info"], capture_output=True, check=False).returncode != 0:
        return False
    return subprocess.run(["docker", "pull", "-q", BASE_IMAGE], capture_output=True, check=False).returncode == 0


@functools.cache
def compose_command() -> str | None:
    """Return the compose executable available on this machine, if any."""
    if shutil.which("docker-compose"):
        return "docker-compose"
    plugin = subprocess.run(["docker", "compose", "version"], capture_output=True, check=False)
    return "docker compose" if plugin.returncode == 0 else None


def free_port() -> int:
    """Return a TCP port that is currently free on the loopback interface."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def container_id(name: str) -> str:
    """Return the id of the container called ``name``."""
    return docker("inspect", "--format", "{{.Id}}", name)


def container_started_at(name: str) -> str:
    """Return when the container last started."""
    return docker("inspect", "--format", "{{.State.StartedAt}}", name)


def container_exists(name: str) -> bool:
    """Return whether a container (running or not) called ``name`` exists."""
    return bool(docker("ps", "-a", "--filter", f"name=^{name}$", "--format", "{{.Names}}"))


def mount_sources(name: str) -> list[str]:
    """Return the host paths bind mounted into the container called ``name``."""
    return docker("inspect", "--format", "{{range .Mounts}}{{.Source}}\n{{end}}", name).split()


def container_running(name: str) -> bool:
    """Return whether a container called ``name`` is running."""
    return bool(docker("ps", "--filter", f"name=^{name}$", "--format", "{{.Names}}"))


@dataclass
class Lab:
    """A scratch area plus unique resource names for one integration test."""

    root: Path
    tag: str = field(default_factory=lambda: uuid.uuid4().hex[:10])

    @property
    def instance_name(self) -> str:
        return f"dzt-{self.tag}"

    @property
    def image_ref(self) -> str:
        return f"dzt-{self.tag}/img"

    @property
    def project(self) -> str:
        return f"dzt-{self.tag}"

    @property
    def output_root(self) -> Path:
        return self.root / "out"

    def rc(self, **settings: object) -> str:
        """Return a ``.dazelrc`` for the lab's image, with ``settings`` overriding the defaults."""
        values: dict[str, object] = {
            "INSTANCE_NAME": self.instance_name,
            "REPOSITORY": f"dzt-{self.tag}",
            "IMAGE_NAME": "img",
            "DOCKERFILE": "Dockerfile.dazel",
            "RUN_COMMAND": "sleep 600",
            "COMMAND": "",
            "NETWORK": "bridge",
            "DOCKER_COMPOSE_PROJECT_NAME": self.project,
            "BAZEL_USER_OUTPUT_ROOT": str(self.output_root),
            "PER_WORKSPACE_CONTAINER": True,
            **settings,
        }
        return "".join(f"DAZEL_{key} = {value!r}\n" for key, value in values.items())

    def primary(self, **settings: object) -> Path:
        """Create a primary git checkout holding the image and compose definitions."""
        workspace = make_workspace(self.root, self.rc(**settings), name="primary")
        (workspace / "Dockerfile.dazel").write_text(f"FROM {BASE_IMAGE}\nRUN echo tiny > /marker\n", encoding="utf-8")
        (workspace / "compose.yml").write_text(COMPOSE_FILE, encoding="utf-8")
        (workspace / "data").mkdir()
        (workspace / "data" / "seed").write_text("seed", encoding="utf-8")
        git(workspace, "init", "-q")
        git(workspace, "add", "-A")
        git(workspace, "commit", "-q", "-m", "init")
        return workspace

    def linked(self, primary: Path, name: str = "linked") -> Path:
        """Create a real linked git worktree of ``primary``."""
        worktree = self.root / name
        git(primary, "worktree", "add", "-q", "--detach", str(worktree))
        return worktree

    def instance(self, workspace: Path) -> DockerInstance:
        """Return the dazel instance for ``workspace``, configured from its rc file only."""
        env = {key: value for key, value in os.environ.items() if not key.startswith("DAZEL_")}
        return DockerInstance.from_config(env, workspace)

    def cleanup(self) -> None:
        """Remove every docker resource carrying this lab's tag."""
        names = docker("ps", "-a", "--filter", f"name=dzt-{self.tag}", "--format", "{{.Names}}", check=False)
        for name in names.split():
            docker("rm", "-f", name, check=False)
        for image in docker("image", "ls", "--format", "{{.Repository}}:{{.Tag}}", check=False).split():
            if image.startswith(f"dzt-{self.tag}/"):
                docker("rmi", "-f", image, check=False)
        for network in docker("network", "ls", "--format", "{{.Name}}", check=False).split():
            if network.startswith(f"dzt-{self.tag}"):
                docker("network", "rm", network, check=False)


def scratch_root(tmp_path: Path) -> Path:
    """Return a scratch directory docker can bind mount.

    colima and Docker Desktop only share the home directory with their VM, not the system temp
    directory pytest uses on macOS, so there the lab lives under ``~/.cache``.
    """
    if sys.platform != "darwin":
        return tmp_path
    root = Path.home() / ".cache" / "dazel-itest" / uuid.uuid4().hex[:10]
    root.mkdir(parents=True)
    return root


@pytest.fixture
def lab(tmp_path: Path) -> Iterator[Lab]:
    """Provide a ``Lab`` and remove its docker resources and files afterwards."""
    if not docker_ready():
        skip_unless_required("git and a docker daemon able to pull " + BASE_IMAGE)
    root = scratch_root(tmp_path)
    scratch = Lab(root)
    try:
        yield scratch
    finally:
        scratch.cleanup()
        if root != tmp_path:
            shutil.rmtree(root, ignore_errors=True)
