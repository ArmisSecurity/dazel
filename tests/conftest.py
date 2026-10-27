"""Shared fixtures: unit tests run with a scratch HOME and no ambient DAZEL_* variables."""

import os
from pathlib import Path

import pytest


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
