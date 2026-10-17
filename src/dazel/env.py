"""Shell-style variable expansion for configuration values."""

import re
from collections.abc import Mapping

_VARIABLE = re.compile(r"\$(?:(\w+)|\{(\w+)(?:(:?)-([^}]*))?\})")


def expand_variables(text: str, env: Mapping[str, str]) -> str:
    """Expand ``$VAR``, ``${VAR}``, ``${VAR-default}`` and ``${VAR:-default}`` like a shell.

    Unset variables expand to the empty string. ``-`` applies the default when the variable is
    unset, ``:-`` also when it is empty.
    """

    def substitute(match: re.Match[str]) -> str:
        name = match.group(1) or match.group(2)
        colon, default = match.group(3), match.group(4)
        value = env.get(name)
        if default is not None and (value is None or (colon and not value)):
            return expand_variables(default, env)
        return value or ""

    return _VARIABLE.sub(substitute, text)
