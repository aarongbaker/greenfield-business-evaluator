#!/usr/bin/env python3
"""Platform gate (W26). Native Windows has no fcntl, so only commands that take file locks refuse there.

Standard library only. Importing this module never fails, on any platform.
"""
from __future__ import annotations
from gf_common import GFError

try:
    import fcntl
except ImportError:  # native Windows: no POSIX file locks
    fcntl = None

HAS_FCNTL = fcntl is not None
WSL_URL = "https://learn.microsoft.com/windows/wsl/install"


class UnsupportedPlatform(GFError):
    json_code = "unsupported_platform"


def require_locking(command):
    """Raise UnsupportedPlatform (exit 3) when a command needs file locks and this platform has none."""
    if not HAS_FCNTL:
        raise UnsupportedPlatform(f"`{command}` needs POSIX file locking, which native Windows does not have.", code=3,
                                  hint=f"Run it inside WSL ({WSL_URL}). Read-only commands such as score, ledger verify, portfolio and doctor work here.")


def lock_exclusive(fd, command):
    """Block until this process holds an exclusive lock on fd; refuses where fcntl is missing."""
    require_locking(command)
    fcntl.flock(fd, fcntl.LOCK_EX)


def unlock(fd):
    if HAS_FCNTL:
        fcntl.flock(fd, fcntl.LOCK_UN)
