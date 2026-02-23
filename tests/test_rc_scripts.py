"""Tests for ChatOS systemd service units (deploy/systemd/).

Structural validation -- parse the unit files as INI and verify required
systemd conventions, dependency ordering, hardening, and kiosk script
references.  No actual service start/stop is attempted.
"""

import configparser
import os
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).parent.parent
SYSTEMD_DIR = PROJECT_ROOT / "deploy" / "systemd"
KIOSK_DIR = PROJECT_ROOT / "deploy" / "kiosk"
AGENT_SERVICE = SYSTEMD_DIR / "chatos-agent.service"
UI_SERVICE = SYSTEMD_DIR / "chatos-ui.service"
README = SYSTEMD_DIR / "README.md"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_unit(path: Path) -> configparser.ConfigParser:
    """Parse a systemd unit file into a ConfigParser.

    systemd unit files are INI-style so ConfigParser works directly.
    Interpolation is disabled to avoid issues with ``%`` specifiers.
    """
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(path)
    return parser


def _read_text(path: Path) -> str:
    return path.read_text()


# ===========================================================================
# TestServiceFilesExist
# ===========================================================================


class TestServiceFilesExist:
    """All expected files under deploy/systemd/ are present and well-formed."""

    def test_systemd_directory_exists(self) -> None:
        assert SYSTEMD_DIR.is_dir()

    def test_agent_service_file_exists(self) -> None:
        assert AGENT_SERVICE.exists(), "chatos-agent.service is missing"

    def test_ui_service_file_exists(self) -> None:
        assert UI_SERVICE.exists(), "chatos-ui.service is missing"

    def test_readme_exists(self) -> None:
        assert README.exists(), "README.md is missing from deploy/systemd/"

    def test_agent_service_has_no_shebang(self) -> None:
        """systemd units are INI files, not scripts -- must not start with #!"""
        text = _read_text(AGENT_SERVICE)
        assert not text.startswith("#!"), "Agent service file has a shebang line"

    def test_ui_service_has_no_shebang(self) -> None:
        text = _read_text(UI_SERVICE)
        assert not text.startswith("#!"), "UI service file has a shebang line"


# ===========================================================================
# TestAgentServiceUnit
# ===========================================================================


class TestAgentServiceUnit:
    """Validate chatos-agent.service structure: [Unit], [Service], [Install]."""

    @pytest.fixture(autouse=True)
    def _load(self) -> None:
        self.unit = _parse_unit(AGENT_SERVICE)
        self.text = _read_text(AGENT_SERVICE)

    # -- [Unit] section -----------------------------------------------------

    def test_has_unit_section(self) -> None:
        assert self.unit.has_section("Unit")

    def test_description_mentions_chatos_and_agent(self) -> None:
        desc = self.unit.get("Unit", "Description")
        assert "ChatOS" in desc
        assert "agent" in desc.lower()

    def test_after_network_online(self) -> None:
        after = self.unit.get("Unit", "After")
        assert "network-online.target" in after

    def test_wants_network_online(self) -> None:
        wants = self.unit.get("Unit", "Wants")
        assert "network-online.target" in wants

    # -- [Service] section --------------------------------------------------

    def test_has_service_section(self) -> None:
        assert self.unit.has_section("Service")

    def test_type_is_simple(self) -> None:
        assert self.unit.get("Service", "Type") == "simple"

    def test_user_is_chatos(self) -> None:
        assert self.unit.get("Service", "User") == "_chatos"

    def test_group_is_chatos(self) -> None:
        assert self.unit.get("Service", "Group") == "_chatos"

    def test_working_directory_is_share_chatos(self) -> None:
        wd = self.unit.get("Service", "WorkingDirectory")
        assert wd == "/usr/local/share/chatos"

    def test_exec_start_uses_venv_python(self) -> None:
        cmd = self.unit.get("Service", "ExecStart")
        assert cmd.startswith("/usr/local/share/chatos/venv/bin/python")

    def test_exec_start_has_serve_flag(self) -> None:
        cmd = self.unit.get("Service", "ExecStart")
        assert "--serve" in cmd

    def test_exec_start_has_rules_flag(self) -> None:
        cmd = self.unit.get("Service", "ExecStart")
        assert "--rules /etc/chatos/rules.toml" in cmd

    def test_exec_start_has_log_dir_flag(self) -> None:
        cmd = self.unit.get("Service", "ExecStart")
        assert "--log-dir /var/chatos/logs" in cmd

    def test_exec_start_has_home_dir_flag(self) -> None:
        cmd = self.unit.get("Service", "ExecStart")
        assert "--home-dir" in cmd

    def test_exec_start_has_static_dir_flag(self) -> None:
        cmd = self.unit.get("Service", "ExecStart")
        assert "--static-dir" in cmd

    def test_exec_start_has_cli_path_flag(self) -> None:
        cmd = self.unit.get("Service", "ExecStart")
        assert "--cli-path" in cmd

    def test_exec_start_pre_creates_runtime_directories(self) -> None:
        pre = self.unit.get("Service", "ExecStartPre")
        assert "mkdir" in pre
        for d in ("/var/chatos/logs", "/var/chatos/run", "/var/chatos/sessions"):
            assert d in pre, f"ExecStartPre does not create {d}"

    def test_restart_policy_is_on_failure(self) -> None:
        assert self.unit.get("Service", "Restart") == "on-failure"

    def test_restart_sec_is_positive(self) -> None:
        val = int(self.unit.get("Service", "RestartSec"))
        assert val > 0

    def test_timeout_start_sec_is_at_least_30(self) -> None:
        val = int(self.unit.get("Service", "TimeoutStartSec"))
        assert val >= 30

    def test_timeout_stop_sec_is_at_least_30(self) -> None:
        val = int(self.unit.get("Service", "TimeoutStopSec"))
        assert val >= 30

    # -- [Install] section --------------------------------------------------

    def test_has_install_section(self) -> None:
        assert self.unit.has_section("Install")

    def test_wanted_by_multi_user_target(self) -> None:
        assert "multi-user.target" in self.unit.get("Install", "WantedBy")


# ===========================================================================
# TestAgentServiceHardening
# ===========================================================================


class TestAgentServiceHardening:
    """Security hardening directives in chatos-agent.service."""

    @pytest.fixture(autouse=True)
    def _load(self) -> None:
        self.unit = _parse_unit(AGENT_SERVICE)
        self.text = _read_text(AGENT_SERVICE)

    def test_hardening_comment_present(self) -> None:
        """The unit should have a comment marking the hardening section."""
        assert "hardening" in self.text.lower()

    def test_no_new_privileges(self) -> None:
        val = self.unit.get("Service", "NoNewPrivileges")
        assert val.lower() == "true"

    def test_protect_system_strict(self) -> None:
        assert self.unit.get("Service", "ProtectSystem") == "strict"

    def test_protect_home_read_only(self) -> None:
        assert self.unit.get("Service", "ProtectHome") == "read-only"

    def test_read_write_paths_includes_var_chatos(self) -> None:
        val = self.unit.get("Service", "ReadWritePaths")
        assert "/var/chatos" in val

    def test_read_only_paths_includes_etc_chatos(self) -> None:
        val = self.unit.get("Service", "ReadOnlyPaths")
        assert "/etc/chatos" in val

    def test_read_only_paths_includes_share_chatos(self) -> None:
        val = self.unit.get("Service", "ReadOnlyPaths")
        assert "/usr/local/share/chatos" in val


# ===========================================================================
# TestUiServiceUnit
# ===========================================================================


class TestUiServiceUnit:
    """Validate chatos-ui.service structure and directives."""

    @pytest.fixture(autouse=True)
    def _load(self) -> None:
        self.unit = _parse_unit(UI_SERVICE)
        self.text = _read_text(UI_SERVICE)

    # -- [Unit] section -- dependency on agent ------------------------------

    def test_has_unit_section(self) -> None:
        assert self.unit.has_section("Unit")

    def test_description_mentions_chatos(self) -> None:
        desc = self.unit.get("Unit", "Description")
        assert "ChatOS" in desc

    def test_description_mentions_ui_or_kiosk(self) -> None:
        desc = self.unit.get("Unit", "Description").lower()
        assert "ui" in desc or "kiosk" in desc

    def test_after_chatos_agent(self) -> None:
        """UI must start after the agent service."""
        after = self.unit.get("Unit", "After")
        assert "chatos-agent.service" in after

    def test_requires_chatos_agent(self) -> None:
        """UI must hard-depend on the agent service."""
        requires = self.unit.get("Unit", "Requires")
        assert "chatos-agent.service" in requires

    # -- [Service] section --------------------------------------------------

    def test_has_service_section(self) -> None:
        assert self.unit.has_section("Service")

    def test_type_is_simple(self) -> None:
        assert self.unit.get("Service", "Type") == "simple"

    def test_no_user_directive(self) -> None:
        """UI service should not set User -- kiosk launch manages privileges."""
        assert not self.unit.has_option("Service", "User")

    def test_exec_start_references_launch_kiosk(self) -> None:
        cmd = self.unit.get("Service", "ExecStart")
        assert "launch-kiosk.sh" in cmd

    def test_exec_start_uses_kiosk_directory(self) -> None:
        cmd = self.unit.get("Service", "ExecStart")
        assert "/usr/local/share/chatos/deploy/kiosk/" in cmd

    # -- ExecStartPre: port check ------------------------------------------

    def test_exec_start_pre_checks_port_8400(self) -> None:
        pre = self.unit.get("Service", "ExecStartPre")
        assert "8400" in pre
        assert "nc" in pre

    def test_exec_start_pre_has_timeout(self) -> None:
        """Port check must have a timeout to avoid hanging forever."""
        pre = self.unit.get("Service", "ExecStartPre")
        assert "timeout" in pre

    def test_exec_start_pre_has_retry_loop(self) -> None:
        """Port check retries in a loop to handle the agent startup race."""
        pre = self.unit.get("Service", "ExecStartPre")
        assert "while" in pre
        assert "sleep" in pre

    def test_exec_start_pre_logs_failure_message(self) -> None:
        """Port check outputs a meaningful message when it gives up."""
        pre = self.unit.get("Service", "ExecStartPre")
        assert "echo" in pre or "logger" in pre

    # -- ExecStopPost: console reset ----------------------------------------

    def test_exec_stop_post_calls_reset_console(self) -> None:
        post = self.unit.get("Service", "ExecStopPost")
        assert "reset-console.sh" in post

    def test_exec_stop_post_uses_kiosk_directory(self) -> None:
        post = self.unit.get("Service", "ExecStopPost")
        assert "/usr/local/share/chatos/deploy/kiosk/" in post

    # -- Restart / timeout --------------------------------------------------

    def test_restart_policy_is_on_failure(self) -> None:
        assert self.unit.get("Service", "Restart") == "on-failure"

    def test_restart_sec_is_positive(self) -> None:
        val = int(self.unit.get("Service", "RestartSec"))
        assert val > 0

    def test_timeout_start_sec_is_at_least_30(self) -> None:
        val = int(self.unit.get("Service", "TimeoutStartSec"))
        assert val >= 30

    def test_timeout_stop_sec_is_at_least_30(self) -> None:
        val = int(self.unit.get("Service", "TimeoutStopSec"))
        assert val >= 30

    # -- [Install] section --------------------------------------------------

    def test_has_install_section(self) -> None:
        assert self.unit.has_section("Install")

    def test_wanted_by_multi_user_target(self) -> None:
        assert "multi-user.target" in self.unit.get("Install", "WantedBy")


# ===========================================================================
# TestKioskScriptsExist
# ===========================================================================


class TestKioskScriptsExist:
    """Kiosk scripts referenced by the UI service must exist and be executable."""

    def test_launch_kiosk_exists(self) -> None:
        assert (KIOSK_DIR / "launch-kiosk.sh").exists()

    def test_xinitrc_exists(self) -> None:
        assert (KIOSK_DIR / "xinitrc").exists()

    def test_reset_console_exists(self) -> None:
        assert (KIOSK_DIR / "reset-console.sh").exists()

    def test_launch_kiosk_is_executable(self) -> None:
        assert os.access(KIOSK_DIR / "launch-kiosk.sh", os.X_OK)

    def test_reset_console_is_executable(self) -> None:
        assert os.access(KIOSK_DIR / "reset-console.sh", os.X_OK)

    def test_agent_service_references_no_kiosk_scripts(self) -> None:
        """The agent service must not reference any kiosk scripts."""
        text = _read_text(AGENT_SERVICE)
        assert "launch-kiosk" not in text
        assert "reset-console" not in text

    def test_ui_service_references_launch_kiosk(self) -> None:
        """The UI service ExecStart must point to the kiosk launch script."""
        unit = _parse_unit(UI_SERVICE)
        cmd = unit.get("Service", "ExecStart")
        assert "launch-kiosk.sh" in cmd

    def test_ui_service_references_reset_console(self) -> None:
        """The UI service ExecStopPost must point to the console reset script."""
        unit = _parse_unit(UI_SERVICE)
        post = unit.get("Service", "ExecStopPost")
        assert "reset-console.sh" in post


# ===========================================================================
# TestServiceDependencyOrdering
# ===========================================================================


class TestServiceDependencyOrdering:
    """Cross-service dependency relationships are correct."""

    @pytest.fixture(autouse=True)
    def _load(self) -> None:
        self.agent = _parse_unit(AGENT_SERVICE)
        self.ui = _parse_unit(UI_SERVICE)

    def test_ui_after_agent(self) -> None:
        after = self.ui.get("Unit", "After")
        assert "chatos-agent.service" in after

    def test_ui_requires_agent(self) -> None:
        requires = self.ui.get("Unit", "Requires")
        assert "chatos-agent.service" in requires

    def test_agent_does_not_depend_on_ui(self) -> None:
        """Agent runs independently -- must not reference the UI service."""
        after = self.agent.get("Unit", "After", fallback="")
        wants = self.agent.get("Unit", "Wants", fallback="")
        requires = self.agent.get("Unit", "Requires", fallback="")
        combined = after + wants + requires
        assert "chatos-ui" not in combined

    def test_both_target_multi_user(self) -> None:
        agent_target = self.agent.get("Install", "WantedBy")
        ui_target = self.ui.get("Install", "WantedBy")
        assert agent_target == ui_target == "multi-user.target"


# ===========================================================================
# TestReadme
# ===========================================================================


class TestReadme:
    """The systemd README documents key operational information."""

    @pytest.fixture(autouse=True)
    def _load(self) -> None:
        self.text = _read_text(README)

    def test_mentions_agent_service(self) -> None:
        assert "chatos-agent.service" in self.text

    def test_mentions_ui_service(self) -> None:
        assert "chatos-ui.service" in self.text

    def test_mentions_override_mechanism(self) -> None:
        """README should explain how to customize unit flags via overrides."""
        assert "systemctl edit" in self.text or "override" in self.text.lower()

    def test_mentions_env_file(self) -> None:
        """README should reference /etc/chatos/env for the API key."""
        assert "/etc/chatos/env" in self.text

    def test_mentions_installation(self) -> None:
        assert "install" in self.text.lower()
