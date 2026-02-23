"""Kiosk configuration for ChatOS.

Parses /etc/chatos/kiosk.conf to produce Chromium flags and shell
variable exports for the kiosk launch scripts. If the file doesn't
exist, sensible defaults are used — graceful degradation.

Usage from shell scripts:
    eval $(/path/to/.venv/bin/python -m src.kiosk_config /etc/chatos/kiosk.conf)
"""

import sys
import tomllib
from pathlib import Path
from urllib.parse import urlparse

from .models import (
    ChromiumConfig,
    FullKioskConfig,
    KioskConfig,
    KioskLoggingConfig,
)

# Hardcoded Chromium kiosk flags — always applied regardless of config.
CHROMIUM_KIOSK_FLAGS: list[str] = [
    "--kiosk",
    "--no-first-run",
    "--disable-translate",
    "--disable-infobars",
    "--noerrdialogs",
    "--disable-session-crashed-bubble",
    "--disable-component-update",
    "--autoplay-policy=no-user-gesture-required",
    "--disable-features=TranslateUI",
    "--disable-background-networking",
    "--disable-sync",
    "--metrics-recording-only",
    "--disable-default-apps",
    "--disable-pinch",
    "--overscroll-history-navigation=disabled",
]


class KioskConfigLoader:
    """Load kiosk configuration from kiosk.conf (TOML)."""

    def __init__(self, config: FullKioskConfig) -> None:
        self._config = config

    @classmethod
    def from_path(cls, path: Path) -> "KioskConfigLoader":
        """Load kiosk config from a TOML file.

        If the file doesn't exist, returns default config.
        """
        if not path.is_file():
            return cls(FullKioskConfig())

        with open(path, "rb") as f:
            raw = tomllib.load(f)

        kiosk_data = raw.get("kiosk", {})
        chromium_data = raw.get("chromium", {})
        logging_data = raw.get("logging", {})

        kiosk_cfg = KioskConfig(**kiosk_data) if kiosk_data else KioskConfig()
        chromium_cfg = ChromiumConfig(**chromium_data) if chromium_data else ChromiumConfig()
        logging_cfg = KioskLoggingConfig(**logging_data) if logging_data else KioskLoggingConfig()

        return cls(FullKioskConfig(
            kiosk=kiosk_cfg,
            chromium=chromium_cfg,
            logging=logging_cfg,
        ))

    @property
    def config(self) -> FullKioskConfig:
        return self._config

    def chromium_flags(self) -> list[str]:
        """Build the complete Chromium flag list.

        Combines hardcoded kiosk flags with config-driven options:
        - --disable-gpu if chromium.disable_gpu is true
        - Extra flags from chromium.extra_flags (space-separated)

        Note: --user-data-dir is intentionally omitted. Chromium's OpenBSD
        unveil() sandbox only unveils $HOME/.config/chromium (the default
        profile path). Custom --user-data-dir paths get ENOENT from unveil.
        Instead, we set HOME to the desired data dir so Chromium uses
        $HOME/.config/chromium naturally.
        """
        flags = list(CHROMIUM_KIOSK_FLAGS)

        if self._config.chromium.disable_gpu:
            flags.append("--disable-gpu")

        extra = self._config.chromium.extra_flags.strip()
        if extra:
            flags.extend(extra.split())

        return flags

    def _extract_port(self) -> str:
        """Extract port from the kiosk URL."""
        parsed = urlparse(self._config.kiosk.url)
        if parsed.port:
            return str(parsed.port)
        return "443" if parsed.scheme == "https" else "80"

    def shell_export(self) -> str:
        """Output shell-compatible variable assignments.

        Designed to be consumed via:
            eval $(.venv/bin/python -m src.kiosk_config /etc/chatos/kiosk.conf)
        """
        k = self._config.kiosk
        c = self._config.chromium
        lg = self._config.logging
        flags_str = " ".join(self.chromium_flags())
        port = self._extract_port()

        lines = [
            f"KIOSK_URL='{k.url}'",
            f"KIOSK_DISPLAY=':{k.display}'",
            f"KIOSK_VT='{k.vt}'",
            f"KIOSK_PORT='{port}'",
            f"KIOSK_SERVER_TIMEOUT='{k.server_timeout}'",
            f"KIOSK_POLL_INTERVAL='{k.poll_interval}'",
            f"KIOSK_LOG_FILE='{lg.log_file}'",
            f"KIOSK_CHROMIUM_DATA_DIR='{c.user_data_dir}'",
            f"KIOSK_CHROMIUM_FLAGS='{flags_str}'",
        ]
        return "\n".join(f"export {line}" for line in lines) + "\n"


def main() -> None:
    """CLI entry point: print shell exports for kiosk config."""
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/etc/chatos/kiosk.conf")
    loader = KioskConfigLoader.from_path(path)
    print(loader.shell_export(), end="")


if __name__ == "__main__":
    main()
