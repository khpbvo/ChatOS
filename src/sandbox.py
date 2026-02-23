"""Linux Landlock filesystem sandbox Python ctypes bindings.

Provides a builder-pattern Sandbox class for configuring and applying
filesystem access restrictions using the Landlock LSM (Linux 5.13+).
On non-Linux platforms or kernels without Landlock, syscalls are no-ops
but state tracking still works for identical application code.

Landlock replaces OpenBSD's pledge/unveil:
- unveil(path, perms) → landlock_add_rule(path, access_flags)
- pledge(promises)    → landlock_restrict_self(ruleset)
"""

import ctypes
import ctypes.util
import os
import struct
import sys

_IS_LINUX: bool = sys.platform.startswith("linux")

# Landlock ABI version and syscall numbers (x86_64 / aarch64)
_LANDLOCK_CREATE_RULESET = 444
_LANDLOCK_ADD_RULE = 445
_LANDLOCK_RESTRICT_SELF = 446

# Landlock access flags for filesystem rules (ABI v1+)
LANDLOCK_ACCESS_FS_EXECUTE = 1 << 0
LANDLOCK_ACCESS_FS_WRITE_FILE = 1 << 1
LANDLOCK_ACCESS_FS_READ_FILE = 1 << 2
LANDLOCK_ACCESS_FS_READ_DIR = 1 << 3
LANDLOCK_ACCESS_FS_REMOVE_DIR = 1 << 4
LANDLOCK_ACCESS_FS_REMOVE_FILE = 1 << 5
LANDLOCK_ACCESS_FS_MAKE_CHAR = 1 << 6
LANDLOCK_ACCESS_FS_MAKE_DIR = 1 << 7
LANDLOCK_ACCESS_FS_MAKE_REG = 1 << 8
LANDLOCK_ACCESS_FS_MAKE_SOCK = 1 << 9
LANDLOCK_ACCESS_FS_MAKE_FIFO = 1 << 10
LANDLOCK_ACCESS_FS_MAKE_BLOCK = 1 << 11
LANDLOCK_ACCESS_FS_MAKE_SYM = 1 << 12

# Rule type
_LANDLOCK_RULE_PATH_BENEATH = 1

# Aggregate access masks for permission characters
_PERM_READ = (
    LANDLOCK_ACCESS_FS_READ_FILE
    | LANDLOCK_ACCESS_FS_READ_DIR
)
_PERM_WRITE = (
    LANDLOCK_ACCESS_FS_WRITE_FILE
    | LANDLOCK_ACCESS_FS_REMOVE_DIR
    | LANDLOCK_ACCESS_FS_REMOVE_FILE
    | LANDLOCK_ACCESS_FS_MAKE_CHAR
    | LANDLOCK_ACCESS_FS_MAKE_DIR
    | LANDLOCK_ACCESS_FS_MAKE_REG
    | LANDLOCK_ACCESS_FS_MAKE_SOCK
    | LANDLOCK_ACCESS_FS_MAKE_FIFO
    | LANDLOCK_ACCESS_FS_MAKE_BLOCK
    | LANDLOCK_ACCESS_FS_MAKE_SYM
)
_PERM_EXECUTE = LANDLOCK_ACCESS_FS_EXECUTE

# All filesystem access flags (ABI v1)
_ALL_FS_ACCESS = _PERM_READ | _PERM_WRITE | _PERM_EXECUTE

# Permission character mapping (compatible with the old unveil API)
VALID_UNVEIL_PERMISSIONS: set[str] = {"r", "w", "x", "c"}

_PERM_MAP: dict[str, int] = {
    "r": _PERM_READ,
    "w": _PERM_WRITE,
    "x": _PERM_EXECUTE,
    "c": _PERM_WRITE,  # "create" maps to write access on Linux
}

# Module-level cache for libc
_libc: ctypes.CDLL | None = None

# Landlock availability flag (set after first check)
_landlock_available: bool | None = None


class SandboxError(Exception):
    """Base exception for sandbox operations."""


class LandlockError(SandboxError):
    """Landlock syscall failed."""

    def __init__(self, message: str, errno_code: int) -> None:
        self.errno_code = errno_code
        super().__init__(f"{message}: {os.strerror(errno_code)} (errno {errno_code})")


# Keep the old names as aliases for backward compatibility in tests
PledgeError = LandlockError
UnveilError = LandlockError


def _load_libc() -> ctypes.CDLL | None:
    """Load libc with errno support. Returns None on non-Linux."""
    global _libc
    if _libc is not None:
        return _libc
    if not _IS_LINUX:
        return None
    lib_name = ctypes.util.find_library("c")
    if lib_name is None:
        return None
    _libc = ctypes.CDLL(lib_name, use_errno=True)
    return _libc


def _check_landlock_available() -> bool:
    """Check if Landlock is available on this kernel."""
    global _landlock_available
    if _landlock_available is not None:
        return _landlock_available

    if not _IS_LINUX:
        _landlock_available = False
        return False

    libc = _load_libc()
    if libc is None:
        _landlock_available = False
        return False

    # Try creating a minimal ruleset to test availability
    try:
        # struct landlock_ruleset_attr { __u64 handled_access_fs; }
        attr = struct.pack("Q", _ALL_FS_ACCESS)
        ret = libc.syscall(
            ctypes.c_long(_LANDLOCK_CREATE_RULESET),
            ctypes.c_char_p(attr),
            ctypes.c_size_t(len(attr)),
            ctypes.c_uint32(0),
        )
        if ret >= 0:
            os.close(ret)
            _landlock_available = True
        else:
            _landlock_available = False
    except Exception:
        _landlock_available = False

    return _landlock_available


def _raw_landlock_create_ruleset(handled_access_fs: int) -> int:
    """Create a Landlock ruleset. Returns fd on success, -1 on error."""
    libc = _load_libc()
    if libc is None:
        return -1
    attr = struct.pack("Q", handled_access_fs)
    return libc.syscall(
        ctypes.c_long(_LANDLOCK_CREATE_RULESET),
        ctypes.c_char_p(attr),
        ctypes.c_size_t(len(attr)),
        ctypes.c_uint32(0),
    )


def _raw_landlock_add_rule(ruleset_fd: int, path: str, access: int) -> int:
    """Add a path rule to a Landlock ruleset. Returns 0 on success, -1 on error."""
    libc = _load_libc()
    if libc is None:
        return 0
    # Open the path with O_PATH
    path_fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
    try:
        # struct landlock_path_beneath_attr { __u64 allowed_access; __s32 parent_fd; }
        # Need padding after parent_fd to align struct
        attr = struct.pack("Qi", access, path_fd)
        ret = libc.syscall(
            ctypes.c_long(_LANDLOCK_ADD_RULE),
            ctypes.c_int(ruleset_fd),
            ctypes.c_int(_LANDLOCK_RULE_PATH_BENEATH),
            ctypes.c_char_p(attr),
            ctypes.c_uint32(0),
        )
        return ret
    finally:
        os.close(path_fd)


def _raw_landlock_restrict_self(ruleset_fd: int) -> int:
    """Apply a Landlock ruleset to the current process. Returns 0 on success."""
    libc = _load_libc()
    if libc is None:
        return 0
    return libc.syscall(
        ctypes.c_long(_LANDLOCK_RESTRICT_SELF),
        ctypes.c_int(ruleset_fd),
        ctypes.c_uint32(0),
    )


def _perms_to_access(perms: str) -> int:
    """Convert permission characters (r/w/x/c) to Landlock access flags."""
    access = 0
    for ch in perms:
        access |= _PERM_MAP.get(ch, 0)
    return access


def validate_unveil_permissions(perms: str) -> None:
    """Validate unveil permission string (subset of 'rwxc')."""
    if not perms:
        raise SandboxError("Unveil permissions cannot be empty")
    for ch in perms:
        if ch not in VALID_UNVEIL_PERMISSIONS:
            raise SandboxError(f"Invalid unveil permission character: {ch!r}")


class Sandbox:
    """Builder for configuring and applying Landlock filesystem restrictions.

    Phase 1 (builder): .unveil() stores path/permission config.
    Phase 2 (apply): .apply_unveils(), .lock_unveil(), .apply_pledge(), or .apply().

    The API mirrors the old OpenBSD pledge/unveil interface for code compatibility.
    On Linux, .apply_pledge() applies the Landlock ruleset (restricting filesystem).
    """

    def __init__(self) -> None:
        self._promises: set[str] = set()
        self._exec_promises: set[str] = set()
        self._unveils: list[tuple[str, str]] = []
        self._pledged: bool = False
        self._unveil_locked: bool = False
        self._ruleset_fd: int = -1

    @property
    def is_supported(self) -> bool:
        """True if running on Linux with Landlock available."""
        return _IS_LINUX and _check_landlock_available()

    @property
    def is_pledged(self) -> bool:
        """True if sandbox has been applied (Landlock ruleset enforced)."""
        return self._pledged

    @property
    def is_unveil_locked(self) -> bool:
        """True if unveil list has been locked (no more paths can be added)."""
        return self._unveil_locked

    @property
    def promises(self) -> frozenset[str]:
        """Current set of promises (kept for API compatibility)."""
        return frozenset(self._promises)

    @property
    def exec_promises(self) -> frozenset[str]:
        """Current set of exec promises (kept for API compatibility)."""
        return frozenset(self._exec_promises)

    @property
    def unveiled_paths(self) -> list[tuple[str, str]]:
        """List of (path, permissions) tuples added via .unveil()."""
        return list(self._unveils)

    def promise(self, *names: str) -> "Sandbox":
        """Add promises (kept for API compatibility). Returns self for chaining.

        On Linux, promises are tracked but not individually enforced.
        Filesystem access is controlled via Landlock unveil rules.
        """
        if self._pledged:
            raise SandboxError("Cannot add promises after sandbox has been applied")
        if not names:
            raise SandboxError("At least one promise is required")
        self._promises.update(names)
        return self

    def exec_promise(self, *names: str) -> "Sandbox":
        """Set exec promises for child processes. Returns self for chaining."""
        if self._pledged:
            raise SandboxError("Cannot add exec promises after sandbox has been applied")
        if not names:
            raise SandboxError("At least one promise is required")
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
        """Create Landlock ruleset and add rules for each stored path."""
        if not _IS_LINUX or not _check_landlock_available():
            return

        # Create the ruleset
        self._ruleset_fd = _raw_landlock_create_ruleset(_ALL_FS_ACCESS)
        if self._ruleset_fd < 0:
            errno_code = ctypes.get_errno()
            raise LandlockError("landlock_create_ruleset() failed", errno_code)

        # Add rules for each unveiled path
        for path, perms in self._unveils:
            access = _perms_to_access(perms)
            try:
                ret = _raw_landlock_add_rule(self._ruleset_fd, path, access)
            except OSError as exc:
                # Path might not exist — skip it (same as OpenBSD unveil behavior
                # when the path doesn't exist yet)
                continue
            if ret != 0:
                errno_code = ctypes.get_errno()
                raise LandlockError(
                    f"landlock_add_rule({path!r}, {perms!r}) failed", errno_code,
                )

    def lock_unveil(self) -> None:
        """Lock the unveil list. Idempotent."""
        if self._unveil_locked:
            return
        self._unveil_locked = True

    def apply_pledge(self) -> None:
        """Apply the Landlock ruleset to restrict the current process."""
        if not self._promises:
            raise SandboxError("Cannot apply sandbox with empty promise set")
        if self._pledged:
            raise SandboxError(
                "Sandbox has already been applied; create a new Sandbox to re-apply"
            )

        if _IS_LINUX and _check_landlock_available() and self._ruleset_fd >= 0:
            # Set no_new_privs (required by Landlock)
            import ctypes as ct
            _PR_SET_NO_NEW_PRIVS = 38
            libc = _load_libc()
            if libc is not None:
                libc.prctl(
                    ct.c_int(_PR_SET_NO_NEW_PRIVS),
                    ct.c_ulong(1), ct.c_ulong(0), ct.c_ulong(0), ct.c_ulong(0),
                )

            ret = _raw_landlock_restrict_self(self._ruleset_fd)
            if ret != 0:
                errno_code = ctypes.get_errno()
                raise LandlockError("landlock_restrict_self() failed", errno_code)

            os.close(self._ruleset_fd)
            self._ruleset_fd = -1

        self._pledged = True

    def apply(self) -> None:
        """Convenience: apply unveils, lock unveil list, then apply sandbox.

        If no unveils were configured, skips unveil lock.
        """
        if self._unveils:
            self.apply_unveils()
            self.lock_unveil()
        self.apply_pledge()
