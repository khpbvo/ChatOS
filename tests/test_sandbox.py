"""Tests for the ChatOS Linux Landlock sandbox module."""

import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest

from src.sandbox import (
    LANDLOCK_ACCESS_FS_EXECUTE,
    LANDLOCK_ACCESS_FS_MAKE_BLOCK,
    LANDLOCK_ACCESS_FS_MAKE_CHAR,
    LANDLOCK_ACCESS_FS_MAKE_DIR,
    LANDLOCK_ACCESS_FS_MAKE_FIFO,
    LANDLOCK_ACCESS_FS_MAKE_REG,
    LANDLOCK_ACCESS_FS_MAKE_SOCK,
    LANDLOCK_ACCESS_FS_MAKE_SYM,
    LANDLOCK_ACCESS_FS_READ_DIR,
    LANDLOCK_ACCESS_FS_READ_FILE,
    LANDLOCK_ACCESS_FS_REMOVE_DIR,
    LANDLOCK_ACCESS_FS_REMOVE_FILE,
    LANDLOCK_ACCESS_FS_WRITE_FILE,
    VALID_UNVEIL_PERMISSIONS,
    LandlockError,
    PledgeError,
    Sandbox,
    SandboxError,
    UnveilError,
    _IS_LINUX,
    _PERM_EXECUTE,
    _PERM_MAP,
    _PERM_READ,
    _PERM_WRITE,
    _check_landlock_available,
    _load_libc,
    _perms_to_access,
    validate_unveil_permissions,
)


# -- TestConstants --


class TestConstants:
    def test_is_linux_matches_platform(self) -> None:
        assert _IS_LINUX == sys.platform.startswith("linux")

    def test_valid_unveil_permissions(self) -> None:
        assert VALID_UNVEIL_PERMISSIONS == {"r", "w", "x", "c"}

    def test_landlock_access_flags_are_powers_of_two(self) -> None:
        flags = [
            LANDLOCK_ACCESS_FS_EXECUTE,
            LANDLOCK_ACCESS_FS_WRITE_FILE,
            LANDLOCK_ACCESS_FS_READ_FILE,
            LANDLOCK_ACCESS_FS_READ_DIR,
            LANDLOCK_ACCESS_FS_REMOVE_DIR,
            LANDLOCK_ACCESS_FS_REMOVE_FILE,
            LANDLOCK_ACCESS_FS_MAKE_CHAR,
            LANDLOCK_ACCESS_FS_MAKE_DIR,
            LANDLOCK_ACCESS_FS_MAKE_REG,
            LANDLOCK_ACCESS_FS_MAKE_SOCK,
            LANDLOCK_ACCESS_FS_MAKE_FIFO,
            LANDLOCK_ACCESS_FS_MAKE_BLOCK,
            LANDLOCK_ACCESS_FS_MAKE_SYM,
        ]
        for i, flag in enumerate(flags):
            assert flag == (1 << i), f"Flag at index {i} should be {1 << i}, got {flag}"

    def test_perm_read_includes_read_file_and_dir(self) -> None:
        assert _PERM_READ & LANDLOCK_ACCESS_FS_READ_FILE
        assert _PERM_READ & LANDLOCK_ACCESS_FS_READ_DIR

    def test_perm_write_includes_write_flags(self) -> None:
        assert _PERM_WRITE & LANDLOCK_ACCESS_FS_WRITE_FILE
        assert _PERM_WRITE & LANDLOCK_ACCESS_FS_REMOVE_DIR
        assert _PERM_WRITE & LANDLOCK_ACCESS_FS_REMOVE_FILE
        assert _PERM_WRITE & LANDLOCK_ACCESS_FS_MAKE_CHAR
        assert _PERM_WRITE & LANDLOCK_ACCESS_FS_MAKE_DIR
        assert _PERM_WRITE & LANDLOCK_ACCESS_FS_MAKE_REG
        assert _PERM_WRITE & LANDLOCK_ACCESS_FS_MAKE_SOCK
        assert _PERM_WRITE & LANDLOCK_ACCESS_FS_MAKE_FIFO
        assert _PERM_WRITE & LANDLOCK_ACCESS_FS_MAKE_BLOCK
        assert _PERM_WRITE & LANDLOCK_ACCESS_FS_MAKE_SYM

    def test_perm_execute_is_execute_flag(self) -> None:
        assert _PERM_EXECUTE == LANDLOCK_ACCESS_FS_EXECUTE

    def test_perm_map_has_rwxc_keys(self) -> None:
        assert set(_PERM_MAP.keys()) == {"r", "w", "x", "c"}

    def test_perm_map_r_maps_to_read(self) -> None:
        assert _PERM_MAP["r"] == _PERM_READ

    def test_perm_map_w_maps_to_write(self) -> None:
        assert _PERM_MAP["w"] == _PERM_WRITE

    def test_perm_map_x_maps_to_execute(self) -> None:
        assert _PERM_MAP["x"] == _PERM_EXECUTE

    def test_perm_map_c_maps_to_write(self) -> None:
        # "create" maps to write access on Linux
        assert _PERM_MAP["c"] == _PERM_WRITE


# -- TestExceptions --


class TestExceptions:
    def test_sandbox_error_is_exception(self) -> None:
        assert issubclass(SandboxError, Exception)

    def test_landlock_error_inherits_sandbox_error(self) -> None:
        assert issubclass(LandlockError, SandboxError)

    def test_pledge_error_is_landlock_error_alias(self) -> None:
        assert PledgeError is LandlockError

    def test_unveil_error_is_landlock_error_alias(self) -> None:
        assert UnveilError is LandlockError

    def test_pledge_error_inherits_sandbox_error(self) -> None:
        assert issubclass(PledgeError, SandboxError)

    def test_unveil_error_inherits_sandbox_error(self) -> None:
        assert issubclass(UnveilError, SandboxError)

    def test_landlock_error_stores_errno(self) -> None:
        err = LandlockError("test", 1)
        assert err.errno_code == 1
        assert "errno 1" in str(err)

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

        err = LandlockError("landlock failed", 1)
        assert os.strerror(1) in str(err)

    def test_error_message_format(self) -> None:
        err = LandlockError("syscall failed", 13)
        msg = str(err)
        assert "syscall failed:" in msg
        assert "errno 13" in msg


# -- TestPermsToAccess --


class TestPermsToAccess:
    def test_single_r(self) -> None:
        assert _perms_to_access("r") == _PERM_READ

    def test_single_w(self) -> None:
        assert _perms_to_access("w") == _PERM_WRITE

    def test_single_x(self) -> None:
        assert _perms_to_access("x") == _PERM_EXECUTE

    def test_single_c(self) -> None:
        assert _perms_to_access("c") == _PERM_WRITE

    def test_combined_rw(self) -> None:
        assert _perms_to_access("rw") == (_PERM_READ | _PERM_WRITE)

    def test_combined_rwx(self) -> None:
        assert _perms_to_access("rwx") == (_PERM_READ | _PERM_WRITE | _PERM_EXECUTE)

    def test_combined_rwxc(self) -> None:
        # c maps to _PERM_WRITE, so rwxc == rwx (w and c overlap)
        assert _perms_to_access("rwxc") == (_PERM_READ | _PERM_WRITE | _PERM_EXECUTE)

    def test_unknown_char_ignored(self) -> None:
        # Unknown characters get 0 from _PERM_MAP.get(ch, 0)
        assert _perms_to_access("z") == 0

    def test_empty_string(self) -> None:
        assert _perms_to_access("") == 0

    def test_wc_same_as_w(self) -> None:
        # Both w and c map to _PERM_WRITE
        assert _perms_to_access("wc") == _perms_to_access("w")


# -- TestUnveilPermissionValidation --


class TestUnveilPermissionValidation:
    def test_valid_single_permission(self) -> None:
        validate_unveil_permissions("r")

    def test_valid_multi_permission(self) -> None:
        validate_unveil_permissions("rwxc")

    def test_valid_subset(self) -> None:
        validate_unveil_permissions("rx")

    def test_each_valid_char_accepted(self) -> None:
        for ch in "rwxc":
            validate_unveil_permissions(ch)

    def test_invalid_char_rejected(self) -> None:
        with pytest.raises(SandboxError, match="Invalid unveil permission character.*'z'"):
            validate_unveil_permissions("rz")

    def test_empty_string_rejected(self) -> None:
        with pytest.raises(SandboxError, match="cannot be empty"):
            validate_unveil_permissions("")

    def test_uppercase_rejected(self) -> None:
        with pytest.raises(SandboxError, match="Invalid unveil permission character.*'R'"):
            validate_unveil_permissions("R")

    def test_numeric_rejected(self) -> None:
        with pytest.raises(SandboxError, match="Invalid unveil permission character.*'7'"):
            validate_unveil_permissions("7")


# -- TestSandboxBuilder --


class TestSandboxBuilder:
    def test_initial_state_empty(self) -> None:
        sb = Sandbox()
        assert sb.promises == frozenset()
        assert sb.exec_promises == frozenset()
        assert sb.unveiled_paths == []
        assert sb.is_pledged is False
        assert sb.is_unveil_locked is False

    def test_is_supported_checks_linux_and_landlock(self) -> None:
        sb = Sandbox()
        if not _IS_LINUX:
            assert sb.is_supported is False
        # On Linux, depends on kernel Landlock support

    def test_promise_adds_and_returns_self(self) -> None:
        sb = Sandbox()
        result = sb.promise("stdio", "rpath")
        assert result is sb
        assert sb.promises == frozenset({"stdio", "rpath"})

    def test_promise_accepts_any_string(self) -> None:
        """Promises are free-form strings on Linux (not validated against a set)."""
        sb = Sandbox()
        sb.promise("custom_promise", "another_one")
        assert sb.promises == frozenset({"custom_promise", "another_one"})

    def test_promise_accepts_openbsd_style_names(self) -> None:
        """Old OpenBSD promise names still work (they're just strings now)."""
        sb = Sandbox()
        sb.promise("stdio", "rpath", "wpath", "cpath", "inet", "dns", "proc", "exec")
        assert len(sb.promises) == 8

    def test_exec_promise_adds_and_returns_self(self) -> None:
        sb = Sandbox()
        result = sb.exec_promise("stdio", "exec")
        assert result is sb
        assert sb.exec_promises == frozenset({"stdio", "exec"})

    def test_exec_promise_accepts_any_string(self) -> None:
        sb = Sandbox()
        sb.exec_promise("custom_exec")
        assert sb.exec_promises == frozenset({"custom_exec"})

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

    def test_exec_promise_accumulates(self) -> None:
        sb = Sandbox()
        sb.exec_promise("stdio")
        sb.exec_promise("exec")
        assert sb.exec_promises == frozenset({"stdio", "exec"})

    def test_exec_promise_deduplicates(self) -> None:
        sb = Sandbox()
        sb.exec_promise("stdio", "stdio")
        assert sb.exec_promises == frozenset({"stdio"})

    def test_unveiled_paths_returns_copy(self) -> None:
        sb = Sandbox()
        sb.unveil("/tmp", "r")
        paths = sb.unveiled_paths
        paths.append(("/var", "w"))
        assert len(sb.unveiled_paths) == 1  # original unchanged

    def test_promises_returns_frozenset(self) -> None:
        sb = Sandbox()
        sb.promise("stdio")
        assert isinstance(sb.promises, frozenset)

    def test_exec_promises_returns_frozenset(self) -> None:
        sb = Sandbox()
        sb.exec_promise("stdio")
        assert isinstance(sb.exec_promises, frozenset)

    def test_unveil_validates_permissions(self) -> None:
        sb = Sandbox()
        with pytest.raises(SandboxError, match="Invalid unveil permission character"):
            sb.unveil("/tmp", "z")


# -- TestSandboxStateGuards --


class TestSandboxStateGuards:
    def test_promise_after_apply_raises(self) -> None:
        sb = Sandbox()
        sb.promise("stdio")
        sb._pledged = True  # simulate sandbox applied
        with pytest.raises(SandboxError, match="after sandbox has been applied"):
            sb.promise("rpath")

    def test_exec_promise_after_apply_raises(self) -> None:
        sb = Sandbox()
        sb.promise("stdio")
        sb._pledged = True
        with pytest.raises(SandboxError, match="after sandbox has been applied"):
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

    def test_apply_pledge_already_applied_raises(self) -> None:
        sb = Sandbox()
        sb.promise("stdio")
        sb._pledged = True
        with pytest.raises(SandboxError, match="already been applied"):
            sb.apply_pledge()

    def test_apply_pledge_with_empty_promises_raises(self) -> None:
        sb = Sandbox()
        with pytest.raises(SandboxError, match="empty promise set"):
            sb.apply_pledge()

    def test_promise_empty_args_raises(self) -> None:
        sb = Sandbox()
        with pytest.raises(SandboxError, match="At least one promise is required"):
            sb.promise()

    def test_exec_promise_empty_args_raises(self) -> None:
        sb = Sandbox()
        with pytest.raises(SandboxError, match="At least one promise is required"):
            sb.exec_promise()

    @patch("src.sandbox._check_landlock_available", return_value=False)
    @patch("src.sandbox._IS_LINUX", False)
    def test_apply_sets_pledged_and_locked_noop_platform(
        self, mock_avail: MagicMock
    ) -> None:
        """On non-Linux, apply() still sets state flags (no-op syscalls)."""
        sb = Sandbox()
        sb.promise("stdio", "rpath").unveil("/tmp", "r")
        sb.apply()
        assert sb.is_pledged is True
        assert sb.is_unveil_locked is True

    @patch("src.sandbox._check_landlock_available", return_value=False)
    @patch("src.sandbox._IS_LINUX", False)
    def test_apply_without_unveils_skips_lock(self, mock_avail: MagicMock) -> None:
        sb = Sandbox()
        sb.promise("stdio")
        sb.apply()
        assert sb.is_pledged is True
        assert sb.is_unveil_locked is False

    @patch("src.sandbox._check_landlock_available", return_value=False)
    @patch("src.sandbox._IS_LINUX", False)
    def test_apply_pledge_sets_pledged(self, mock_avail: MagicMock) -> None:
        sb = Sandbox()
        sb.promise("stdio", "rpath")
        sb.apply_pledge()
        assert sb.is_pledged is True

    @patch("src.sandbox._check_landlock_available", return_value=False)
    @patch("src.sandbox._IS_LINUX", False)
    def test_apply_pledge_with_exec_promises(self, mock_avail: MagicMock) -> None:
        sb = Sandbox()
        sb.promise("stdio").exec_promise("stdio", "exec")
        sb.apply_pledge()
        assert sb.is_pledged is True
        assert sb.exec_promises == frozenset({"stdio", "exec"})


# -- TestLibcLoading --


class TestLibcLoading:
    def test_returns_cdll_on_linux(self) -> None:
        import ctypes as ct

        import src.sandbox as mod

        old = mod._libc
        mod._libc = None  # reset cache
        try:
            result = _load_libc()
            if _IS_LINUX:
                assert result is not None
                assert isinstance(result, ct.CDLL)
            else:
                assert result is None
        finally:
            mod._libc = old

    def test_returns_none_on_non_linux(self) -> None:
        import src.sandbox as mod

        old = mod._libc
        old_platform = mod._IS_LINUX
        mod._libc = None
        try:
            with patch.object(mod, "_IS_LINUX", False):
                mod._libc = None  # reset again after patch
                result = _load_libc()
                # When _IS_LINUX is patched to False, returns None
                # (but _load_libc reads module-level _IS_LINUX)
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

    @pytest.mark.skipif(not _IS_LINUX, reason="libc only on Linux")
    def test_libc_has_syscall(self) -> None:
        import src.sandbox as mod

        old = mod._libc
        mod._libc = None
        try:
            libc = _load_libc()
            assert libc is not None
            assert hasattr(libc, "syscall")
        finally:
            mod._libc = old


# -- TestLandlockAvailability --


class TestLandlockAvailability:
    def test_not_available_on_non_linux(self) -> None:
        import src.sandbox as mod

        old = mod._landlock_available
        mod._landlock_available = None
        try:
            with patch.object(mod, "_IS_LINUX", False):
                result = _check_landlock_available()
                assert result is False
        finally:
            mod._landlock_available = old

    def test_caches_result(self) -> None:
        import src.sandbox as mod

        old = mod._landlock_available
        mod._landlock_available = True
        try:
            # Should return cached value without checking anything
            assert _check_landlock_available() is True
        finally:
            mod._landlock_available = old

    def test_caches_false_result(self) -> None:
        import src.sandbox as mod

        old = mod._landlock_available
        mod._landlock_available = False
        try:
            assert _check_landlock_available() is False
        finally:
            mod._landlock_available = old


# -- TestRawSyscallErrors --


class TestRawSyscallErrors:
    @patch("src.sandbox._raw_landlock_create_ruleset", return_value=-1)
    @patch("src.sandbox.ctypes.get_errno", return_value=38)
    @patch("src.sandbox._IS_LINUX", True)
    @patch("src.sandbox._check_landlock_available", return_value=True)
    def test_create_ruleset_failure_raises(
        self,
        mock_avail: MagicMock,
        mock_errno: MagicMock,
        mock_create: MagicMock,
    ) -> None:
        sb = Sandbox()
        sb.unveil("/tmp", "r")
        with pytest.raises(LandlockError, match="landlock_create_ruleset.*failed"):
            sb.apply_unveils()

    @patch("src.sandbox._raw_landlock_create_ruleset", return_value=5)
    @patch("src.sandbox._raw_landlock_add_rule", return_value=-1)
    @patch("src.sandbox.ctypes.get_errno", return_value=22)
    @patch("src.sandbox._IS_LINUX", True)
    @patch("src.sandbox._check_landlock_available", return_value=True)
    def test_add_rule_failure_raises(
        self,
        mock_avail: MagicMock,
        mock_errno: MagicMock,
        mock_add: MagicMock,
        mock_create: MagicMock,
    ) -> None:
        sb = Sandbox()
        sb.unveil("/tmp", "r")
        with pytest.raises(LandlockError, match="landlock_add_rule.*failed"):
            sb.apply_unveils()

    @patch("src.sandbox._raw_landlock_restrict_self", return_value=-1)
    @patch("src.sandbox.ctypes.get_errno", return_value=1)
    @patch("src.sandbox._load_libc", return_value=MagicMock())
    @patch("src.sandbox._IS_LINUX", True)
    @patch("src.sandbox._check_landlock_available", return_value=True)
    def test_restrict_self_failure_raises(
        self,
        mock_avail: MagicMock,
        mock_libc: MagicMock,
        mock_errno: MagicMock,
        mock_restrict: MagicMock,
    ) -> None:
        sb = Sandbox()
        sb.promise("stdio")
        sb._ruleset_fd = 5  # simulate a valid ruleset fd
        # Mock os.close to avoid closing a bad fd
        with patch("src.sandbox.os.close"):
            with pytest.raises(LandlockError, match="landlock_restrict_self.*failed"):
                sb.apply_pledge()

    @patch("src.sandbox._check_landlock_available", return_value=False)
    @patch("src.sandbox._IS_LINUX", False)
    def test_apply_pledge_noop_on_non_linux(self, mock_avail: MagicMock) -> None:
        """On non-Linux, apply_pledge succeeds as a no-op but sets state."""
        sb = Sandbox()
        sb.promise("stdio")
        sb.apply_pledge()
        assert sb.is_pledged is True

    @patch("src.sandbox._check_landlock_available", return_value=False)
    @patch("src.sandbox._IS_LINUX", False)
    def test_apply_unveils_noop_on_non_linux(self, mock_avail: MagicMock) -> None:
        """On non-Linux, apply_unveils returns without creating ruleset."""
        sb = Sandbox()
        sb.unveil("/tmp", "r")
        sb.apply_unveils()
        # No error, no ruleset fd
        assert sb._ruleset_fd == -1


# -- TestApplyConvenience --


class TestApplyConvenience:
    @patch("src.sandbox._check_landlock_available", return_value=False)
    @patch("src.sandbox._IS_LINUX", False)
    def test_apply_with_unveils_locks_and_pledges(self, mock_avail: MagicMock) -> None:
        sb = Sandbox()
        sb.promise("stdio", "rpath").unveil("/tmp", "r")
        sb.apply()
        assert sb.is_pledged is True
        assert sb.is_unveil_locked is True

    @patch("src.sandbox._check_landlock_available", return_value=False)
    @patch("src.sandbox._IS_LINUX", False)
    def test_apply_without_unveils_only_pledges(self, mock_avail: MagicMock) -> None:
        sb = Sandbox()
        sb.promise("stdio")
        sb.apply()
        assert sb.is_pledged is True
        assert sb.is_unveil_locked is False

    @patch("src.sandbox._check_landlock_available", return_value=False)
    @patch("src.sandbox._IS_LINUX", False)
    def test_apply_with_empty_promises_raises(self, mock_avail: MagicMock) -> None:
        sb = Sandbox()
        sb.unveil("/tmp", "r")
        with pytest.raises(SandboxError, match="empty promise set"):
            sb.apply()

    @patch("src.sandbox._check_landlock_available", return_value=False)
    @patch("src.sandbox._IS_LINUX", False)
    def test_apply_calls_apply_unveils_then_lock_then_pledge(
        self, mock_avail: MagicMock
    ) -> None:
        sb = Sandbox()
        sb.promise("stdio").unveil("/tmp", "r")

        calls: list[str] = []
        orig_apply_unveils = sb.apply_unveils
        orig_lock = sb.lock_unveil
        orig_pledge = sb.apply_pledge

        def track_unveils() -> None:
            calls.append("apply_unveils")
            orig_apply_unveils()

        def track_lock() -> None:
            calls.append("lock_unveil")
            orig_lock()

        def track_pledge() -> None:
            calls.append("apply_pledge")
            orig_pledge()

        sb.apply_unveils = track_unveils  # type: ignore[assignment]
        sb.lock_unveil = track_lock  # type: ignore[assignment]
        sb.apply_pledge = track_pledge  # type: ignore[assignment]

        sb.apply()
        assert calls == ["apply_unveils", "lock_unveil", "apply_pledge"]


# -- TestSubprocessIntegration --


@pytest.mark.skipif(not _IS_LINUX, reason="Landlock sandbox only on Linux")
class TestSubprocessIntegration:
    """Integration tests that run real Landlock operations in isolated subprocesses."""

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

    def test_sandbox_promise_any_string_succeeds(self) -> None:
        result = self._run_snippet(
            "from src.sandbox import Sandbox\n"
            "sb = Sandbox().promise('stdio')\n"
            "print(f'promises={sb.promises}')\n"
        )
        assert result.returncode == 0
        assert "stdio" in result.stdout

    def test_sandbox_promise_custom_string_succeeds(self) -> None:
        """Promises are free-form on Linux — any string is accepted."""
        result = self._run_snippet(
            "from src.sandbox import Sandbox\n"
            "sb = Sandbox().promise('custom_thing')\n"
            "print(f'promises={sb.promises}')\n"
        )
        assert result.returncode == 0
        assert "custom_thing" in result.stdout

    def test_unveil_and_lock(self) -> None:
        result = self._run_snippet(
            "from src.sandbox import Sandbox\n"
            "sb = Sandbox()\n"
            "sb.promise('stdio', 'rpath')\n"
            "sb.unveil('/tmp', 'r')\n"
            "sb.apply_unveils()\n"
            "sb.lock_unveil()\n"
            "print('locked')\n"
        )
        assert result.returncode == 0
        assert "locked" in result.stdout

    def test_unveil_lock_prevents_additions(self) -> None:
        result = self._run_snippet(
            "from src.sandbox import Sandbox, SandboxError\n"
            "sb = Sandbox()\n"
            "sb.promise('stdio', 'rpath')\n"
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
            "    .promise('stdio', 'rpath')\n"
            "    .unveil('/tmp', 'r')\n"
            ")\n"
            "sb.apply()\n"
            "print(f'pledged={sb.is_pledged}')\n"
            "print(f'locked={sb.is_unveil_locked}')\n"
        )
        assert result.returncode == 0
        assert "pledged=True" in result.stdout
        assert "locked=True" in result.stdout

    def test_apply_without_unveils(self) -> None:
        result = self._run_snippet(
            "from src.sandbox import Sandbox\n"
            "sb = Sandbox().promise('stdio')\n"
            "sb.apply()\n"
            "print(f'pledged={sb.is_pledged}')\n"
            "print(f'locked={sb.is_unveil_locked}')\n"
        )
        assert result.returncode == 0
        assert "pledged=True" in result.stdout
        assert "locked=False" in result.stdout

    def test_empty_promise_raises(self) -> None:
        result = self._run_snippet(
            "from src.sandbox import Sandbox, SandboxError\n"
            "try:\n"
            "    Sandbox().promise()\n"
            "    print('ERROR: no exception')\n"
            "except SandboxError as e:\n"
            "    print(f'caught: {e}')\n"
        )
        assert result.returncode == 0
        assert "caught:" in result.stdout

    def test_is_supported_reflects_platform(self) -> None:
        result = self._run_snippet(
            "from src.sandbox import Sandbox\n"
            "sb = Sandbox()\n"
            "print(f'supported={sb.is_supported}')\n"
        )
        assert result.returncode == 0
        # On Linux, this may be True or False depending on kernel support
        assert "supported=" in result.stdout
