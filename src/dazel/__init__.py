"""Run bazel inside a docker container, in a reproducible and portable way."""

from dazel.cli import main
from dazel.config import Config, load_config
from dazel.instance import DockerInstance
from dazel.version import installed_version

__version__ = installed_version()
__all__ = ["Config", "DockerInstance", "__version__", "load_config", "main"]
