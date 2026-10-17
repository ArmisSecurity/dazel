"""Bazel command construction and output base layout."""

import getpass
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from dazel.config import Config

OUTPUT_SUBDIRS = ("external", "action_cache", "execroot")
BAZEL_ROOT_MARKER = "/_bazel"


@dataclass(frozen=True, slots=True)
class OutputLayout:
    """Where bazel keeps its outputs on the host and which parts are bind mounted."""

    user_root: str = ""
    base: Path | None = None
    mount_dirs: tuple[Path, ...] = ()


def container_user_root() -> str:
    """Return the ``--output_user_root`` used inside the container for the default (root) user."""
    return f"/var/bazel/workspace/_bazel_{getpass.getuser()}"


def derive_user_root(directory: Path) -> str:
    """Infer the user output root from where the ``bazel-out`` symlink points, if anywhere."""
    real = str((directory / "bazel-out" / "..").resolve())
    if BAZEL_ROOT_MARKER not in real:
        return ""
    first, _, rest = real.partition(BAZEL_ROOT_MARKER)
    return f"{first}{BAZEL_ROOT_MARKER}{rest.split('/')[0]}"


def output_layout(cfg: Config, digest: str) -> OutputLayout:
    """Resolve the output base for a workspace; ``digest`` isolates it when non-empty."""
    user_root = cfg.bazel_user_output_root or derive_user_root(cfg.directory)
    if not user_root:
        return OutputLayout()
    base = (Path(user_root) / digest).resolve()
    names = (*OUTPUT_SUBDIRS, cfg.directory.resolve().name)
    return OutputLayout(user_root, base, tuple((base / name).resolve() for name in names))


def bazel_argv(cfg: Config, layout: OutputLayout, args: Sequence[str]) -> list[str]:
    """Return the full command run inside the container for the given bazel arguments."""
    if not cfg.command:
        return [*args]
    extra = [f"--bazelrc={cfg.bazel_rc_file}"] if cfg.bazel_rc_file else []
    if cfg.user:
        if layout.user_root:
            extra.append(f"--output_user_root={layout.user_root}")
    elif layout.base:
        extra += [f"--output_user_root={container_user_root()}", f"--output_base={layout.base}"]
    return [*cfg.command, *extra, *args]
