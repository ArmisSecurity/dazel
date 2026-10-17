"""Shared fixtures."""

import os
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point HOME at a scratch directory and drop ambient DAZEL_* variables."""
    home = tmp_path / "home"
    (home / ".docker" / "cli-plugins").mkdir(parents=True)
    (home / ".docker" / "config.json").touch()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("LOGNAME", "tester")
    for name in [n for n in os.environ if n.startswith("DAZEL_")]:
        monkeypatch.delenv(name)
    return home
