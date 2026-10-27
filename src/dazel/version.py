"""The package version: from the source tree's ``pyproject.toml`` when run from one, else the installed metadata."""

import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

UNKNOWN_VERSION = "0+unknown"
PACKAGE_NAME = "dazel"


def _source_tree_version() -> str | None:
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    if not pyproject.is_file():
        return None
    project = tomllib.loads(pyproject.read_text(encoding="utf-8")).get("project", {})
    return project.get("version") if project.get("name") == PACKAGE_NAME else None


def installed_version() -> str:
    """Return the ``dazel`` version.

    Running from a source tree (``PYTHONPATH=src``, as a CI launcher may do) reports the tree's own
    ``pyproject.toml``, never another dazel that happens to be installed in the interpreter. Otherwise
    the installed distribution's metadata is used, with a placeholder when there is none.
    """
    if (source := _source_tree_version()) is not None:
        return source
    try:
        return version(PACKAGE_NAME)
    except PackageNotFoundError:
        return UNKNOWN_VERSION
