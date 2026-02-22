"""Tests for the ChatOS kiosk configuration loader."""

from pathlib import Path

import pytest

from src.kiosk_config import CHROMIUM_KIOSK_FLAGS, KioskConfigLoader
from src.models import (
    ChromiumConfig,
    FullKioskConfig,
    KioskConfig,
    KioskLoggingConfig,
)


# -- TestFileLoading --


class TestFileLoading:
    def test_full_config(self, tmp_path: Path) -> None:
        conf = tmp_path / "kiosk.conf"
        conf.write_text(
            '[kiosk]\nurl = "http://127.0.0.1:9000"\ndisplay = "1"\n'
            'vt = "vt07"\nserver_timeout = 60\npoll_interval = 2\n\n'
            '[chromium]\nextra_flags = "--verbose"\n'
            'user_data_dir = "/tmp/chrome"\ndisable_gpu = true\n\n'
            '[logging]\nlog_file = "/tmp/kiosk.log"\n'
        )
        loader = KioskConfigLoader.from_path(conf)
        assert loader.config.kiosk.url == "http://127.0.0.1:9000"
        assert loader.config.kiosk.display == "1"
        assert loader.config.kiosk.vt == "vt07"
        assert loader.config.kiosk.server_timeout == 60
        assert loader.config.kiosk.poll_interval == 2
        assert loader.config.chromium.extra_flags == "--verbose"
        assert loader.config.chromium.user_data_dir == "/tmp/chrome"
        assert loader.config.chromium.disable_gpu is True
        assert loader.config.logging.log_file == "/tmp/kiosk.log"

    def test_missing_file_returns_defaults(self, tmp_path: Path) -> None:
        loader = KioskConfigLoader.from_path(tmp_path / "nonexistent.conf")
        assert loader.config.kiosk.url == "http://127.0.0.1:8400"
        assert loader.config.kiosk.display == "0"
        assert loader.config.chromium.disable_gpu is False
        assert loader.config.logging.log_file == "/var/chatos/logs/kiosk.log"

    def test_partial_config_uses_defaults(self, tmp_path: Path) -> None:
        conf = tmp_path / "kiosk.conf"
        conf.write_text('[kiosk]\nurl = "http://10.0.0.1:3000"\n')
        loader = KioskConfigLoader.from_path(conf)
        assert loader.config.kiosk.url == "http://10.0.0.1:3000"
        # Unset fields get defaults
        assert loader.config.kiosk.display == "0"
        assert loader.config.chromium.user_data_dir == "/var/chatos/chromium"
        assert loader.config.logging.log_file == "/var/chatos/logs/kiosk.log"

    def test_empty_file(self, tmp_path: Path) -> None:
        conf = tmp_path / "kiosk.conf"
        conf.write_text("")
        loader = KioskConfigLoader.from_path(conf)
        assert loader.config.kiosk.url == "http://127.0.0.1:8400"
        assert loader.config.chromium.extra_flags == ""

    def test_custom_values_propagated(self, tmp_path: Path) -> None:
        conf = tmp_path / "kiosk.conf"
        conf.write_text(
            '[chromium]\nuser_data_dir = "/home/test/chrome-data"\n'
            'disable_gpu = true\n'
        )
        loader = KioskConfigLoader.from_path(conf)
        assert loader.config.chromium.user_data_dir == "/home/test/chrome-data"
        assert loader.config.chromium.disable_gpu is True
        # Kiosk section still defaults
        assert loader.config.kiosk.server_timeout == 30

    def test_loads_production_config(self) -> None:
        """Load the actual etc/chatos/kiosk.conf shipped with the project."""
        conf = Path(__file__).parent.parent / "etc" / "chatos" / "kiosk.conf"
        loader = KioskConfigLoader.from_path(conf)
        assert loader.config.kiosk.url == "http://127.0.0.1:8400"
        assert loader.config.kiosk.display == "0"
        assert loader.config.kiosk.vt == "vt05"
        assert loader.config.chromium.user_data_dir == "/var/chatos/chromium"


# -- TestChromiumFlags --


class TestChromiumFlags:
    def test_kiosk_flag_present(self) -> None:
        loader = KioskConfigLoader(FullKioskConfig())
        flags = loader.chromium_flags()
        assert "--kiosk" in flags

    def test_user_data_dir_present(self) -> None:
        loader = KioskConfigLoader(FullKioskConfig())
        flags = loader.chromium_flags()
        assert "--user-data-dir=/var/chatos/chromium" in flags

    def test_disable_gpu_off_by_default(self) -> None:
        loader = KioskConfigLoader(FullKioskConfig())
        flags = loader.chromium_flags()
        assert "--disable-gpu" not in flags

    def test_disable_gpu_when_enabled(self) -> None:
        cfg = FullKioskConfig(chromium=ChromiumConfig(disable_gpu=True))
        loader = KioskConfigLoader(cfg)
        flags = loader.chromium_flags()
        assert "--disable-gpu" in flags

    def test_extra_flags_appended(self) -> None:
        cfg = FullKioskConfig(chromium=ChromiumConfig(extra_flags="--verbose --remote-debugging-port=9222"))
        loader = KioskConfigLoader(cfg)
        flags = loader.chromium_flags()
        assert "--verbose" in flags
        assert "--remote-debugging-port=9222" in flags

    def test_empty_extra_flags_no_empty_string(self) -> None:
        loader = KioskConfigLoader(FullKioskConfig())
        flags = loader.chromium_flags()
        assert "" not in flags

    def test_flag_count_minimum(self) -> None:
        """At least the hardcoded flags + user-data-dir."""
        loader = KioskConfigLoader(FullKioskConfig())
        flags = loader.chromium_flags()
        assert len(flags) >= len(CHROMIUM_KIOSK_FLAGS) + 1

    def test_custom_user_data_dir(self) -> None:
        cfg = FullKioskConfig(chromium=ChromiumConfig(user_data_dir="/tmp/test-chrome"))
        loader = KioskConfigLoader(cfg)
        flags = loader.chromium_flags()
        assert "--user-data-dir=/tmp/test-chrome" in flags


# -- TestShellExport --


class TestShellExport:
    def test_all_variables_present(self) -> None:
        loader = KioskConfigLoader(FullKioskConfig())
        export = loader.shell_export()
        expected_vars = [
            "KIOSK_URL",
            "KIOSK_DISPLAY",
            "KIOSK_VT",
            "KIOSK_PORT",
            "KIOSK_SERVER_TIMEOUT",
            "KIOSK_POLL_INTERVAL",
            "KIOSK_LOG_FILE",
            "KIOSK_CHROMIUM_DATA_DIR",
            "KIOSK_CHROMIUM_FLAGS",
        ]
        for var in expected_vars:
            assert f"export {var}=" in export

    def test_display_has_colon_prefix(self) -> None:
        loader = KioskConfigLoader(FullKioskConfig())
        export = loader.shell_export()
        assert "KIOSK_DISPLAY=':0'" in export

    def test_custom_display(self) -> None:
        cfg = FullKioskConfig(kiosk=KioskConfig(display="2"))
        loader = KioskConfigLoader(cfg)
        export = loader.shell_export()
        assert "KIOSK_DISPLAY=':2'" in export

    def test_port_extracted_from_url(self) -> None:
        loader = KioskConfigLoader(FullKioskConfig())
        export = loader.shell_export()
        assert "KIOSK_PORT='8400'" in export

    def test_port_extracted_custom_url(self) -> None:
        cfg = FullKioskConfig(kiosk=KioskConfig(url="http://10.0.0.1:9090"))
        loader = KioskConfigLoader(cfg)
        export = loader.shell_export()
        assert "KIOSK_PORT='9090'" in export

    def test_port_default_http(self) -> None:
        cfg = FullKioskConfig(kiosk=KioskConfig(url="http://localhost"))
        loader = KioskConfigLoader(cfg)
        export = loader.shell_export()
        assert "KIOSK_PORT='80'" in export

    def test_port_default_https(self) -> None:
        cfg = FullKioskConfig(kiosk=KioskConfig(url="https://localhost"))
        loader = KioskConfigLoader(cfg)
        export = loader.shell_export()
        assert "KIOSK_PORT='443'" in export

    def test_flags_string_contains_kiosk(self) -> None:
        loader = KioskConfigLoader(FullKioskConfig())
        export = loader.shell_export()
        assert "--kiosk" in export

    def test_custom_values_propagated(self) -> None:
        cfg = FullKioskConfig(
            kiosk=KioskConfig(url="http://192.168.1.1:5000", server_timeout=45),
            logging=KioskLoggingConfig(log_file="/tmp/test.log"),
        )
        loader = KioskConfigLoader(cfg)
        export = loader.shell_export()
        assert "KIOSK_URL='http://192.168.1.1:5000'" in export
        assert "KIOSK_SERVER_TIMEOUT='45'" in export
        assert "KIOSK_LOG_FILE='/tmp/test.log'" in export


# -- TestModels --


class TestModels:
    def test_kiosk_config_defaults(self) -> None:
        cfg = KioskConfig()
        assert cfg.url == "http://127.0.0.1:8400"
        assert cfg.display == "0"
        assert cfg.vt == "vt05"
        assert cfg.server_timeout == 30
        assert cfg.poll_interval == 1

    def test_chromium_config_defaults(self) -> None:
        cfg = ChromiumConfig()
        assert cfg.extra_flags == ""
        assert cfg.user_data_dir == "/var/chatos/chromium"
        assert cfg.disable_gpu is False

    def test_kiosk_logging_config_defaults(self) -> None:
        cfg = KioskLoggingConfig()
        assert cfg.log_file == "/var/chatos/logs/kiosk.log"

    def test_full_kiosk_config_nested_defaults(self) -> None:
        cfg = FullKioskConfig()
        assert cfg.kiosk.url == "http://127.0.0.1:8400"
        assert cfg.chromium.user_data_dir == "/var/chatos/chromium"
        assert cfg.logging.log_file == "/var/chatos/logs/kiosk.log"

    def test_kiosk_config_custom(self) -> None:
        cfg = KioskConfig(url="http://10.0.0.1:3000", display="2", vt="vt03")
        assert cfg.url == "http://10.0.0.1:3000"
        assert cfg.display == "2"
        assert cfg.vt == "vt03"

    def test_chromium_config_custom(self) -> None:
        cfg = ChromiumConfig(
            extra_flags="--verbose",
            user_data_dir="/tmp/chrome",
            disable_gpu=True,
        )
        assert cfg.extra_flags == "--verbose"
        assert cfg.user_data_dir == "/tmp/chrome"
        assert cfg.disable_gpu is True
