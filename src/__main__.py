"""Allow running ChatOS via `python -m src`."""

import sys

from .cli import main as cli_main


def main() -> None:
    if "--serve" in sys.argv:
        sys.argv.remove("--serve")
        from .ws_server import main as ws_main

        ws_main()
    else:
        cli_main()


main()
