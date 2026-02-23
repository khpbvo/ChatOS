#!/usr/bin/env python3
"""Acquire a controlling terminal on a VT and exec a command.

Used by launch-kiosk.sh to give xinit proper wscons console access
when started from an rc.d service (which has no controlling terminal).

Usage: vt-launch.py /dev/ttyC5 xinit /path/to/xinitrc -- :1 vt05
"""

import fcntl
import os
import sys
import termios


def main() -> None:
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} /dev/ttyCN command [args...]", file=sys.stderr)
        sys.exit(1)

    tty_path = sys.argv[1]
    cmd = sys.argv[2:]

    # Save the launch log fd so we can report errors after redirecting stdio
    log_fd = os.dup(2)

    # Fork so the child is not a process group leader (required for setsid).
    pid = os.fork()
    if pid > 0:
        # Parent exits immediately — child is reparented to init.
        # rc.d will find the child via pexp pattern matching.
        os._exit(0)

    # Child: become a new session leader
    os.setsid()

    # Open the target VT — as session leader, this becomes our controlling terminal
    try:
        fd = os.open(tty_path, os.O_RDWR)
    except OSError as e:
        os.write(log_fd, f"vt-launch: cannot open {tty_path}: {e}\n".encode())
        os._exit(1)

    try:
        fcntl.ioctl(fd, termios.TIOCSCTTY, 0)
    except OSError as e:
        os.write(log_fd, f"vt-launch: TIOCSCTTY failed on {tty_path}: {e}\n".encode())
        os._exit(1)

    # Redirect only stdin from the VT (X server checks stdin for terminal).
    # Keep stdout/stderr on the launch log for error visibility.
    os.dup2(fd, 0)
    if fd > 2:
        os.close(fd)

    os.write(log_fd, f"vt-launch: exec {cmd}\n".encode())
    os.close(log_fd)

    # Exec the command (replaces this process)
    os.execvp(cmd[0], cmd)


if __name__ == "__main__":
    main()
