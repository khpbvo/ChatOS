"""Tests for the ChatOS pledge/unveil sandbox module."""

import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest

from src.sandbox import (
    VALID_PROMISES,
    VALID_UNVEIL_PERMISSIONS,
    PledgeError,
    Sandbox,
    SandboxError,
    UnveilError,
    _IS_OPENBSD,
    _load_libc,
    validate_promises,
    validate_unveil_permissions,
)


# -- TestConstants --


class TestConstants:
    def test_is_openbsd_matches_platform(self) -> None:
        assert _IS_OPENBSD == sys.platform.startswith("openbsd")

    def test_valid_promises_is_frozenset(self) -> None:
        assert isinstance(VALID_PROMISES, frozenset)

    def test_valid_promises_contains_core_promises(self) -> None:
        for p in ("stdio", "rpath", "wpath", "cpath", "inet", "dns", "proc", "exec"):
            assert p in VALID_PROMISES

    def test_valid_unveil_permissions(self) -> None:
        assert VALID_UNVEIL_PERMISSIONS == {"r", "w", "x", "c"}


# -- TestExceptions --


class TestExceptions:
    def test_sandbox_error_is_exception(self) -> None:
        assert issubclass(SandboxError, Exception)

    def test_pledge_error_inherits_sandbox_error(self) -> None:
        assert issubclass(PledgeError, SandboxError)

    def test_unveil_error_inherits_sandbox_error(self) -> None:
        assert issubclass(UnveilError, SandboxError)

    def test_pledge_error_stores_errno(self) -> None:
        err = PledgeError("test", 1)
        assert err.errno_code == 1
        assert "errno 1" in str(err)

    def test_unveil_error_stores_errno(self) -> None:
        err = UnveilError("test", 2)
        assert err.errno_code == 2
        assert "errno 2" in str(err)

    def test_error_message_includes_strerror(self) -> None:
        import os

        err = PledgeError("pledge failed", 1)
        assert os.strerror(1) in str(err)


# -- TestPromiseValidation --


class TestPromiseValidation:
    def test_valid_single_promise(self) -> None:
        validate_promises("stdio")

    def test_valid_multiple_promises(self) -> None:
        validate_promises("stdio", "rpath", "wpath")

    def test_all_36_promises_accepted(self) -> None:
        validate_promises(*VALID_PROMISES)
        assert len(VALID_PROMISES) == 36

    def test_unknown_promise_rejected(self) -> None:
        with pytest.raises(SandboxError, match="Unknown pledge promise.*'bogus'"):
            validate_promises("bogus")

    def test_empty_promises_rejected(self) -> None:
        with pytest.raises(SandboxError, match="At least one promise"):
            validate_promises()

    def test_case_wrong_rejected(self) -> None:
        with pytest.raises(SandboxError, match="Unknown pledge promise.*'STDIO'"):
            validate_promises("STDIO")

    def test_whitespace_padded_rejected(self) -> None:
        with pytest.raises(SandboxError, match="Unknown pledge promise"):
            validate_promises(" stdio ")


# -- TestUnveilPermissionValidation --


class TestUnveilPermissionValidation:
    def test_valid_single_permission(self) -> None:
        validate_unveil_permissions("r")

    def test_valid_multi_permission(self) -> None:
        validate_unveil_permissions("rwxc")

    def test_valid_subset(self) -> None:
        validate_unveil_permissions("rx")

    def test_invalid_char_rejected(self) -> None:
        with pytest.raises(SandboxError, match="Invalid unveil permission character.*'z'"):
            validate_unveil_permissions("rz")

    def test_empty_string_rejected(self) -> None:
        with pytest.raises(SandboxError, match="cannot be empty"):
            validate_unveil_permissions("")


# -- TestSandboxBuilder --


class TestSandboxBuilder:
    def test_initial_state_empty(self) -> None:
        sb = Sandbox()
        assert sb.promises == frozenset()
        assert sb.exec_promises == frozenset()
        assert sb.unveiled_paths == []
        assert sb.is_pledged is False
        assert sb.is_unveil_locked is False

    def test_is_supported_property(self) -> None:
        sb = Sandbox()
        assert sb.is_supported == _IS_OPENBSD

    def test_promise_adds_and_returns_self(self) -> None:
        sb = Sandbox()
        result = sb.promise("stdio", "rpath")
        assert result is sb
        assert sb.promises == frozenset({"stdio", "rpath"})

    def test_exec_promise_adds_and_returns_self(self) -> None:
        sb = Sandbox()
        result = sb.exec_promise("stdio", "exec")
        assert result is sb
        assert sb.exec_promises == frozenset({"stdio", "exec"})

    def test_unveil_adds_and_returns_self(self) -> None:
        sb = Sandbox()
        result = sb.unveil("/tmp", "r")
        assert result is sb
        assert sb.unveiled_paths == [("/tmp", "r")]

    def test_multiple_unveils(self) -> None:
        sb = Sandbox()
        sb.unveil("/tmp", "r").unveil("/var", "rw")
        assert sb.unveiled_paths == [("/tmp", "r"), ("/var", "rw")]

    def test_full_builder_chain(self) -> None:
        sb = (
            Sandbox()
            .promise("stdio", "rpath", "wpath")
            .exec_promise("stdio")
            .unveil("/tmp", "rw")
            .unveil("/var/log", "r")
        )
        assert sb.promises == frozenset({"stdio", "rpath", "wpath"})
        assert sb.exec_promises == frozenset({"stdio"})
        assert len(sb.unveiled_paths) == 2

    def test_promise_accumulates(self) -> None:
        sb = Sandbox()
        sb.promise("stdio")
        sb.promise("rpath")
        assert sb.promises == frozenset({"stdio", "rpath"})

    def test_promise_deduplicates(self) -> None:
        sb = Sandbox()
        sb.promise("stdio", "stdio", "rpath")
        assert sb.promises == frozenset({"stdio", "rpath"})


# -- TestSandboxStateGuards --


class TestSandboxStateGuards:
    def test_promise_after_pledge_raises(self) -> None:
        sb = Sandbox()
        sb.promise("stdio")
        sb._pledged = True  # simulate pledge applied
        with pytest.raises(SandboxError, match="after pledge has been applied"):
            sb.promise("rpath")

    def test_exec_promise_after_pledge_raises(self) -> None:
        sb = Sandbox()
        sb.promise("stdio")
        sb._pledged = True
        with pytest.raises(SandboxError, match="after pledge has been applied"):
            sb.exec_promise("stdio")

    def test_unveil_after_lock_raises(self) -> None:
        sb = Sandbox()
        sb._unveil_locked = True
        with pytest.raises(SandboxError, match="after unveil has been locked"):
            sb.unveil("/tmp", "r")

    def test_double_lock_is_idempotent(self) -> None:
        sb = Sandbox()
        sb._unveil_locked = True
        # Second lock should be a no-op (no error)
        sb.lock_unveil()
        assert sb.is_unveil_locked is True

    def test_pledge_already_applied_raises(self) -> None:
        sb = Sandbox()
        sb.promise("stdio")
        sb._pledged = True
        with pytest.raises(SandboxError, match="already been applied"):
            sb.apply_pledge()

    def test_apply_pledge_with_empty_promises_raises(self) -> None:
        sb = Sandbox()
        with pytest.raises(SandboxError, match="empty promise set"):
            sb.apply_pledge()

    @patch("src.sandbox._raw_pledge", return_value=0)
    @patch("src.sandbox._raw_unveil", return_value=0)
    def test_apply_sets_pledged_and_locked(
        self, mock_unveil: MagicMock, mock_pledge: MagicMock
    ) -> None:
        sb = Sandbox()
        sb.promise("stdio", "rpath").unveil("/tmp", "r")
        sb.apply()
        assert sb.is_pledged is True
        assert sb.is_unveil_locked is True

    @patch("src.sandbox._raw_pledge", return_value=0)
    def test_apply_without_unveils_skips_lock(self, mock_pledge: MagicMock) -> None:
        sb = Sandbox()
        sb.promise("stdio")
        sb.apply()
        assert sb.is_pledged is True
        assert sb.is_unveil_locked is False

    @patch("src.sandbox._raw_pledge", return_value=0)
    def test_apply_pledge_sorts_promises(self, mock_pledge: MagicMock) -> None:
        sb = Sandbox()
        sb.promise("wpath", "stdio", "rpath")
        sb.apply_pledge()
        mock_pledge.assert_called_once_with("rpath stdio wpath", None)

    @patch("src.sandbox._raw_pledge", return_value=0)
    def test_apply_pledge_with_exec_promises(self, mock_pledge: MagicMock) -> None:
        sb = Sandbox()
        sb.promise("stdio").exec_promise("stdio", "exec")
        sb.apply_pledge()
        mock_pledge.assert_called_once_with("stdio", "exec stdio")


# -- TestLibcLoading --


class TestLibcLoading:
    def test_returns_cdll_on_openbsd(self) -> None:
        import ctypes as ct

        import src.sandbox as mod

        old = mod._libc
        mod._libc = None  # reset cache
        try:
            result = _load_libc()
            if _IS_OPENBSD:
                assert result is not None
                assert isinstance(result, ct.CDLL)
            else:
                assert result is None
        finally:
            mod._libc = old

    @pytest.mark.skipif(not _IS_OPENBSD, reason="libc only on OpenBSD")
    def test_libc_has_pledge_and_unveil(self) -> None:
        import src.sandbox as mod

        old = mod._libc
        mod._libc = None
        try:
            libc = _load_libc()
            assert libc is not None
            assert hasattr(libc, "pledge")
            assert hasattr(libc, "unveil")
        finally:
            mod._libc = old

    def test_second_call_returns_cached(self) -> None:
        import src.sandbox as mod

        old = mod._libc
        mod._libc = None
        try:
            first = _load_libc()
            second = _load_libc()
            assert first is second
        finally:
            mod._libc = old


# -- TestRawSyscallErrors --


class TestRawSyscallErrors:
    @patch("src.sandbox._raw_pledge", return_value=-1)
    @patch("src.sandbox.ctypes.get_errno", return_value=1)
    def test_pledge_failure_raises(
        self, mock_errno: MagicMock, mock_pledge: MagicMock
    ) -> None:
        sb = Sandbox()
        sb.promise("stdio")
        with pytest.raises(PledgeError, match="pledge.*failed"):
            sb.apply_pledge()

    @patch("src.sandbox._raw_unveil", return_value=-1)
    @patch("src.sandbox.ctypes.get_errno", return_value=2)
    def test_unveil_failure_raises(
        self, mock_errno: MagicMock, mock_unveil: MagicMock
    ) -> None:
        sb = Sandbox()
        sb.unveil("/tmp", "r")
        with pytest.raises(UnveilError, match="unveil.*failed"):
            sb.apply_unveils()

    @patch("src.sandbox._raw_unveil", return_value=-1)
    @patch("src.sandbox.ctypes.get_errno", return_value=1)
    def test_lock_unveil_failure_raises(
        self, mock_errno: MagicMock, mock_unveil: MagicMock
    ) -> None:
        sb = Sandbox()
        with pytest.raises(UnveilError, match="unveil.*NULL.*failed"):
            sb.lock_unveil()


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

    def test_pledge_stdio_succeeds(self) -> None:
        result = self._run_snippet(
            "from src.sandbox import Sandbox\n"
            "sb = Sandbox().promise('stdio')\n"
            "sb.apply_pledge()\n"
            "print('pledged')\n"
        )
        assert result.returncode == 0
        assert "pledged" in result.stdout

    def test_pledge_invalid_promise_fails_at_validation(self) -> None:
        result = self._run_snippet(
            "from src.sandbox import Sandbox, SandboxError\n"
            "try:\n"
            "    Sandbox().promise('fakepromise')\n"
            "    print('ERROR: no exception')\n"
            "except SandboxError as e:\n"
            "    print(f'caught: {e}')\n"
        )
        assert result.returncode == 0
        assert "caught:" in result.stdout
        assert "fakepromise" in result.stdout

    def test_unveil_and_lock(self) -> None:
        result = self._run_snippet(
            "import os\n"
            "from src.sandbox import Sandbox\n"
            "sb = Sandbox()\n"
            "sb.promise('stdio', 'rpath', 'unveil')\n"
            "sb.unveil('/tmp', 'r')\n"
            "sb.apply_unveils()\n"
            "sb.lock_unveil()\n"
            "print('locked')\n"
            "# Verify /tmp is accessible\n"
            "os.listdir('/tmp')\n"
            "print('access ok')\n"
        )
        assert result.returncode == 0
        assert "locked" in result.stdout
        assert "access ok" in result.stdout

    def test_unveil_lock_prevents_additions(self) -> None:
        result = self._run_snippet(
            "from src.sandbox import Sandbox, SandboxError\n"
            "sb = Sandbox()\n"
            "sb.promise('stdio', 'rpath', 'unveil')\n"
            "sb.unveil('/tmp', 'r')\n"
            "sb.apply_unveils()\n"
            "sb.lock_unveil()\n"
            "try:\n"
            "    sb.unveil('/var', 'r')\n"
            "    print('ERROR: no exception')\n"
            "except SandboxError as e:\n"
            "    print(f'caught: {e}')\n"
        )
        assert result.returncode == 0
        assert "caught:" in result.stdout
        assert "locked" in result.stdout

    def test_full_sandbox_apply(self) -> None:
        result = self._run_snippet(
            "from src.sandbox import Sandbox\n"
            "sb = (\n"
            "    Sandbox()\n"
            "    .promise('stdio', 'rpath', 'unveil')\n"
            "    .unveil('/tmp', 'r')\n"
            ")\n"
            "sb.apply()\n"
            "print(f'pledged={sb.is_pledged}')\n"
            "print(f'locked={sb.is_unveil_locked}')\n"
        )
        assert result.returncode == 0
        assert "pledged=True" in result.stdout
        assert "locked=True" in result.stdout
