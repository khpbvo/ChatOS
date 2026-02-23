"""Allow running ChatOS via `python -m src`."""

import os
import sys
from pathlib import Path

from .cli import main as cli_main

DEFAULT_ENV_FILE = Path("/etc/chatos/env")


def load_env_file(path: Path = DEFAULT_ENV_FILE) -> None:
    """Load key=value pairs from an env file into os.environ.

    Silently skips if the file does not exist or is unreadable.
    Only sets variables that are not already in the environment
    (existing env vars take precedence).
    """
    try:
        text = path.read_text()
    except (OSError, PermissionError):
        return

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = value


def main() -> None:
    load_env_file()

    if "--serve" in sys.argv:
        sys.argv.remove("--serve")
        from .ws_server import main as ws_main

        ws_main()
    else:
        cli_main()


if __name__ == "__main__":
    main()
