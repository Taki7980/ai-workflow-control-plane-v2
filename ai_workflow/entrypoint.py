from __future__ import annotations

import sys

from ._version import __version__
from .benchmark_external_cli import handles as external_handles
from .benchmark_external_cli import main as external_main
from .cli import main as cli_main
from .run_cli import handles as run_handles
from .run_cli import main as run_main
from .scip_cli import handles as scip_handles
from .scip_cli import main as scip_main


def main() -> None:
    """Expose package-level flags before delegating to the existing CLI."""

    if len(sys.argv) == 2 and sys.argv[1] == "--version":
        print(__version__)
        return
    argv = sys.argv[1:]
    if external_handles(argv):
        external_main(argv)
        return
    if scip_handles(argv):
        scip_main(argv)
        return
    if run_handles(argv):
        run_main(argv)
        return
    cli_main()
