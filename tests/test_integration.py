import shutil
import subprocess
from pathlib import Path

import pytest

from dazel import DockerInstance

from fakes import make_workspace

IMAGE = "alpine:3"


def docker_ready() -> bool:
    if shutil.which("docker") is None:
        return False
    probe = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, check=False)
    pull = subprocess.run(["docker", "pull", "-q", IMAGE], capture_output=True, check=False)
    return probe.returncode == 0 or pull.returncode == 0


pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def require_docker() -> None:
    if not docker_ready():
        pytest.skip("needs a docker daemon and the alpine image")


def test_container_lifecycle_per_workspace(tmp_path: Path) -> None:
    rc = (
        f'DAZEL_REPOSITORY = ""\nDAZEL_IMAGE_NAME = "{IMAGE}"\nDAZEL_COMMAND = ""\n'
        'DAZEL_NETWORK = "bridge"\nDAZEL_RUN_COMMAND = "sleep 300"\n'
        'DAZEL_INSTANCE_NAME = "dazel-itest"\nDAZEL_PER_WORKSPACE_CONTAINER = True\n'
        f'DAZEL_BAZEL_USER_OUTPUT_ROOT = "{tmp_path / "out"}"\n'
    )
    instance = DockerInstance.from_config({}, make_workspace(tmp_path, rc))
    try:
        assert instance.needs_start()
        assert instance.start() == 0
        assert instance.is_running()
        assert not instance.needs_start()
        assert instance.send_command(["true"]) == 0
        assert instance.send_command(["sh", "-c", "exit 5"]) == 5
    finally:
        assert instance.clean_workspace() == 0
    assert not instance.is_running()
