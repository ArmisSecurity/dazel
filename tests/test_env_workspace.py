import hashlib
import os
import subprocess
from pathlib import Path

import pytest

from dazel.env import expand_variables
from dazel.workspace import (
    WorkspaceNotFoundError,
    find_workspace,
    is_linked_worktree,
    primary_checkout,
    workspace_digest,
)

from fake_support import make_linked_worktree, make_workspace


@pytest.mark.parametrize(
    ("text", "env", "expected"),
    [
        ("$HOME/.aws:/root/.aws", {"HOME": "/h"}, "/h/.aws:/root/.aws"),
        ("${HOME}/x", {"HOME": "/h"}, "/h/x"),
        ("A=${A:-''}", {}, "A=''"),
        ("A=${A:-''}", {"A": ""}, "A=''"),
        ("A=${A:-''}", {"A": "v"}, "A=v"),
        ("A=${A-d}", {"A": ""}, "A="),
        ("P=${PWD}/.github.com", {"PWD": "/w"}, "P=/w/.github.com"),
        ("$MISSING/x", {}, "/x"),
        ("A=${A:-$B}", {"B": "b"}, "A=b"),
        ("plain", {}, "plain"),
    ],
)
def test_expand_variables(text: str, env: dict[str, str], expected: str) -> None:
    assert expand_variables(text, env) == expected


@pytest.mark.parametrize("marker", ["WORKSPACE", "WORKSPACE.bazel", "MODULE.bazel"])
def test_find_workspace_walks_up_to_any_marker(tmp_path: Path, marker: str) -> None:
    root = tmp_path / "ws"
    nested = root / "a" / "b"
    nested.mkdir(parents=True)
    (root / marker).touch()
    assert find_workspace(nested) == root.resolve()


def test_find_workspace_prefers_the_closest_marker(tmp_path: Path) -> None:
    outer = make_workspace(tmp_path, name="outer")
    inner = make_workspace(outer, name="inner")
    assert find_workspace(inner) == inner.resolve()


def test_find_workspace_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceNotFoundError):
        find_workspace(tmp_path)


def test_workspace_digest_is_md5_of_the_real_path(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    link = tmp_path / "link"
    link.symlink_to(workspace)
    expected = hashlib.md5(str(workspace.resolve()).encode(), usedforsecurity=False).hexdigest()
    assert workspace_digest(link) == expected


def test_digest_differs_between_workspaces(tmp_path: Path) -> None:
    assert workspace_digest(make_workspace(tmp_path, name="a")) != workspace_digest(make_workspace(tmp_path, name="b"))


def test_primary_checkout_is_not_a_linked_worktree(tmp_path: Path) -> None:
    primary = make_workspace(tmp_path)
    (primary / ".git").mkdir()
    assert not is_linked_worktree(primary)


def test_directory_without_git_is_not_a_linked_worktree(tmp_path: Path) -> None:
    assert not is_linked_worktree(make_workspace(tmp_path))


def test_git_file_pointing_into_worktrees_is_a_linked_worktree(tmp_path: Path) -> None:
    primary = make_workspace(tmp_path)
    assert is_linked_worktree(make_linked_worktree(primary))


def test_git_file_of_a_submodule_is_not_a_linked_worktree(tmp_path: Path) -> None:
    submodule = make_workspace(tmp_path)
    (submodule / ".git").write_text("gitdir: ../.git/modules/sub\n", encoding="utf-8")
    assert not is_linked_worktree(submodule)


def git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, env={**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null"}
    )


def test_real_git_worktree_is_linked_and_a_separate_git_dir_clone_is_not(tmp_path: Path) -> None:
    primary = make_workspace(tmp_path, name="primary")
    git(primary, "init", "-q")
    git(primary, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "x")
    linked = tmp_path / "linked"
    git(primary, "worktree", "add", "-q", "--detach", str(linked))
    separate = make_workspace(tmp_path, name="separate")
    git(separate, "init", "-q", "--separate-git-dir", str(tmp_path / "separate-git"))

    assert is_linked_worktree(linked)
    assert primary_checkout(linked) == primary
    assert (separate / ".git").is_file()
    assert not is_linked_worktree(separate)


@pytest.mark.parametrize(
    ("gitdir", "commondir"),
    [("worktrees/clone/.git-sep", True), ("worktrees/clone.git", False)],
    ids=["worktrees-is-not-the-parent", "no-commondir-file"],
)
def test_a_git_file_into_a_directory_merely_called_worktrees_is_not_a_linked_worktree(
    tmp_path: Path, gitdir: str, *, commondir: bool
) -> None:
    separate = make_workspace(tmp_path, name="separate")
    store = tmp_path / gitdir
    store.mkdir(parents=True)
    if commondir:
        (store / "commondir").write_text("../..\n", encoding="utf-8")
    (separate / ".git").write_text(f"gitdir: {store}\n", encoding="utf-8")

    assert not is_linked_worktree(separate)
    assert primary_checkout(separate) == separate


def test_a_checkout_living_under_a_worktrees_directory_is_not_linked(tmp_path: Path) -> None:
    checkout = make_workspace(tmp_path / "worktrees", name="primary")
    (checkout / ".git").mkdir()

    assert not is_linked_worktree(checkout)


def test_primary_checkout_of_a_linked_worktree_is_its_main_clone(tmp_path: Path) -> None:
    primary = make_workspace(tmp_path)
    assert primary_checkout(make_linked_worktree(primary)) == primary
