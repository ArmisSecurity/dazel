# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project follows
[Semantic Versioning](https://semver.org/) from 1.0.0.

Entries before 1.0.0 were reconstructed from the git history and the PyPI upload dates of
[nadirizr/dazel](https://github.com/nadirizr/dazel). Each change is listed under the first release
that shipped it. Bumps to the sample Dockerfile's Bazel version, and releases with no other user-visible
change (0.0.4, 0.0.7, 0.0.21), are left out.

## [Unreleased]

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

## [0.0.43] - 2025-06-30

- `DAZEL_PLATFORM` passes `--platform` to `docker run` ([#70](https://github.com/nadirizr/dazel/pull/70)).
- The container runs with `--ulimit nofile=1048576:1048576`. This change was published to PyPI but never committed upstream.

## [0.0.42] - 2023-11-16

- `DAZEL_GPUS` passes `--gpus` to `docker run` ([#65](https://github.com/nadirizr/dazel/pull/65)).
- `DAZEL_SHM_SIZE` passes `--shm-size` to `docker run` ([#68](https://github.com/nadirizr/dazel/pull/68)).

## [0.0.41] - 2022-04-01

- Import `Iterable` from `collections.abc`, for Python 3.10 ([#63](https://github.com/nadirizr/dazel/pull/63)).

## [0.0.40] - 2021-12-20

- Podman compatibility ([#62](https://github.com/nadirizr/dazel/pull/62)).

## [0.0.39] - 2021-09-29

- `DAZEL_NETWORK` accepts Docker's built-in `host`, `bridge` and `none` networks ([#59](https://github.com/nadirizr/dazel/pull/59)).
- Windows support ([#61](https://github.com/nadirizr/dazel/pull/61)).

## [0.0.38] - 2020-04-19

- `DAZEL_DOCKER_BUILD_ARGS` adds arguments to `docker build` ([#52](https://github.com/nadirizr/dazel/pull/52)).

## [0.0.37] - 2020-04-15

- `DAZEL_ENV_VARS` passes environment variables to the container ([#51](https://github.com/nadirizr/dazel/pull/51)).

## [0.0.36] - 2018-06-27

- `DAZEL_USER` sets the user for `docker run` and `docker exec` ([#39](https://github.com/nadirizr/dazel/pull/39)).

## [0.0.35] - 2018-05-24

- Compatibility fixes for older Python 3 versions.

## [0.0.34] - 2018-01-11

- The bazel output directories are mounted `:delegated`, which is faster on macOS (`DAZEL_DELEGATED_VOLUME`).

## [0.0.33] - 2018-01-03

- `COLUMNS`, `LINES` and `TERM` are passed into the container ([#26](https://github.com/nadirizr/dazel/pull/26)).

## [0.0.32] - 2017-08-28

- `DAZEL_DOCKER_COMMAND` selects the docker executable, e.g. `nvidia-docker` for GPUs ([#20](https://github.com/nadirizr/dazel/pull/20)).

## [0.0.31] - 2017-08-20

- Docker and docker-compose logs go to stderr, so stdout carries only bazel's output ([#18](https://github.com/nadirizr/dazel/pull/18)).
- The sample image file was renamed from `Dockerfile.dazel` to `Dockerfile`.

## [0.0.30] - 2017-03-26

- Reverted the tar build context and image selection changes from 0.0.27 to 0.0.29 ([#15](https://github.com/nadirizr/dazel/pull/15)).

## [0.0.29] - 2017-02-28

- The tar build context honours `.dockerignore` ([#14](https://github.com/nadirizr/dazel/pull/14)).

## [0.0.28] - 2017-02-28

- Use the newest image by creation date rather than by tag ([#13](https://github.com/nadirizr/dazel/pull/13)).

## [0.0.27] - 2017-02-22

- Pull the image before building it ([#11](https://github.com/nadirizr/dazel/pull/11)).
- Build from a tar context owned by uid and gid 0 ([#12](https://github.com/nadirizr/dazel/pull/12)).

## [0.0.26] - 2017-01-08

- Workspace-specific container names are opt-in through `DAZEL_WORKSPACE_HEX` ([#10](https://github.com/nadirizr/dazel/pull/10)).

## [0.0.25] - 2016-11-19

- Several workspaces can run dazel at the same time, each with its own container.

## [0.0.24] - 2016-08-28

- docker-compose services are recreated when the container has to be recreated ([#7](https://github.com/nadirizr/dazel/pull/7)).

## [0.0.23] - 2016-08-07

- `DAZEL_DOCKER_MACHINE` selects a docker-machine to build and run on.

## [0.0.22] - 2016-07-24

- Compatibility with Bazel 0.3.0 and later ([#4](https://github.com/nadirizr/dazel/pull/4)).

## [0.0.20] - 2016-04-11

- The sample image installs Bazel from its Debian package instead of building from master.

## [0.0.19] - 2016-03-22

- The bazel output base is kept on the host, so the build cache survives container restarts.

## [0.0.18] - 2016-03-19

- All compose images are built and pulled before `docker-compose up -d`.

## [0.0.17] - 2016-03-18

- dazel can be run from a subdirectory of the workspace.
- Check that docker-compose is installed before using it.

## [0.0.16] - 2016-03-17

- `DAZEL_DOCKER_COMPOSE_FILE` starts docker-compose services next to the container.

## [0.0.15] - 2016-03-14

- The container is recreated when its network changed.

## [0.0.14] - 2016-03-14

- Fixed sharing of bazel's `external` directory.

## [0.0.13] - 2016-03-14

- The container is restarted when another workspace with the same configuration uses it.

## [0.0.12] - 2016-03-13

- `DAZEL_RUN_COMMAND` sets the command that keeps the container alive.

## [0.0.11] - 2016-03-12

- dazel works in a workspace where bazel never ran, before its output symlinks exist.

## [0.0.10] - 2016-03-10

- `DAZEL_BAZEL_RC_FILE` passes a custom `--bazelrc`.

## [0.0.9] - 2016-03-10

- Fixed output redirection on some systems.

## [0.0.8] - 2016-03-10

- `DAZEL_DOCKER_RUN_PRIVILEGED` runs the container privileged.

## [0.0.6] - 2016-03-10

- Run dependencies can be given container names (`image::name`).

## [0.0.5] - 2016-03-10

- `DAZEL_PORTS` publishes ports from the container.

## [0.0.3] - 2016-03-09

- `DAZEL_RUN_DEPS` and `DAZEL_NETWORK` start dependency containers on a shared network.

## [0.0.2] - 2016-03-09

- Python 3 fixes and a `dazel` executable script.

## [0.0.1] - 2016-03-09

- First release: run bazel commands in a Docker container built from a Dockerfile or pulled from a
  repository, with the workspace and bazel output directories mounted, and extra volumes from
  `DAZEL_VOLUMES`.

[Unreleased]: https://github.com/ArmisSecurity/dazel/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/ArmisSecurity/dazel/releases/tag/v1.0.0
[0.0.43]: https://pypi.org/project/dazel/0.0.43/
[0.0.42]: https://pypi.org/project/dazel/0.0.42/
[0.0.41]: https://pypi.org/project/dazel/0.0.41/
[0.0.40]: https://pypi.org/project/dazel/0.0.40/
[0.0.39]: https://pypi.org/project/dazel/0.0.39/
[0.0.38]: https://pypi.org/project/dazel/0.0.38/
[0.0.37]: https://pypi.org/project/dazel/0.0.37/
[0.0.36]: https://pypi.org/project/dazel/0.0.36/
[0.0.35]: https://pypi.org/project/dazel/0.0.35/
[0.0.34]: https://pypi.org/project/dazel/0.0.34/
[0.0.33]: https://pypi.org/project/dazel/0.0.33/
[0.0.32]: https://pypi.org/project/dazel/0.0.32/
[0.0.31]: https://pypi.org/project/dazel/0.0.31/
[0.0.30]: https://pypi.org/project/dazel/0.0.30/
[0.0.29]: https://pypi.org/project/dazel/0.0.29/
[0.0.28]: https://pypi.org/project/dazel/0.0.28/
[0.0.27]: https://pypi.org/project/dazel/0.0.27/
[0.0.26]: https://pypi.org/project/dazel/0.0.26/
[0.0.25]: https://pypi.org/project/dazel/0.0.25/
[0.0.24]: https://pypi.org/project/dazel/0.0.24/
[0.0.23]: https://pypi.org/project/dazel/0.0.23/
[0.0.22]: https://pypi.org/project/dazel/0.0.22/
[0.0.20]: https://pypi.org/project/dazel/0.0.20/
[0.0.19]: https://pypi.org/project/dazel/0.0.19/
[0.0.18]: https://pypi.org/project/dazel/0.0.18/
[0.0.17]: https://pypi.org/project/dazel/0.0.17/
[0.0.16]: https://pypi.org/project/dazel/0.0.16/
[0.0.15]: https://pypi.org/project/dazel/0.0.15/
[0.0.14]: https://pypi.org/project/dazel/0.0.14/
[0.0.13]: https://pypi.org/project/dazel/0.0.13/
[0.0.12]: https://pypi.org/project/dazel/0.0.12/
[0.0.11]: https://pypi.org/project/dazel/0.0.11/
[0.0.10]: https://pypi.org/project/dazel/0.0.10/
[0.0.9]: https://pypi.org/project/dazel/0.0.9/
[0.0.8]: https://pypi.org/project/dazel/0.0.8/
[0.0.6]: https://pypi.org/project/dazel/0.0.6/
[0.0.5]: https://pypi.org/project/dazel/0.0.5/
[0.0.3]: https://pypi.org/project/dazel/0.0.3/
[0.0.2]: https://pypi.org/project/dazel/0.0.2/
[0.0.1]: https://pypi.org/project/dazel/0.0.1/
