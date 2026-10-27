"""Shared fixtures: a scratch HOME for unit tests, and the docker ``lab`` for integration tests."""

import os
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from docker_support import BASE_IMAGE, Lab, docker_ready, scratch_root, skip_unless_required


@pytest.fixture(autouse=True)
def isolated_home(request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point HOME at a scratch directory and drop ambient DAZEL_* variables.

    Integration tests keep the real HOME: their bind-mount sources live under it, which is the part of
    the host filesystem that docker VMs (Docker Desktop, colima) share.
    """
    if request.node.get_closest_marker("integration"):
        return Path.home()
    home = tmp_path / "home"
    (home / ".docker" / "cli-plugins").mkdir(parents=True)
    (home / ".docker" / "config.json").touch()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("LOGNAME", "tester")
    for name in [name for name in os.environ if name.startswith("DAZEL_")]:
        monkeypatch.delenv(name)
    return home


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
