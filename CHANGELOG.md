# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project follows
[Semantic Versioning](https://semver.org/).

## [1.0.0]

First release maintained by Armis open source. A rewrite of the single-file 0.0.x `dazel.py` as a typed
package. It keeps the `.dazelrc` format, and the [README](README.md#upgrading-from-00x) lists the
behaviour changes.

### Added

- Per-workspace containers and output bases (`DAZEL_PER_WORKSPACE_CONTAINER`), with serialised start-up
  and ports published only from the primary checkout (`DAZEL_PORTS_ONLY_PRIMARY`).
- `DAZEL_BAZEL_DISK_CACHE` to mount a shared bazel disk cache.
- `~/.dazelrc` and `.dazelrc.local` layered around the workspace `.dazelrc`
  ([nadirizr/dazel#47](https://github.com/nadirizr/dazel/issues/47)).
- The container restarts when an rc file changes
  ([nadirizr/dazel#42](https://github.com/nadirizr/dazel/issues/42)).
- `DAZEL_BUILD_DIRECTORY` for the `docker build` context
  ([nadirizr/dazel#35](https://github.com/nadirizr/dazel/issues/35)).
- `DAZEL_GROUPS` for `--group-add` ([nadirizr/dazel#40](https://github.com/nadirizr/dazel/pull/40)).
- `--dazel-version`, `--dazel-container-name`, `--dazel-clean-workspace` and `--dazel-clean-legacy`.
- `MODULE.bazel` and `WORKSPACE.bazel` mark a workspace.
- `--ulimit nofile=1048576:1048576` on the container (shipped in 0.0.43 but never committed).
- A Debian bookworm `Dockerfile` with checksum-pinned Bazelisk.

### Changed

- Commands run as argv lists instead of through a shell. Values expand only `$V`, `${V}`, `${V-d}` and
  `${V:-d}`.
- Relative paths resolve against the workspace root.
- A command killed by signal N exits with `128 + N`.
- Requires Python 3.11 or newer. Packaged with `pyproject.toml` (hatchling) and managed with uv.

### Removed

- Python 2 and Windows support, `setup.py`, `setup.cfg`, `README.rst` and the committed wheels.
