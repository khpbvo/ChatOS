"""Pre-built sandbox profiles for ChatOS processes.

Each builder function returns a configured Sandbox instance with the
minimal pledge promises and unveil paths needed for its role.

AD-29: Profiles are code (not TOML) because they depend on runtime CLI args.
AD-30: Broad exec_promises for the Claude CLI subprocess (Node.js V8 JIT).
AD-31: Graceful failure — callers catch exceptions and continue unsandboxed.
"""

from pathlib import Path

from .sandbox import Sandbox

# -- Exec promises for the Claude CLI child process --------------------------
# The Claude CLI (Node.js) IS the agent — it runs user-requested commands.
# The rules engine provides semantic filtering; pledge provides OS-level caps.
# Excluded: settime, route, wroute, disklabel, audio, video,
#           bpf, vmm, drm, pf, mcast, dpath, tape, error
_EXEC_PROMISES: tuple[str, ...] = (
    "stdio", "rpath", "wpath", "cpath", "tmppath",
    "inet", "dns", "unix", "proc", "exec",
    "tty", "flock", "fattr", "ps", "getpw", "id",
    "prot_exec", "chown", "sendfd", "recvfd",
)

# -- Common parent promises shared by both profiles -------------------------
_COMMON_PROMISES: tuple[str, ...] = (
    "stdio", "rpath", "wpath", "cpath", "inet",
    "proc", "exec", "dns", "unix", "tmppath", "flock", "unveil",
)


def _add_common_unveils(sb: Sandbox, log_dir: str, app_dir: str) -> None:
    """Add unveil paths shared by both server and CLI profiles."""
    sb.unveil("/etc", "r")
    sb.unveil("/usr", "rx")
    sb.unveil("/bin", "rx")
    sb.unveil("/sbin", "rx")
    sb.unveil("/dev/null", "rw")
    sb.unveil("/dev/urandom", "r")
    sb.unveil("/tmp", "rwc")
    sb.unveil("/var/chatos", "rwc")
    sb.unveil(app_dir, "r")

    # Only add log_dir if it's not already under /var/chatos
    log_path = Path(log_dir).resolve()
    var_chatos = Path("/var/chatos").resolve()
    try:
        log_path.relative_to(var_chatos)
    except ValueError:
        # log_dir is outside /var/chatos — unveil it separately
        sb.unveil(str(log_path), "rwc")


def build_server_sandbox(
    *,
    log_dir: str = "/var/chatos/logs",
    home_dir: str | None = None,
    static_dir: str | None = None,
    app_dir: str = "/usr/local/share/chatos",
) -> Sandbox:
    """Build a Sandbox for the WebSocket/agent server (_chatos process).

    Parameters
    ----------
    log_dir : str
        Audit log directory (default: /var/chatos/logs).
    home_dir : str | None
        User home directory for /files/ serving. Unveiled rwc if set.
    static_dir : str | None
        Static UI dist directory. Unveiled r if set and not under app_dir.
    app_dir : str
        Application source root (default: /usr/local/share/chatos).
    """
    sb = Sandbox()

    # Parent process promises
    sb.promise(*_COMMON_PROMISES)

    # Exec promises for Claude CLI subprocess
    sb.exec_promise(*_EXEC_PROMISES)

    # Common unveils
    _add_common_unveils(sb, log_dir, app_dir)

    # Home directory for file serving + agent writes
    if home_dir is not None:
        sb.unveil(home_dir, "rwc")

    # Static UI dist (only if not already under app_dir)
    if static_dir is not None:
        static_path = Path(static_dir).resolve()
        app_path = Path(app_dir).resolve()
        try:
            static_path.relative_to(app_path)
        except ValueError:
            # static_dir is outside app_dir — unveil separately
            sb.unveil(str(static_path), "r")

    return sb


def build_cli_sandbox(
    *,
    log_dir: str = "/var/chatos/logs",
    app_dir: str = "/usr/local/share/chatos",
) -> Sandbox:
    """Build a Sandbox for the CLI REPL (admin/dev interface).

    Same as the server profile plus ``tty`` for interactive terminal I/O.
    No ``home_dir`` or ``static_dir`` — the CLI doesn't serve files.

    Parameters
    ----------
    log_dir : str
        Audit log directory (default: /var/chatos/logs).
    app_dir : str
        Application source root (default: /usr/local/share/chatos).
    """
    sb = Sandbox()

    # Parent process promises — same as server plus tty for interactive REPL
    sb.promise(*_COMMON_PROMISES, "tty")

    # Exec promises for Claude CLI subprocess
    sb.exec_promise(*_EXEC_PROMISES)

    # Common unveils
    _add_common_unveils(sb, log_dir, app_dir)

    return sb
