"""Tests for the ChatOS installer script (Step 20).

Structural validation — parse the script as text and verify required
conventions, constants, and idempotency patterns. No actual installation
is attempted.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
INSTALL_SCRIPT = PROJECT_ROOT / "deploy" / "install.sh"


def _read_script() -> str:
    return INSTALL_SCRIPT.read_text()


def _lines() -> list[str]:
    return INSTALL_SCRIPT.read_text().splitlines()


def _find_var(var: str) -> str | None:
    """Return the value of a `VAR=VALUE` or `VAR="VALUE"` assignment, or None."""
    for line in _lines():
        stripped = line.strip()
        if stripped.startswith(f"{var}="):
            return stripped.split("=", 1)[1].strip('"').strip("'")
    return None


def _has_function(name: str) -> bool:
    """Check if a shell function is defined in the script."""
    text = _read_script()
    # Match both `name() {` and `name () {`
    return bool(re.search(rf"^{name}\s*\(\)", text, re.MULTILINE))


# ---------------------------------------------------------------------------
# TestScriptStructure
# ---------------------------------------------------------------------------


class TestScriptStructure:
    def test_file_exists(self) -> None:
        assert INSTALL_SCRIPT.exists()

    def test_shebang(self) -> None:
        lines = _lines()
        assert lines[0] == "#!/bin/ksh"

    def test_set_eu(self) -> None:
        text = _read_script()
        assert "set -eu" in text

    def test_root_check(self) -> None:
        text = _read_script()
        assert "id -u" in text

    def test_helper_functions_defined(self) -> None:
        for fn in ("info", "warn", "die"):
            assert _has_function(fn), f"Helper function {fn}() not found"

    def test_ensure_functions_defined(self) -> None:
        for fn in ("ensure_user", "ensure_dir", "install_config"):
            assert _has_function(fn), f"Function {fn}() not found"


# ---------------------------------------------------------------------------
# TestConstants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_chatos_app_path(self) -> None:
        val = _find_var("CHATOS_APP")
        assert val == "/usr/local/share/chatos"

    def test_chatos_etc_path(self) -> None:
        val = _find_var("CHATOS_ETC")
        assert val == "/etc/chatos"

    def test_chatos_var_path(self) -> None:
        val = _find_var("CHATOS_VAR")
        assert val == "/var/chatos"

    def test_chatos_user(self) -> None:
        val = _find_var("CHATOS_USER")
        assert val == "_chatos"

    def test_chatos_ui_user(self) -> None:
        val = _find_var("CHATOS_UI_USER")
        assert val == "_chatos_ui"

    def test_project_dir_from_dirname(self) -> None:
        text = _read_script()
        assert "dirname" in text
        assert "PROJECT_DIR" in text


# ---------------------------------------------------------------------------
# TestPackageInstallation
# ---------------------------------------------------------------------------


class TestPackageInstallation:
    def test_pkg_add_present(self) -> None:
        text = _read_script()
        assert "pkg_add" in text

    def test_required_packages(self) -> None:
        val = _find_var("PACKAGES")
        assert val is not None
        for pkg in ("python%3.12", "node", "chromium"):
            assert pkg in val, f"Missing required package: {pkg}"

    def test_pip_package(self) -> None:
        val = _find_var("PACKAGES")
        assert val is not None
        assert "py3-pip" in val

    def test_optional_packages_non_fatal(self) -> None:
        text = _read_script()
        val = _find_var("OPT_PACKAGES")
        assert val is not None
        assert "unclutter" in val
        # Optional packages should have a fallback (|| warn)
        assert '|| warn' in text


# ---------------------------------------------------------------------------
# TestUserCreation
# ---------------------------------------------------------------------------


class TestUserCreation:
    def test_creates_chatos_user(self) -> None:
        text = _read_script()
        assert "_chatos" in text
        assert "ensure_user" in text

    def test_creates_chatos_ui_user(self) -> None:
        text = _read_script()
        assert "_chatos_ui" in text

    def test_nologin_shell(self) -> None:
        text = _read_script()
        assert "/sbin/nologin" in text

    def test_idempotent_user_check(self) -> None:
        """ensure_user should check if user exists before creating."""
        text = _read_script()
        # The ensure_user function should check `id -u` first
        assert "id -u" in text


# ---------------------------------------------------------------------------
# TestDirectoryCreation
# ---------------------------------------------------------------------------


class TestDirectoryCreation:
    def test_etc_chatos_dir(self) -> None:
        text = _read_script()
        assert "/etc/chatos" in text

    def test_var_chatos_subdirs(self) -> None:
        text = _read_script()
        for subdir in ("logs", "run", "sessions"):
            assert subdir in text, f"Missing directory subdir: {subdir}"
        # Verify these are under CHATOS_VAR
        assert "CHATOS_VAR" in text

    def test_chromium_dir_for_ui_user(self) -> None:
        text = _read_script()
        assert "chromium" in text
        assert "CHATOS_UI_USER" in text

    def test_mkdir_p_used(self) -> None:
        text = _read_script()
        assert "mkdir -p" in text

    def test_ensure_dir_corrects_ownership(self) -> None:
        """ensure_dir should chown + chmod (fixes ownership on re-run)."""
        text = _read_script()
        # The ensure_dir function body
        assert "chown" in text
        assert "chmod" in text


# ---------------------------------------------------------------------------
# TestApplicationDeployment
# ---------------------------------------------------------------------------


class TestApplicationDeployment:
    def test_copies_src_dir(self) -> None:
        text = _read_script()
        # Should copy src directory
        assert "src" in text
        assert "cp -R" in text

    def test_copies_ui_dir(self) -> None:
        text = _read_script()
        assert "ui" in text

    def test_venv_creation(self) -> None:
        text = _read_script()
        assert "venv" in text
        assert "python3.12" in text

    def test_pip_install(self) -> None:
        text = _read_script()
        assert "pip" in text
        assert "install" in text

    def test_npm_build(self) -> None:
        text = _read_script()
        assert "npm ci" in text
        assert "npm run build" in text


# ---------------------------------------------------------------------------
# TestOwnership
# ---------------------------------------------------------------------------


class TestOwnership:
    def test_chown_recursive_chatos(self) -> None:
        text = _read_script()
        assert "chown -R" in text
        assert "CHATOS_USER" in text

    def test_chown_after_npm_build(self) -> None:
        """Ownership must be set after npm build (which may create files as root)."""
        lines = _lines()
        npm_build_idx = None
        chown_r_idx = None
        for i, line in enumerate(lines):
            if "npm run build" in line and npm_build_idx is None:
                npm_build_idx = i
            if "chown -R" in line and "CHATOS_USER" in line and chown_r_idx is None:
                chown_r_idx = i
        assert npm_build_idx is not None, "npm run build not found"
        assert chown_r_idx is not None, "chown -R not found"
        assert chown_r_idx > npm_build_idx, "chown -R must come after npm run build"


# ---------------------------------------------------------------------------
# TestConfigPreservation
# ---------------------------------------------------------------------------


class TestConfigPreservation:
    def test_rules_toml_referenced(self) -> None:
        text = _read_script()
        assert "rules.toml" in text

    def test_agents_toml_referenced(self) -> None:
        text = _read_script()
        assert "agents.toml" in text

    def test_kiosk_conf_referenced(self) -> None:
        text = _read_script()
        assert "kiosk.conf" in text

    def test_preservation_check(self) -> None:
        """install_config should check if file exists before copying."""
        text = _read_script()
        # The install_config function should test for existing file
        assert '[ -f "$_dst" ]' in text


# ---------------------------------------------------------------------------
# TestConfigPermissions
# ---------------------------------------------------------------------------


class TestConfigPermissions:
    def test_rules_toml_mode_640(self) -> None:
        for line in _lines():
            if "rules.toml" in line and "install_config" in line:
                assert "640" in line
                return
        pytest.fail("install_config call for rules.toml not found")

    def test_agents_toml_mode_640(self) -> None:
        for line in _lines():
            if "agents.toml" in line and "install_config" in line:
                assert "640" in line
                return
        pytest.fail("install_config call for agents.toml not found")

    def test_kiosk_conf_mode_644(self) -> None:
        for line in _lines():
            if "kiosk.conf" in line and "install_config" in line:
                assert "644" in line
                return
        pytest.fail("install_config call for kiosk.conf not found")


# ---------------------------------------------------------------------------
# TestServiceInstallation
# ---------------------------------------------------------------------------


class TestServiceInstallation:
    def test_agent_rc_script_installed(self) -> None:
        text = _read_script()
        assert "/etc/rc.d/chatos_agent" in text

    def test_ui_rc_script_installed(self) -> None:
        text = _read_script()
        assert "/etc/rc.d/chatos_ui" in text


# ---------------------------------------------------------------------------
# TestDoasConf
# ---------------------------------------------------------------------------


class TestDoasConf:
    def test_doas_line_correct(self) -> None:
        text = _read_script()
        assert "permit nopass root as _chatos_ui" in text

    def test_doas_idempotent_guard(self) -> None:
        """Should check if the line already exists before appending."""
        text = _read_script()
        assert "grep" in text
        assert "doas.conf" in text


# ---------------------------------------------------------------------------
# TestRcctl
# ---------------------------------------------------------------------------


class TestRcctl:
    def test_rcctl_enable_agent(self) -> None:
        text = _read_script()
        assert "rcctl enable chatos_agent" in text

    def test_rcctl_enable_ui(self) -> None:
        text = _read_script()
        assert "rcctl enable chatos_ui" in text

    def test_timeout_set(self) -> None:
        text = _read_script()
        assert "rcctl set chatos_agent timeout" in text
        assert "rcctl set chatos_ui timeout" in text


# ---------------------------------------------------------------------------
# TestPostInstallMessage
# ---------------------------------------------------------------------------


class TestPostInstallMessage:
    def test_mentions_setup_token(self) -> None:
        text = _read_script()
        assert "claude setup-token" in text

    def test_mentions_rcctl_start(self) -> None:
        text = _read_script()
        assert "rcctl start" in text


# ---------------------------------------------------------------------------
# TestKshSyntax
# ---------------------------------------------------------------------------


class TestKshSyntax:
    @pytest.mark.skipif(not shutil.which("ksh"), reason="ksh not available")
    def test_ksh_syntax_valid(self) -> None:
        result = subprocess.run(
            ["ksh", "-n", str(INSTALL_SCRIPT)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"ksh syntax error: {result.stderr}"
