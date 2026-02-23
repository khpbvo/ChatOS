"""Tests for the ChatOS OpenBSD rc.d service scripts (Step 16).

Structural validation — parse the scripts as text and verify required
rc.d conventions are followed. No actual service start/stop is attempted.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
AGENT_SCRIPT = PROJECT_ROOT / "deploy" / "rc.d" / "chatos_agent"
UI_SCRIPT = PROJECT_ROOT / "deploy" / "rc.d" / "chatos_ui"
RC_CONF_EXAMPLE = PROJECT_ROOT / "deploy" / "rc.d" / "rc.conf.local.example"


def _read_script(path: Path) -> str:
    return path.read_text()


def _lines(path: Path) -> list[str]:
    return path.read_text().splitlines()


def _rc_subr_line_index(lines: list[str]) -> int:
    """Return the line index of the `. /etc/rc.d/rc.subr` line."""
    for i, line in enumerate(lines):
        if line.strip() == ". /etc/rc.d/rc.subr":
            return i
    raise ValueError("rc.subr source not found")


def _find_var(lines: list[str], var: str) -> str | None:
    """Return the value of a `var=VALUE` assignment, or None."""
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(f"{var}="):
            return stripped.split("=", 1)[1].strip('"').strip("'")
    return None


# ---------------------------------------------------------------------------
# TestChatosAgentScript
# ---------------------------------------------------------------------------


class TestChatosAgentScript:
    def test_shebang(self) -> None:
        lines = _lines(AGENT_SCRIPT)
        assert lines[0] == "#!/bin/ksh"

    def test_daemon_points_to_venv_python(self) -> None:
        val = _find_var(_lines(AGENT_SCRIPT), "daemon")
        assert val is not None
        assert val == "/usr/local/share/chatos/venv/bin/python"

    def test_daemon_flags_contains_serve(self) -> None:
        val = _find_var(_lines(AGENT_SCRIPT), "daemon_flags")
        assert val is not None
        assert "--serve" in val

    def test_daemon_flags_contains_rules(self) -> None:
        val = _find_var(_lines(AGENT_SCRIPT), "daemon_flags")
        assert val is not None
        assert "--rules /etc/chatos/rules.toml" in val

    def test_daemon_flags_contains_log_dir(self) -> None:
        val = _find_var(_lines(AGENT_SCRIPT), "daemon_flags")
        assert val is not None
        assert "--log-dir /var/chatos/logs" in val

    def test_daemon_user_is_chatos(self) -> None:
        val = _find_var(_lines(AGENT_SCRIPT), "daemon_user")
        assert val == "_chatos"

    def test_daemon_execdir_set(self) -> None:
        val = _find_var(_lines(AGENT_SCRIPT), "daemon_execdir")
        assert val == "/usr/local/share/chatos"

    def test_sources_rc_subr(self) -> None:
        text = _read_script(AGENT_SCRIPT)
        assert ". /etc/rc.d/rc.subr" in text

    def test_pexp_after_rc_subr(self) -> None:
        lines = _lines(AGENT_SCRIPT)
        subr_idx = _rc_subr_line_index(lines)
        pexp_indices = [i for i, l in enumerate(lines) if l.strip().startswith("pexp=")]
        assert len(pexp_indices) == 1
        assert pexp_indices[0] > subr_idx

    def test_rc_bg_yes(self) -> None:
        val = _find_var(_lines(AGENT_SCRIPT), "rc_bg")
        assert val == "YES"

    def test_rc_reload_no(self) -> None:
        val = _find_var(_lines(AGENT_SCRIPT), "rc_reload")
        assert val == "NO"

    def test_rc_pre_creates_directories(self) -> None:
        text = _read_script(AGENT_SCRIPT)
        assert "rc_pre()" in text
        assert "/var/chatos/logs" in text
        assert "/var/chatos/run" in text
        assert "/var/chatos/sessions" in text

    def test_last_line_is_rc_cmd(self) -> None:
        lines = _lines(AGENT_SCRIPT)
        non_empty = [l for l in lines if l.strip()]
        assert non_empty[-1].strip() == "rc_cmd $1"

    @pytest.mark.skipif(not shutil.which("ksh"), reason="ksh not available")
    def test_ksh_syntax_valid(self) -> None:
        result = subprocess.run(
            ["ksh", "-n", str(AGENT_SCRIPT)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"ksh syntax error: {result.stderr}"


# ---------------------------------------------------------------------------
# TestChatosUiScript
# ---------------------------------------------------------------------------


class TestChatosUiScript:
    def test_shebang(self) -> None:
        lines = _lines(UI_SCRIPT)
        assert lines[0] == "#!/bin/ksh"

    def test_daemon_points_to_launch_kiosk(self) -> None:
        val = _find_var(_lines(UI_SCRIPT), "daemon")
        assert val is not None
        assert val == "/usr/local/share/chatos/deploy/kiosk/launch-kiosk.sh"

    def test_no_daemon_user(self) -> None:
        """chatos_ui must NOT set daemon_user — runs as root, drops privs internally."""
        val = _find_var(_lines(UI_SCRIPT), "daemon_user")
        assert val is None

    def test_sources_rc_subr(self) -> None:
        text = _read_script(UI_SCRIPT)
        assert ". /etc/rc.d/rc.subr" in text

    def test_pexp_contains_xinit(self) -> None:
        val = _find_var(_lines(UI_SCRIPT), "pexp")
        assert val is not None
        assert "xinit" in val

    def test_pexp_after_rc_subr(self) -> None:
        lines = _lines(UI_SCRIPT)
        subr_idx = _rc_subr_line_index(lines)
        pexp_indices = [i for i, l in enumerate(lines) if l.strip().startswith("pexp=")]
        assert len(pexp_indices) == 1
        assert pexp_indices[0] > subr_idx

    def test_rc_bg_yes(self) -> None:
        val = _find_var(_lines(UI_SCRIPT), "rc_bg")
        assert val == "YES"

    def test_rc_reload_no(self) -> None:
        val = _find_var(_lines(UI_SCRIPT), "rc_reload")
        assert val == "NO"

    def test_rc_pre_checks_port(self) -> None:
        text = _read_script(UI_SCRIPT)
        assert "rc_pre()" in text
        assert "nc -z" in text
        assert "8400" in text

    def test_rc_pre_retries_with_timeout(self) -> None:
        """rc_pre must retry the port check to handle the rc_bg race."""
        text = _read_script(UI_SCRIPT)
        assert "while" in text, "rc_pre should use a retry loop"
        assert "sleep" in text, "rc_pre should sleep between retries"

    def test_rc_pre_logs_failure(self) -> None:
        text = _read_script(UI_SCRIPT)
        assert "logger" in text
        assert "chatos_ui" in text

    def test_rc_post_calls_reset_console(self) -> None:
        text = _read_script(UI_SCRIPT)
        assert "rc_post()" in text
        assert "reset-console.sh" in text

    def test_last_line_is_rc_cmd(self) -> None:
        lines = _lines(UI_SCRIPT)
        non_empty = [l for l in lines if l.strip()]
        assert non_empty[-1].strip() == "rc_cmd $1"

    @pytest.mark.skipif(not shutil.which("ksh"), reason="ksh not available")
    def test_ksh_syntax_valid(self) -> None:
        result = subprocess.run(
            ["ksh", "-n", str(UI_SCRIPT)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"ksh syntax error: {result.stderr}"


# ---------------------------------------------------------------------------
# TestPexpPatterns
# ---------------------------------------------------------------------------


class TestPexpPatterns:
    """Verify that pexp regex patterns match the expected process strings.

    The pexp values in rc.d scripts use ${daemon} which ksh expands at runtime.
    We resolve the variable here by substituting the daemon value from the script.
    """

    def _extract_pexp(self, path: Path) -> str:
        lines = _lines(path)
        pexp_raw = _find_var(lines, "pexp")
        assert pexp_raw is not None
        # Resolve ${daemon} references using the daemon= value from the same script
        daemon_val = _find_var(lines, "daemon")
        if daemon_val and "${daemon}" in pexp_raw:
            pexp_raw = pexp_raw.replace("${daemon}", re.escape(daemon_val))
        return pexp_raw

    def test_agent_pexp_matches_default_command(self) -> None:
        pexp = self._extract_pexp(AGENT_SCRIPT)
        cmd = "/usr/local/share/chatos/venv/bin/python -m src --serve --rules /etc/chatos/rules.toml --log-dir /var/chatos/logs"
        assert re.search(pexp, cmd)

    def test_agent_pexp_matches_with_extra_flags(self) -> None:
        pexp = self._extract_pexp(AGENT_SCRIPT)
        cmd = "/usr/local/share/chatos/venv/bin/python -m src --serve --port 9000 --model opus --rules /etc/chatos/rules.toml"
        assert re.search(pexp, cmd)

    def test_agent_pexp_no_match_unrelated_python(self) -> None:
        pexp = self._extract_pexp(AGENT_SCRIPT)
        cmd = "/usr/bin/python3 -m http.server 8080"
        assert not re.search(pexp, cmd)

    def test_agent_pexp_no_match_without_serve(self) -> None:
        pexp = self._extract_pexp(AGENT_SCRIPT)
        cmd = "/usr/local/share/chatos/venv/bin/python -m src --rules /etc/chatos/rules.toml"
        assert not re.search(pexp, cmd)

    def test_ui_pexp_matches_expected_xinit(self) -> None:
        pexp = self._extract_pexp(UI_SCRIPT)
        cmd = "xinit /usr/local/share/chatos/deploy/kiosk/xinitrc -- :0 vt05"
        assert re.search(pexp, cmd)

    def test_ui_pexp_no_match_unrelated_xinit(self) -> None:
        pexp = self._extract_pexp(UI_SCRIPT)
        cmd = "xinit /home/user/.xinitrc"
        assert not re.search(pexp, cmd)


# ---------------------------------------------------------------------------
# TestScriptPaths
# ---------------------------------------------------------------------------


class TestScriptPaths:
    """Verify that all paths referenced by the scripts exist in the project tree."""

    def test_agent_script_exists(self) -> None:
        assert AGENT_SCRIPT.exists()

    def test_ui_script_exists(self) -> None:
        assert UI_SCRIPT.exists()

    def test_launch_kiosk_exists(self) -> None:
        """The daemon path in chatos_ui must exist in the project."""
        path = PROJECT_ROOT / "deploy" / "kiosk" / "launch-kiosk.sh"
        assert path.exists()

    def test_xinitrc_exists(self) -> None:
        path = PROJECT_ROOT / "deploy" / "kiosk" / "xinitrc"
        assert path.exists()

    def test_reset_console_exists(self) -> None:
        path = PROJECT_ROOT / "deploy" / "kiosk" / "reset-console.sh"
        assert path.exists()

    def test_agent_script_is_executable(self) -> None:
        import os
        assert os.access(AGENT_SCRIPT, os.X_OK)

    def test_ui_script_is_executable(self) -> None:
        import os
        assert os.access(UI_SCRIPT, os.X_OK)


# ---------------------------------------------------------------------------
# TestRcConfExample
# ---------------------------------------------------------------------------


class TestRcConfExample:
    def test_file_exists(self) -> None:
        assert RC_CONF_EXAMPLE.exists()

    def test_pkg_scripts_agent_before_ui(self) -> None:
        text = RC_CONF_EXAMPLE.read_text()
        match = re.search(r'pkg_scripts="([^"]+)"', text)
        assert match is not None
        services = match.group(1).split()
        agent_idx = services.index("chatos_agent")
        ui_idx = services.index("chatos_ui")
        assert agent_idx < ui_idx

    def test_agent_timeout_present(self) -> None:
        text = RC_CONF_EXAMPLE.read_text()
        assert "chatos_agent_timeout=" in text

    def test_ui_timeout_present(self) -> None:
        text = RC_CONF_EXAMPLE.read_text()
        assert "chatos_ui_timeout=" in text

    def test_flag_override_documented(self) -> None:
        """Example should show how to override daemon_flags."""
        text = RC_CONF_EXAMPLE.read_text()
        assert "chatos_agent_flags=" in text
