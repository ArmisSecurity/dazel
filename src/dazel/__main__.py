"""``python -m dazel``: runs dazel from a source tree without installing it."""

import sys

from dazel.cli import main

if __name__ == "__main__":
    sys.exit(main())
