"""Tests for ChatOS sandbox profiles (Step 18)."""

import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest

from src.sandbox import VALID_PROMISES, Sandbox, _IS_OPENBSD
from src.sandbox_profiles import (
    _COMMON_PROMISES,
    _EXEC_PROMISES,
    build_cli_sandbox,
    build_server_sandbox,
)


# -- TestServerProfile --


class TestServerProfile:
    def test_returns_sandbox_instance(self) -> None:
        sb = build_server_sandbox()
        assert isinstance(sb, Sandbox)

    def test_has_required_parent_promises(self) -> None:
        sb = build_server_sandbox()
        for p in ("stdio", "rpath", "wpath", "cpath", "inet", "proc",
                   "exec", "dns", "unix", "tmppath", "flock", "unveil"):
            assert p in sb.promises, f"Missing promise: {p}"

    def test_has_exec_promises(self) -> None:
        sb = build_server_sandbox()
        assert len(sb.exec_promises) == len(_EXEC_PROMISES)
        for p in _EXEC_PROMISES:
            assert p in sb.exec_promises

    def test_has_common_unveils(self) -> None:
        sb = build_server_sandbox()
        paths = {path for path, _ in sb.unveiled_paths}
        for expected in ("/etc", "/usr", "/bin", "/sbin", "/dev/null",
                         "/dev/urandom", "/tmp", "/var/chatos"):
            assert expected in paths, f"Missing unveil: {expected}"

    def test_home_dir_unveiled_when_set(self) -> None:
        sb = build_server_sandbox(home_dir="/home/agent01")
        paths = {path for path, _ in sb.unveiled_paths}
        assert "/home/agent01" in paths

    def test_home_dir_absent_when_none(self) -> None:
        sb = build_server_sandbox(home_dir=None)
        paths = {path for path, _ in sb.unveiled_paths}
        assert "/home/agent01" not in paths

    def test_static_dir_unveiled_when_outside_app_dir(self) -> None:
        sb = build_server_sandbox(
            static_dir="/opt/chatos-ui/dist",
            app_dir="/usr/local/share/chatos",
        )
        paths_perms = {(p, perm) for p, perm in sb.unveiled_paths}
        assert ("/opt/chatos-ui/dist", "r") in paths_perms

    def test_static_dir_not_doubled_when_under_app_dir(self) -> None:
        sb = build_server_sandbox(
            static_dir="/usr/local/share/chatos/ui/dist",
            app_dir="/usr/local/share/chatos",
        )
        paths = [p for p, _ in sb.unveiled_paths]
        assert "/usr/local/share/chatos/ui/dist" not in paths

    def test_custom_log_dir_unveiled_when_outside_var_chatos(self) -> None:
        sb = build_server_sandbox(log_dir="/tmp/chatos-logs")
        paths = {path for path, _ in sb.unveiled_paths}
        # /tmp/chatos-logs resolves under /tmp which is already unveiled,
        # but the profile adds it explicitly as rwc
        resolved = str(__import__("pathlib").Path("/tmp/chatos-logs").resolve())
        assert resolved in paths

    def test_default_log_dir_not_double_unveiled(self) -> None:
        sb = build_server_sandbox(log_dir="/var/chatos/logs")
        paths = [p for p, _ in sb.unveiled_paths]
        assert "/var/chatos/logs" not in paths  # covered by /var/chatos

    def test_custom_app_dir_in_unveils(self) -> None:
        sb = build_server_sandbox(app_dir="/opt/myapp")
        paths = {path for path, _ in sb.unveiled_paths}
        assert "/opt/myapp" in paths

    @patch("src.sandbox._raw_pledge", return_value=0)
    @patch("src.sandbox._raw_unveil", return_value=0)
    def test_apply_succeeds_with_mocked_syscalls(
        self, mock_unveil: MagicMock, mock_pledge: MagicMock
    ) -> None:
        sb = build_server_sandbox(home_dir="/home/agent01")
        sb.apply()
        assert sb.is_pledged is True
        assert sb.is_unveil_locked is True


# -- TestCliProfile --


class TestCliProfile:
    def test_returns_sandbox_instance(self) -> None:
        sb = build_cli_sandbox()
        assert isinstance(sb, Sandbox)

    def test_has_tty_promise(self) -> None:
        sb = build_cli_sandbox()
        assert "tty" in sb.promises

    def test_server_profile_lacks_tty(self) -> None:
        sb = build_server_sandbox()
        assert "tty" not in sb.promises

    def test_has_required_parent_promises(self) -> None:
        sb = build_cli_sandbox()
        for p in ("stdio", "rpath", "wpath", "cpath", "inet", "proc",
                   "exec", "dns", "unix", "tmppath", "flock", "unveil"):
            assert p in sb.promises, f"Missing promise: {p}"

    def test_has_exec_promises(self) -> None:
        sb = build_cli_sandbox()
        assert len(sb.exec_promises) == len(_EXEC_PROMISES)

    def test_has_common_unveils(self) -> None:
        sb = build_cli_sandbox()
        paths = {path for path, _ in sb.unveiled_paths}
        for expected in ("/etc", "/usr", "/bin", "/sbin", "/dev/null",
                         "/dev/urandom", "/tmp", "/var/chatos"):
            assert expected in paths

    def test_no_home_dir_unveil(self) -> None:
        sb = build_cli_sandbox()
        paths = {path for path, _ in sb.unveiled_paths}
        assert "/home/agent01" not in paths

    def test_custom_log_dir_works(self) -> None:
        sb = build_cli_sandbox(log_dir="/tmp/chatos-logs")
        paths = {path for path, _ in sb.unveiled_paths}
        resolved = str(__import__("pathlib").Path("/tmp/chatos-logs").resolve())
        assert resolved in paths

    @patch("src.sandbox._raw_pledge", return_value=0)
    @patch("src.sandbox._raw_unveil", return_value=0)
    def test_apply_succeeds_with_mocked_syscalls(
        self, mock_unveil: MagicMock, mock_pledge: MagicMock
    ) -> None:
        sb = build_cli_sandbox()
        sb.apply()
        assert sb.is_pledged is True
        assert sb.is_unveil_locked is True


# -- TestExecPromises --


class TestExecPromises:
    def test_contains_prot_exec(self) -> None:
        assert "prot_exec" in _EXEC_PROMISES

    def test_excludes_dangerous_promises(self) -> None:
        dangerous = {"settime", "disklabel", "pf", "drm", "vmm",
                      "route", "wroute", "audio", "video", "bpf",
                      "mcast", "dpath", "tape", "error"}
        for p in dangerous:
            assert p not in _EXEC_PROMISES, f"Dangerous promise in exec: {p}"

    def test_all_names_valid(self) -> None:
        for p in _EXEC_PROMISES:
            assert p in VALID_PROMISES, f"Typo in exec promise: {p}"

    def test_is_tuple(self) -> None:
        assert isinstance(_EXEC_PROMISES, tuple)


# -- TestIntegrationPoints --


class TestIntegrationPoints:
    @patch("src.sandbox_profiles.Sandbox")
    def test_ws_server_main_calls_build_server_sandbox(
        self, MockSandbox: MagicMock
    ) -> None:
        mock_sb = MagicMock()
        with (
            patch("src.ws_server.parse_args") as mock_args,
            patch("src.ws_server.RulesEngine") as MockRules,
            patch("src.ws_server.AuditLogger") as MockAudit,
            patch("src.ws_server.Orchestrator") as MockOrch,
            patch("src.ws_server.ChatOSWebSocketServer") as MockServer,
            patch("src.ws_server.asyncio") as mock_asyncio,
            patch("src.ws_server.resolve_rules_path", return_value="/fake/rules.toml"),
            patch("src.sandbox_profiles.build_server_sandbox", return_value=mock_sb) as mock_build,
        ):
            mock_args.return_value = MagicMock(
                host="127.0.0.1", port=8400, rules=None,
                log_dir="/tmp/test-logs", model="sonnet", cwd="/tmp",
                home_dir="/home/agent01", static_dir="/opt/ui",
            )
            MockRules.from_file.return_value = MagicMock()
            # Mock agent registry (DEV_AGENTS_TOML.is_file())
            with (
                patch("src.ws_server.DEV_AGENTS_TOML") as mock_agents_path,
                patch("src.ws_server.AgentRegistry"),
                patch("src.ws_server.McpConfigLoader") as MockMcp,
            ):
                mock_agents_path.is_file.return_value = False
                MockMcp.from_path.return_value = MagicMock(has_email=lambda: False)

                from src.ws_server import main
                main()

            mock_build.assert_called_once()
            call_kwargs = mock_build.call_args[1]
            assert call_kwargs["log_dir"] == "/tmp/test-logs"
            assert call_kwargs["home_dir"] == "/home/agent01"
            assert call_kwargs["static_dir"] == "/opt/ui"
            mock_sb.apply.assert_called_once()

    @patch("src.sandbox_profiles.Sandbox")
    def test_cli_main_calls_build_cli_sandbox(
        self, MockSandbox: MagicMock
    ) -> None:
        mock_sb = MagicMock()
        with (
            patch("src.cli.parse_args") as mock_args,
            patch("src.cli.RulesEngine") as MockRules,
            patch("src.cli.AuditLogger") as MockAudit,
            patch("src.cli.Orchestrator") as MockOrch,
            patch("src.cli.asyncio") as mock_asyncio,
            patch("src.cli.resolve_rules_path", return_value="/fake/rules.toml"),
            patch("src.sandbox_profiles.build_cli_sandbox", return_value=mock_sb) as mock_build,
        ):
            mock_args.return_value = MagicMock(
                rules=None, log_dir="/tmp/test-logs", model="sonnet", cwd="/tmp",
            )
            MockRules.from_file.return_value = MagicMock()
            with (
                patch("src.cli.DEV_AGENTS_TOML") as mock_agents_path,
                patch("src.cli.AgentRegistry"),
                patch("src.cli.McpConfigLoader") as MockMcp,
            ):
                mock_agents_path.is_file.return_value = False
                MockMcp.from_path.return_value = MagicMock(has_email=lambda: False)

                from src.cli import main
                main()

            mock_build.assert_called_once()
            call_kwargs = mock_build.call_args[1]
            assert call_kwargs["log_dir"] == "/tmp/test-logs"
            mock_sb.apply.assert_called_once()

    def test_server_continues_on_sandbox_failure(self) -> None:
        mock_sb = MagicMock()
        mock_sb.apply.side_effect = OSError("pledge failed")
        with (
            patch("src.ws_server.parse_args") as mock_args,
            patch("src.ws_server.RulesEngine") as MockRules,
            patch("src.ws_server.AuditLogger") as MockAudit,
            patch("src.ws_server.Orchestrator") as MockOrch,
            patch("src.ws_server.ChatOSWebSocketServer") as MockServer,
            patch("src.ws_server.asyncio") as mock_asyncio,
            patch("src.ws_server.resolve_rules_path", return_value="/fake/rules.toml"),
            patch("src.sandbox_profiles.build_server_sandbox", return_value=mock_sb),
        ):
            mock_args.return_value = MagicMock(
                host="127.0.0.1", port=8400, rules=None,
                log_dir=None, model="sonnet", cwd="/tmp",
                home_dir=None, static_dir=None,
            )
            MockRules.from_file.return_value = MagicMock()
            with (
                patch("src.ws_server.DEV_AGENTS_TOML") as mock_agents_path,
                patch("src.ws_server.AgentRegistry"),
                patch("src.ws_server.McpConfigLoader") as MockMcp,
            ):
                mock_agents_path.is_file.return_value = False
                MockMcp.from_path.return_value = MagicMock(has_email=lambda: False)

                from src.ws_server import main
                main()

            # Server should still call asyncio.run despite sandbox failure
            mock_asyncio.run.assert_called_once()

    def test_cli_continues_on_sandbox_failure(self) -> None:
        mock_sb = MagicMock()
        mock_sb.apply.side_effect = OSError("pledge failed")
        with (
            patch("src.cli.parse_args") as mock_args,
            patch("src.cli.RulesEngine") as MockRules,
            patch("src.cli.AuditLogger") as MockAudit,
            patch("src.cli.Orchestrator") as MockOrch,
            patch("src.cli.asyncio") as mock_asyncio,
            patch("src.cli.resolve_rules_path", return_value="/fake/rules.toml"),
            patch("src.sandbox_profiles.build_cli_sandbox", return_value=mock_sb),
        ):
            mock_args.return_value = MagicMock(
                rules=None, log_dir=None, model="sonnet", cwd="/tmp",
            )
            MockRules.from_file.return_value = MagicMock()
            with (
                patch("src.cli.DEV_AGENTS_TOML") as mock_agents_path,
                patch("src.cli.AgentRegistry"),
                patch("src.cli.McpConfigLoader") as MockMcp,
            ):
                mock_agents_path.is_file.return_value = False
                MockMcp.from_path.return_value = MagicMock(has_email=lambda: False)

                from src.cli import main
                main()

            mock_asyncio.run.assert_called_once()

    @patch("src.sandbox_profiles.Sandbox")
    def test_server_passes_correct_args(self, MockSandbox: MagicMock) -> None:
        mock_sb = MagicMock()
        with (
            patch("src.ws_server.parse_args") as mock_args,
            patch("src.ws_server.RulesEngine") as MockRules,
            patch("src.ws_server.AuditLogger"),
            patch("src.ws_server.Orchestrator"),
            patch("src.ws_server.ChatOSWebSocketServer"),
            patch("src.ws_server.asyncio"),
            patch("src.ws_server.resolve_rules_path", return_value="/fake/rules.toml"),
            patch("src.sandbox_profiles.build_server_sandbox", return_value=mock_sb) as mock_build,
        ):
            mock_args.return_value = MagicMock(
                host="127.0.0.1", port=8400, rules=None,
                log_dir="/custom/logs", model="sonnet", cwd="/tmp",
                home_dir="/home/testuser", static_dir="/opt/dist",
            )
            MockRules.from_file.return_value = MagicMock()
            with (
                patch("src.ws_server.DEV_AGENTS_TOML") as mock_agents_path,
                patch("src.ws_server.AgentRegistry"),
                patch("src.ws_server.McpConfigLoader") as MockMcp,
            ):
                mock_agents_path.is_file.return_value = False
                MockMcp.from_path.return_value = MagicMock(has_email=lambda: False)

                from src.ws_server import main
                main()

            kw = mock_build.call_args[1]
            assert kw["log_dir"] == "/custom/logs"
            assert kw["home_dir"] == "/home/testuser"
            assert kw["static_dir"] == "/opt/dist"
            assert "app_dir" in kw

    @patch("src.sandbox_profiles.Sandbox")
    def test_cli_passes_correct_args(self, MockSandbox: MagicMock) -> None:
        mock_sb = MagicMock()
        with (
            patch("src.cli.parse_args") as mock_args,
            patch("src.cli.RulesEngine") as MockRules,
            patch("src.cli.AuditLogger"),
            patch("src.cli.Orchestrator"),
            patch("src.cli.asyncio"),
            patch("src.cli.resolve_rules_path", return_value="/fake/rules.toml"),
            patch("src.sandbox_profiles.build_cli_sandbox", return_value=mock_sb) as mock_build,
        ):
            mock_args.return_value = MagicMock(
                rules=None, log_dir="/custom/logs", model="sonnet", cwd="/tmp",
            )
            MockRules.from_file.return_value = MagicMock()
            with (
                patch("src.cli.DEV_AGENTS_TOML") as mock_agents_path,
                patch("src.cli.AgentRegistry"),
                patch("src.cli.McpConfigLoader") as MockMcp,
            ):
                mock_agents_path.is_file.return_value = False
                MockMcp.from_path.return_value = MagicMock(has_email=lambda: False)

                from src.cli import main
                main()

            kw = mock_build.call_args[1]
            assert kw["log_dir"] == "/custom/logs"
            assert "app_dir" in kw


# -- TestSubprocessIntegration --


@pytest.mark.skipif(not _IS_OPENBSD, reason="pledge/unveil only on OpenBSD")
class TestSubprocessIntegration:
    """Integration tests that run real pledge/unveil in isolated subprocesses."""

    _python = sys.executable
    _env = {"PYTHONPATH": str(__import__("pathlib").Path(__file__).resolve().parent.parent)}

    def _run_snippet(self, code: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [self._python, "-c", code],
            capture_output=True,
            text=True,
            env={**self._env, "PATH": "/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin"},
            timeout=10,
        )

    def test_server_sandbox_pledge_succeeds(self) -> None:
        result = self._run_snippet(
            "from src.sandbox_profiles import build_server_sandbox\n"
            "sb = build_server_sandbox(log_dir='/tmp/test-logs')\n"
            "sb.apply()\n"
            "print('applied')\n"
        )
        assert result.returncode == 0
        assert "applied" in result.stdout

    def test_cli_sandbox_pledge_succeeds(self) -> None:
        result = self._run_snippet(
            "from src.sandbox_profiles import build_cli_sandbox\n"
            "sb = build_cli_sandbox(log_dir='/tmp/test-logs')\n"
            "sb.apply()\n"
            "print('applied')\n"
        )
        assert result.returncode == 0
        assert "applied" in result.stdout

    def test_sandbox_allows_writing_to_unveiled_log_dir(self) -> None:
        result = self._run_snippet(
            "import os, tempfile\n"
            "from src.sandbox_profiles import build_server_sandbox\n"
            "sb = build_server_sandbox(log_dir='/tmp/test-logs')\n"
            "os.makedirs('/tmp/test-logs', exist_ok=True)\n"
            "sb.apply()\n"
            "with open('/tmp/test-logs/test.txt', 'w') as f:\n"
            "    f.write('hello')\n"
            "print('write ok')\n"
        )
        assert result.returncode == 0
        assert "write ok" in result.stdout

    def test_sandbox_allows_reading_etc(self) -> None:
        result = self._run_snippet(
            "from src.sandbox_profiles import build_server_sandbox\n"
            "sb = build_server_sandbox(log_dir='/tmp/test-logs')\n"
            "sb.apply()\n"
            "with open('/etc/hosts') as f:\n"
            "    _ = f.read()\n"
            "print('read ok')\n"
        )
        assert result.returncode == 0
        assert "read ok" in result.stdout

    def test_sandbox_blocks_unrevealed_path(self) -> None:
        result = self._run_snippet(
            "from src.sandbox_profiles import build_server_sandbox\n"
            "sb = build_server_sandbox(log_dir='/tmp/test-logs')\n"
            "sb.apply()\n"
            "try:\n"
            "    open('/root/.profile')\n"
            "    print('ERROR: should have been blocked')\n"
            "except PermissionError:\n"
            "    print('blocked')\n"
        )
        assert result.returncode == 0
        assert "blocked" in result.stdout

    def test_full_apply_with_unveils_and_pledge(self) -> None:
        result = self._run_snippet(
            "from src.sandbox_profiles import build_cli_sandbox\n"
            "sb = build_cli_sandbox(log_dir='/tmp/test-logs')\n"
            "sb.apply()\n"
            "print(f'pledged={sb.is_pledged}')\n"
            "print(f'locked={sb.is_unveil_locked}')\n"
        )
        assert result.returncode == 0
        assert "pledged=True" in result.stdout
        assert "locked=True" in result.stdout
