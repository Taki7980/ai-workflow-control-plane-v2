from __future__ import annotations

import sys

from ._version import __version__
from .cli import main as cli_main


def main() -> None:
    """Expose package-level flags before delegating to the existing CLI."""

    if len(sys.argv) == 2 and sys.argv[1] == "--version":
        print(__version__)
        return
    cli_main()
