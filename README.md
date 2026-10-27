# dazel

[![CI](https://img.shields.io/github/actions/workflow/status/ArmisSecurity/dazel/ci.yml?branch=master&label=CI&color=0A66C2)](https://github.com/ArmisSecurity/dazel/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/dazel?color=0A66C2)](https://pypi.org/project/dazel/)
[![Python](https://img.shields.io/python/required-version-toml?tomlFilePath=https%3A%2F%2Fraw.githubusercontent.com%2FArmisSecurity%2Fdazel%2Fmaster%2Fpyproject.toml&label=python&color=0A66C2)](pyproject.toml)
[![License](https://img.shields.io/github/license/ArmisSecurity/dazel?color=0A66C2)](LICENSE)

Run [Bazel](https://bazel.build) inside a Docker container, as if it ran on your host.

Bazel builds are fast and reproducible, but only as reproducible as the machine they run on. dazel
defines the build environment as a Docker image and runs bazel in it through a transparent proxy:

```bash
dazel build //my/package/...
dazel test //my/package:tests
dazel run //my/package:binary -- --flag
```

The arguments go to bazel in the container unchanged (`docker exec`, as an argv list, never through a
shell). The workspace and bazel's output directories are bind mounted at the same paths, so `bazel-bin`,
`bazel-out` and the rest work on the host exactly as they would without dazel. The container is built,
started and restarted on demand.

dazel is maintained by [Armis](https://www.armis.com) open source. It was created by
[nadirizr](https://github.com/nadirizr/dazel); 1.0 is a typed rewrite of the original `dazel.py`
that keeps its `.dazelrc` format.

## Installation

```bash
uv tool install dazel     # or: pipx install dazel
```

dazel needs Python 3.11 or newer and Docker. Bazel itself does not need to be installed on the host.

## Quick start

1. Describe the build environment in a `Dockerfile.dazel` in the workspace root. The
   [`Dockerfile`](Dockerfile) in this repository is a good start: Debian with
   [Bazelisk](https://github.com/bazelbuild/bazelisk) installed as `bazel`, so the workspace's
   `.bazelversion` selects the Bazel release.
2. Optionally, add a `.dazelrc` next to it (see [Configuration](#configuration)):

   ```python
   DAZEL_REPOSITORY = "myproject"
   DAZEL_VOLUMES = ["$HOME/.ssh:/root/.ssh:ro"]
   DAZEL_PER_WORKSPACE_CONTAINER = True
   ```

3. Run `dazel build //...`. The first run builds the image and starts the container. Later runs reuse
   it. dazel restarts the container when the Dockerfile or an rc file changes.

If `DAZEL_DOCKERFILE` does not exist, dazel pulls `DAZEL_REPOSITORY/DAZEL_IMAGE_NAME` instead, so a team
can share a prebuilt image.

## Commands

All arguments are passed to bazel, except these, which dazel handles when they are the whole command
line:

| Command | Effect |
|---|---|
| `dazel --dazel-version` | Print the dazel version. |
| `dazel --dazel-container-name` | Print the container name for this workspace (useful in scripts). |
| `dazel --dazel-clean-workspace` | Remove this workspace's container, bazel output base and run file. This only works in per-workspace mode, because otherwise both are shared. |
| `dazel --dazel-clean-legacy [--yes]` | List, or with `--yes` delete, the shared output base left behind by dazel 0.0.x. See [Upgrading from 0.0.x](#upgrading-from-00x). |

A command killed by signal N exits with status `128 + N`, like a shell. Ctrl-C reaches bazel in the
container and does not produce a traceback.

## Parallel git worktrees

By default all workspaces share one container (`dazel`) and one bazel output base. The container is
recreated whenever a different workspace uses it, so builds in two git worktrees keep restarting each
other. Set `DAZEL_PER_WORKSPACE_CONTAINER = True` to give each workspace:

- **Its own container and output base**: `<DAZEL_INSTANCE_NAME>_<md5>` and
  `<DAZEL_BAZEL_USER_OUTPUT_ROOT>/<md5>`, keyed on the workspace's real path. dazel writes
  `WORKSPACE: <path>` into `<base>/README`, so a base whose worktree is gone can be identified and
  removed.
- **A shared image, compose project and network.** Compose runs with `--project-directory` set to the
  compose file's location in the *primary* checkout, so relative bind mounts resolve the same from every
  worktree and a new worktree never restarts the shared services.
- **Serialised start-up.** A file lock (`<output root>/.dazel.lock`) guards building the image and
  starting the services and the container. A dazel that waited checks again once it holds the lock, so
  concurrent commands start the container once.
- **Ports from the primary checkout only.** Linked worktrees publish no `DAZEL_PORTS`, so fixed ports
  don't collide (`DAZEL_PORTS_ONLY_PRIMARY`).

A per-workspace output base starts cold. Share work between them with a disk cache:
`DAZEL_BAZEL_DISK_CACHE = "~/.cache/bazel-disk:/root/.cache/bazel-disk"` mounts one host directory in
every container (creating it first, so Docker doesn't create it root-owned). Point bazel's `--disk_cache`
at the container path in your bazelrc. dazel passes no bazel flags of its own.

## Configuration

Settings come from four layers. Lowest precedence first:

1. `~/.dazelrc`: per-user defaults.
2. `.dazelrc` in the workspace root, or the file named by the `DAZEL_RC_FILE` environment variable: the
   project configuration.
3. `.dazelrc.local` in the workspace root: personal overrides. Add it to `.gitignore`.
4. `DAZEL_*` environment variables.

rc files are **executed as Python**, and every top-level `DAZEL_*` name they define is a setting. A later
layer replaces a key's value whole; lists are not merged.

The workspace root is the closest parent of the current directory (or of `DAZEL_DIRECTORY`) that holds a
`WORKSPACE`, `WORKSPACE.bazel` or `MODULE.bazel` file.

Value rules:

- **Lists** are a Python iterable or a comma-separated string.
- **Flags** are booleans. From the environment, `""`, `0`, `false`, `no` and `off` are false.
- **Variables** (`$VAR`, `${VAR}`, `${VAR-default}`, `${VAR:-default}`) are expanded from the environment
  in `DAZEL_VOLUMES`, `DAZEL_PORTS`, `DAZEL_ENV_VARS` and the path settings. In a value, `$PWD` is the
  directory dazel was started in.
- **Paths** (`DAZEL_DOCKERFILE`, `DAZEL_BUILD_DIRECTORY`, `DAZEL_DOCKER_COMPOSE_FILE`, `DAZEL_RUN_FILE`,
  `DAZEL_BAZEL_DISK_CACHE`) also expand a leading `~`. A relative path resolves against the workspace
  root.
- **Commands** (`DAZEL_COMMAND`, `DAZEL_RUN_COMMAND`, `DAZEL_DOCKER_COMMAND`,
  `DAZEL_DOCKER_COMPOSE_COMMAND`, `DAZEL_DOCKER_BUILD_ARGS`) are split like a shell would split them, but
  nothing is expanded in them.

### Image and container

| Key | Default | Meaning |
|---|---|---|
| `DAZEL_DOCKERFILE` | `Dockerfile.dazel` | Dockerfile for the image. If it doesn't exist, the image is pulled instead. |
| `DAZEL_BUILD_DIRECTORY` | workspace root | Build context for `docker build`. |
| `DAZEL_DOCKER_BUILD_ARGS` | none | Extra `docker build` arguments, such as `--cache-from` or `--build-arg`. |
| `DAZEL_REPOSITORY` | `dazel` | Image repository, and the registry path it is pulled from. |
| `DAZEL_IMAGE_NAME` | `dazel` | Image name. |
| `DAZEL_INSTANCE_NAME` | `dazel` | Container name. |
| `DAZEL_RUN_COMMAND` | `/bin/bash` | Command that keeps the container alive. |
| `DAZEL_DOCKER_COMMAND` | `docker` | Docker executable. |
| `DAZEL_DOCKER_MACHINE` | none | `docker-machine` whose environment is used. |
| `DAZEL_PLATFORM` | none | `--platform` for build and run, e.g. `linux/amd64` on Apple silicon. |
| `DAZEL_DOCKER_RUN_PRIVILEGED` | `False` | Run and exec privileged. Needed by bazel's sandbox in most images. |
| `DAZEL_USER` | none | `--user` for run and exec. |
| `DAZEL_GROUPS` | none | `--group-add` for each entry, e.g. the host's `docker` group id. |
| `DAZEL_GPUS` | none | `--gpus`, e.g. `all`. |
| `DAZEL_SHM_SIZE` | none | `--shm-size`. |
| `DAZEL_VOLUMES` | none | Extra `host:container[:options]` mounts. |
| `DAZEL_PORTS` | none | Published ports, `[interface:]host:container`. |
| `DAZEL_ENV_VARS` | none | `NAME=value` entries passed with `-e`. |
| `DAZEL_DIRECTORY` | workspace root | Directory mounted and used as the working directory. |
| `DAZEL_RUN_FILE` | `.dazel_run` | File recording the container name; dazel restarts the container when the Dockerfile or an rc file is newer. Empty disables it, and then the container is only restarted when it isn't running. |

The container always gets `--ulimit nofile=1048576:1048576`.

### Bazel

| Key | Default | Meaning |
|---|---|---|
| `DAZEL_COMMAND` | `/usr/bin/bazel` | Bazel command in the container. Put bazel flags in a bazelrc. |
| `DAZEL_BAZEL_RC_FILE` | none | `--bazelrc` for the bazel command. |
| `DAZEL_BAZEL_USER_OUTPUT_ROOT` | `~/.cache/bazel/_bazel_<user>` | Host output root, created if missing. If empty, it is derived from where the workspace's `bazel-out` symlink points. |
| `DAZEL_BAZEL_DISK_CACHE` | none | `host[:container]` bind mount for bazel's disk cache. The container path defaults to the host path. |
| `DAZEL_DELEGATED_VOLUME` | `True` | `:delegated` on the output mounts, which is faster on macOS. |

### Workspace isolation

| Key | Default | Meaning |
|---|---|---|
| `DAZEL_PER_WORKSPACE_CONTAINER` | `False` | One container and output base per workspace on a shared image. See [Parallel git worktrees](#parallel-git-worktrees). |
| `DAZEL_PORTS_ONLY_PRIMARY` | `True` in per-workspace mode, else `False` | Publish `DAZEL_PORTS` only from the primary checkout. |
| `DAZEL_WORKSPACE_HEX` | `False` | Older isolation mode: suffixes the container, compose project and built image with the workspace hash. |

### Services

| Key | Default | Meaning |
|---|---|---|
| `DAZEL_DOCKER_COMPOSE_FILE` | none | Compose file whose services start with the container. |
| `DAZEL_DOCKER_COMPOSE_SERVICES` | all | Services to start. |
| `DAZEL_DOCKER_COMPOSE_COMMAND` | `docker-compose` | Compose executable, e.g. `docker compose`. |
| `DAZEL_DOCKER_COMPOSE_PROJECT_NAME` | `dazel` | Compose project name. |
| `DAZEL_NETWORK` | `dazel` | Network for the container and its services. With a compose file it is prefixed with the project name, unless it is `host`, `bridge` or `none`. |
| `DAZEL_RUN_DEPS` | none | Containers started on the same network, as `image[:tag][::name]`. Used when there is no compose file or the compose command isn't installed. |

### Recipes

- **`$HOME` inside the container.** Variables are expanded on the host. To give the container your host
  home path, pass it explicitly: `DAZEL_ENV_VARS = ["HOME=$HOME"]`.
- **SSH agent.** Mount the socket and pass its path:
  `DAZEL_VOLUMES = ["$SSH_AUTH_SOCK:/ssh-agent"]` and `DAZEL_ENV_VARS = ["SSH_AUTH_SOCK=/ssh-agent"]`.
- **Docker from inside the container.** Mount `/var/run/docker.sock` through `DAZEL_VOLUMES`. When you run
  as a non-root user, also set `DAZEL_GROUPS` to the socket's group id.
- **Non-root containers.** With `DAZEL_USER`, set `DAZEL_BAZEL_USER_OUTPUT_ROOT` to a directory that user
  owns. Docker creates missing bind-mount sources as root.

## Upgrading from 0.0.x

1.0 reads the same `.dazelrc` keys. These things behave differently:

- **No shell.** Commands run as argv lists. Values are no longer passed through the host shell, so
  command substitution, `||`, globs and arithmetic in values are gone; only the variable forms listed in
  [Configuration](#configuration) are expanded. Compute anything else in the rc file, which is Python, or
  in the calling script.
- **Paths.** Relative `DAZEL_DOCKERFILE`, `DAZEL_DOCKER_COMPOSE_FILE` and `DAZEL_RUN_FILE` resolve against
  the workspace root, not the current directory.
- **Exit status.** A command killed by a signal exits with `128 + N` instead of raising an exception.
- **Workspaces.** `WORKSPACE.bazel` and `MODULE.bazel` mark a workspace too. Windows support was dropped.
- **New in 1.0.**
  - Per-workspace containers, the disk cache mount, the `--dazel-*` commands.
  - `~/.dazelrc` and `.dazelrc.local`.
  - `DAZEL_BUILD_DIRECTORY` and `DAZEL_GROUPS`.
  - Restarting the container when an rc file changes.

After switching to `DAZEL_PER_WORKSPACE_CONTAINER`, start dazel once (it removes the old shared `dazel`
container), then run `dazel --dazel-clean-legacy` to see the shared output base 0.0.x left under the
output root, and `dazel --dazel-clean-legacy --yes` to delete it. Scripts that hard-code the container name
`dazel` should read `.dazel_run` or call `dazel --dazel-container-name`.

On Linux the container runs as root, so files it writes into bind-mounted directories are root-owned.
When dazel can't remove them, it retries through a throw-away container of the same image. If that also
fails, it prints the command to run.

## Development

```bash
uv sync            # create .venv with dazel and the dev tools
prek install       # install the pre-commit and commit-msg hooks
uv run pytest      # unit tests with coverage
uv run pytest -m integration --no-cov   # lifecycle tests against a real docker daemon
prek run --all-files                    # ruff, pyrefly, uv.lock and file hygiene
```

Commit messages and pull request titles follow [Conventional Commits](https://www.conventionalcommits.org).
[gitfluff](https://github.com/Goldziher/gitfluff) checks them in the `commit-msg` hook and in CI.

Releases are cut by pushing a `v<version>` tag that matches `pyproject.toml`. The release workflow then
publishes to PyPI through trusted publishing.

## License

[MIT](LICENSE). Copyright (c) 2016 nadirizr and the dazel contributors.
