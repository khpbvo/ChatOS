"""OpenBSD pledge(2) and unveil(2) Python ctypes bindings.

Provides a builder-pattern Sandbox class for configuring and applying
process restrictions. On non-OpenBSD platforms, syscalls are no-ops
but state tracking still works for identical application code.
"""

import ctypes
import ctypes.util
import os
import sys

_IS_OPENBSD: bool = sys.platform.startswith("openbsd")

# All pledge promises from OpenBSD 7.8 pledge(2)
VALID_PROMISES: frozenset[str] = frozenset({
    "stdio", "rpath", "wpath", "cpath", "dpath", "tmppath", "inet", "mcast",
    "fattr", "chown", "flock", "unix", "dns", "getpw", "sendfd", "recvfd",
    "tape", "tty", "proc", "exec", "prot_exec", "settime", "ps", "unveil",
    "route", "wroute", "vminfo", "error", "disklabel", "audio", "video",
    "bpf", "id", "vmm", "drm", "pf",
})

VALID_UNVEIL_PERMISSIONS: set[str] = {"r", "w", "x", "c"}

# Module-level cache for loaded libc
_libc: ctypes.CDLL | None = None


class SandboxError(Exception):
    """Base exception for sandbox operations."""


class PledgeError(SandboxError):
    """pledge(2) syscall failed."""

    def __init__(self, message: str, errno_code: int) -> None:
        self.errno_code = errno_code
        super().__init__(f"{message}: {os.strerror(errno_code)} (errno {errno_code})")


class UnveilError(SandboxError):
    """unveil(2) syscall failed."""

    def __init__(self, message: str, errno_code: int) -> None:
        self.errno_code = errno_code
        super().__init__(f"{message}: {os.strerror(errno_code)} (errno {errno_code})")


def _load_libc() -> ctypes.CDLL | None:
    """Load libc with errno support. Returns None on non-OpenBSD."""
    global _libc
    if _libc is not None:
        return _libc
    if not _IS_OPENBSD:
        return None
    lib_name = ctypes.util.find_library("c")
    if lib_name is None:
        return None
    _libc = ctypes.CDLL(lib_name, use_errno=True)
    _libc.pledge.restype = ctypes.c_int
    _libc.pledge.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
    _libc.unveil.restype = ctypes.c_int
    _libc.unveil.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
    return _libc


def _raw_pledge(promises: str | None, execpromises: str | None) -> int:
    """Call pledge(2). Returns 0 on success, -1 on error. No-op off OpenBSD."""
    libc = _load_libc()
    if libc is None:
        return 0
    p = promises.encode("ascii") if promises is not None else None
    ep = execpromises.encode("ascii") if execpromises is not None else None
    return libc.pledge(p, ep)


def _raw_unveil(path: str | None, permissions: str | None) -> int:
    """Call unveil(2). Returns 0 on success, -1 on error. No-op off OpenBSD."""
    libc = _load_libc()
    if libc is None:
        return 0
    p = path.encode("utf-8") if path is not None else None
    perm = permissions.encode("ascii") if permissions is not None else None
    return libc.unveil(p, perm)


def validate_promises(*names: str) -> None:
    """Validate that all promise names are known OpenBSD pledge promises."""
    if not names:
        raise SandboxError("At least one promise is required")
    for name in names:
        if name not in VALID_PROMISES:
            raise SandboxError(f"Unknown pledge promise: {name!r}")


def validate_unveil_permissions(perms: str) -> None:
    """Validate unveil permission string (subset of 'rwxc')."""
    if not perms:
        raise SandboxError("Unveil permissions cannot be empty")
    for ch in perms:
        if ch not in VALID_UNVEIL_PERMISSIONS:
            raise SandboxError(f"Invalid unveil permission character: {ch!r}")


class Sandbox:
    """Builder for configuring and applying pledge/unveil restrictions.

    Phase 1 (builder): .promise(), .exec_promise(), .unveil() store config.
    Phase 2 (apply): .apply_unveils(), .lock_unveil(), .apply_pledge(), or .apply().
    """

    def __init__(self) -> None:
        self._promises: set[str] = set()
        self._exec_promises: set[str] = set()
        self._unveils: list[tuple[str, str]] = []
        self._pledged: bool = False
        self._unveil_locked: bool = False

    @property
    def is_supported(self) -> bool:
        """True if running on OpenBSD with pledge/unveil available."""
        return _IS_OPENBSD

    @property
    def is_pledged(self) -> bool:
        """True if pledge(2) has been applied."""
        return self._pledged

    @property
    def is_unveil_locked(self) -> bool:
        """True if unveil list has been locked (unveil(NULL, NULL))."""
        return self._unveil_locked

    @property
    def promises(self) -> frozenset[str]:
        """Current set of pledge promises."""
        return frozenset(self._promises)

    @property
    def exec_promises(self) -> frozenset[str]:
        """Current set of exec pledge promises."""
        return frozenset(self._exec_promises)

    @property
    def unveiled_paths(self) -> list[tuple[str, str]]:
        """List of (path, permissions) tuples added via .unveil()."""
        return list(self._unveils)

    def promise(self, *names: str) -> "Sandbox":
        """Add pledge promises. Validates names. Returns self for chaining."""
        if self._pledged:
            raise SandboxError("Cannot add promises after pledge has been applied")
        validate_promises(*names)
        self._promises.update(names)
        return self

    def exec_promise(self, *names: str) -> "Sandbox":
        """Set exec promises for child processes. Returns self for chaining."""
        if self._pledged:
            raise SandboxError("Cannot add exec promises after pledge has been applied")
        validate_promises(*names)
        self._exec_promises.update(names)
        return self

    def unveil(self, path: str, perms: str) -> "Sandbox":
        """Add a path with permissions to the unveil list. Returns self for chaining."""
        if self._unveil_locked:
            raise SandboxError("Cannot add unveil paths after unveil has been locked")
        validate_unveil_permissions(perms)
        self._unveils.append((path, perms))
        return self

    def apply_unveils(self) -> None:
        """Execute unveil(2) for each stored path."""
        for path, perms in self._unveils:
            ret = _raw_unveil(path, perms)
            if ret != 0:
                errno_code = ctypes.get_errno()
                raise UnveilError(f"unveil({path!r}, {perms!r}) failed", errno_code)

    def lock_unveil(self) -> None:
        """Lock the unveil list by calling unveil(NULL, NULL). Idempotent."""
        if self._unveil_locked:
            return
        ret = _raw_unveil(None, None)
        if ret != 0:
            errno_code = ctypes.get_errno()
            raise UnveilError("unveil(NULL, NULL) failed", errno_code)
        self._unveil_locked = True

    def apply_pledge(self) -> None:
        """Execute pledge(2) with stored promises."""
        if not self._promises:
            raise SandboxError("Cannot apply pledge with empty promise set")
        if self._pledged:
            raise SandboxError(
                "pledge has already been applied; create a new Sandbox to re-pledge"
            )
        promise_str = " ".join(sorted(self._promises))
        exec_str = " ".join(sorted(self._exec_promises)) if self._exec_promises else None
        ret = _raw_pledge(promise_str, exec_str)
        if ret != 0:
            errno_code = ctypes.get_errno()
            raise PledgeError(f"pledge({promise_str!r}) failed", errno_code)
        self._pledged = True

    def apply(self) -> None:
        """Convenience: apply unveils, lock unveil list, then apply pledge.

        If no unveils were configured, skips unveil lock.
        """
        if self._unveils:
            self.apply_unveils()
            self.lock_unveil()
        self.apply_pledge()
