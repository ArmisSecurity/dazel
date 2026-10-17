# dazel
Run Google's bazel inside a docker container via a seamless proxy.

bazel is awesome at creating fast and reproducible builds on your own development environment.
The problem is that it works in an imperfect and non-portable environment.

Enter dazel.

dazel allows you to create your build environment as a Docker image, either via a Dockerfile or a prebuilt repository.
The tool itself is a small Python package that sends the command line arguments directly to bazel inside the container, and maps all of the necessary volumes to make it seamless to you.
It uses the 'docker exec' command to achieve this, and maps the current directory and the bazel-WORKDIR link directory so that the results appear on the host as if you ran the command locally on the host.

It is run the same way you would bazel:
```bash
dazel build //my/cool/package/...
dazel run //my/cool/package:target
```

This was a simple build and run.
The command line arguments were sent as-is into the docker container, and the output was run in the same manner inside the container.

Running the command for the first time will start the container on it's own, and it will automatically detect if there is need to rebuild or restart the container (if the Dockerfile is newer than the conatiner).
You can configure anything you need through the ".dazelrc" file in the same directory.
Take a look at the configuration section for information on how to write one.

## Installation

```bash
uv tool install dazel   # or: pipx install dazel / pip install dazel
```

Requires Python 3.11 or newer and docker. Even bazel is not required on the host.

## Versioning

The PyPI distribution is still called `dazel` but is now published from the
[ArmisSecurity fork](https://github.com/ArmisSecurity/dazel) as a new `1.x` line: a src-layout package
with typed modules, replacing the single-file `0.0.x` script. It includes the
`--ulimit nofile=1048576:1048576` patch shipped in 0.0.43 and keeps every `.dazelrc` key working.

## Parallel git worktrees

By default every workspace shares one container (`dazel`) and one bazel output base, and the container
is recreated whenever the bound source directory differs, so builds from several git worktrees restart
each other. Set `DAZEL_PER_WORKSPACE_CONTAINER=True` to get, per workspace:

* a container named `<DAZEL_INSTANCE_NAME>_<md5(realpath(workspace))>` and the bazel output base
  `<DAZEL_BAZEL_USER_OUTPUT_ROOT>/<md5>`;
* a **shared** image, compose project and network (compose `up` no longer forces a recreate, so a new
  worktree never restarts the shared services);
* host ports published only by the primary checkout. A linked worktree (`.git` is a file pointing into
  `worktrees/`) publishes none, so fixed `DAZEL_PORTS` do not collide. Override with
  `DAZEL_PORTS_ONLY_PRIMARY=False`;
* `DAZEL_BAZEL_DISK_CACHE=/host/path` mounted at the same path in the container (created on the host
  if missing). dazel passes no bazel flags; point `--disk_cache` at it from your bazelrc.

Remove a workspace's container, output base and run file (read-only directories included) with:

```bash
dazel --dazel-clean-workspace
```

The flag is only recognised as the sole argument, so it cannot collide with bazel's own arguments.
It refuses to run unless `DAZEL_PER_WORKSPACE_CONTAINER` (or `DAZEL_WORKSPACE_HEX`) is enabled,
because the container and output base are otherwise shared.

## Configuration

You can configure dazel in two ways (or combine):
* A `.dazelrc` file in the workspace root (the closest parent holding `WORKSPACE`, `WORKSPACE.bazel` or `MODULE.bazel`). It is executed as Python.
* Environment variables with the configuration parameters mentioned below.

Note that specific environment variables supercede the values in the .dazelrc file.

The possible parameters to set are (with their defaults):
```python
# The name of the docker container to run.
DAZEL_INSTANCE_NAME="dazel"

# The name of the dazel image to build or pull.
DAZEL_IMAGE_NAME="dazel"

# The command to run when running the image (the continuous command that will
# hold the container active while we connect to it).
DAZEL_RUN_COMMAND="/bin/bash"

# The command to run to invoke docker (can be changed to `nvidia-docker` for GPUs).
DAZEL_DOCKER_COMMAND="docker"

# The path to the Dockerfile to use to build the dazel image.
DAZEL_DOCKERFILE="Dockerfile.dazel"  # in DAZEL_DIRECTORY

# The repository to pull the dazel image from.
DAZEL_REPOSITORY="dazel"

# The directory to start looking for the bazel workspace from.
DAZEL_DIRECTORY=$PWD

# The command to run inside the container.
# NOTE: You should add flags to the .bazelrc file instead of here, since it is
#       also shared in the volume and it is a much cleaner way.
DAZEL_COMMAND="/usr/bin/bazel"

# Add any additional volumes you want to share between the host and the docker
# container, in the normal "hostdir:dockerdir" format.
# This can be a python iterable, or a comma-separated string.
# If working on windows add drive name to avoid conflicts, e.g.
# DAZEL_VOLUMES = ["C:\\tmp:/C/tmp"]
DAZEL_VOLUMES=[]

# Add any ports you want to publish from the dazel container to the host, in the
# normal "interface:dockerport:hostport" (e.g. "0.0.0.0:80:80").
# This can be useful if you use the "dazel run //my/cool/webserver/target"
# command for example, and need to publish port 80.
DAZEL_PORTS=[]

# Add any environment variables you want to set in the dazel container
# They will be set via -e in the docker run command
# This can be a python iterable, or a comma-separated string.
DAZEL_ENV_VARS=[]

# The GPUs to expose to the Docker container, "all" for every installed GPU
DAZEL_GPUS=""

# The name of the network on which to load all run dependencies and dazel container.
# If you are using a docker-compose.yml file to load the environment, this must
# be the network name to which all of the necessary dependencies are connected.
DAZEL_NETWORK="dazel"

# Add any additional images that you want to run as dependencies and hook up to
# the same docker network as the main container.
# The format is the standard "repository/image:tag", but you can optionally add
# the name of the container to create with "repository/image:tag::container".
# This is useful if you want to add "postgres" or "rabbitmq" for instance, and
# have them run as part of your test environment in a seamless reproducible way.
# This can be a python iterable, or a comma-separated string.
# Note: alternatively, you can use a docker-compose.yml file for dependencies.
DAZEL_RUN_DEPS=[]

# Add a docker-compose.yml file here to use it to load any services you want to
# launch as part of the environment for running bazel.
# This can be a much more complex environment than what is possible using run
# dependencies.
# Note: you can control both the project name and which services to run with the
# variables below.
DAZEL_DOCKER_COMPOSE_FILE=""

# The command to run to invoke docker-compose (can be changed to
# `nvidia-docker-compose` for GPUs).
DAZEL_DOCKER_COMPOSE_COMMAND="docker-compose"

# If using a docker-compose.yml file, this will set the COMPOSE_PROJECT_NAME
# environment variable and thus the project name.
DAZEL_DOCKER_COMPOSE_PROJECT_NAME="dazel"

# If using a docker-compose.yml file, you can specify the services to run in the
# file (and empty string means all services - as in running: docker-compose up).
# This can be a python iterable, or a comma-separated string.
DAZEL_DOCKER_COMPOSE_SERVICES=""

# Whether or not to run in privileged mode (fixes bazel sandboxing issues on some
# systems). Note that this can be a python boolean equivalent, so if setting
# this from the environment, simply set it to an empty string.
DAZEL_DOCKER_RUN_PRIVILEGED=False

# Path to custom .bazelrc file to use when running the bazel commands.
DAZEL_BAZEL_RC_FILE=""

# Use the :delegated flag of the --volume option of docker for the bind-mounting of
# the bazel cache directory. This vastly improves throughput on MacOSX.
# More information on the :delegated flag: https://docs.docker.com/docker-for-mac/osxfs-caching/.
# NOTE: This will fail on Docker versions < 17.04.
DAZEL_DELEGATED_VOLUME=True

# The user, in the same format as the --user option docker run and docker exec takes,
# to use when starting the container and executing commands inside of the container
DAZEL_USER=""

# NEW in 1.0 -- see "Parallel git worktrees" below.
DAZEL_PER_WORKSPACE_CONTAINER=False
DAZEL_PORTS_ONLY_PRIMARY=True   # default: True when DAZEL_PER_WORKSPACE_CONTAINER is on
DAZEL_BAZEL_DISK_CACHE=""
```

Also available: `DAZEL_RUN_FILE` (default `.dazel_run`, holds the container name),
`DAZEL_BAZEL_USER_OUTPUT_ROOT` (default `~/.cache/bazel/_bazel_<user>`), `DAZEL_PLATFORM`,
`DAZEL_SHM_SIZE`, `DAZEL_DOCKER_BUILD_ARGS`, `DAZEL_DOCKER_MACHINE`, `DAZEL_WORKSPACE_HEX` (legacy,
suffixes container, image and compose project with the workspace hash) and `DAZEL_RC_FILE` (path of
the rc file to use).

Details worth knowing:
* `$VAR`, `${VAR}` and `${VAR:-default}` are expanded in `DAZEL_VOLUMES`, `DAZEL_PORTS` and `DAZEL_ENV_VARS`.
* Boolean variables set from the environment are false when empty, `0`, `false`, `no`, `off` or `none`.
* Relative `DAZEL_DOCKERFILE`, `DAZEL_DOCKER_COMPOSE_FILE` and `DAZEL_RUN_FILE` are resolved against the workspace root.
* Commands are executed as argv lists, never through a shell.


## Library use

```python
import dazel

instance = dazel.DockerInstance.from_config()
instance.docker_command  # "docker"
instance.instance_name  # "dazel" or "dazel_<md5>" in per-workspace mode
```

## Development

```bash
uv sync
uv run ruff check
uv run ruff format --check
uv run pyrefly check
uv run pytest                  # unit tests; add -m integration for the docker test
uv build                       # sdist and wheel into dist/
```

Layout: `config` (rc + env into a frozen `Config`), `workspace`, `plan` (names, ports, mounts),
`bazel`, `docker` and `compose` (pure argv builders), `executor` (the only subprocess boundary),
`instance` (lifecycle), `clean`, `cli`.

Releases: push a `v*` tag; the release workflow builds the sdist and wheel and publishes to PyPI
through trusted publishing.
