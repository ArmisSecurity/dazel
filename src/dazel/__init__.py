"""Run bazel inside a docker container, in a reproducible and portable way."""

from importlib.metadata import version

from dazel.cli import main
from dazel.config import Config, load_config
from dazel.instance import DockerInstance

__version__ = version("dazel")
__all__ = ["Config", "DockerInstance", "__version__", "load_config", "main"]
