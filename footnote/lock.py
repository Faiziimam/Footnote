"""Cross-process lock so a hook, the MCP server, the web page and the CLI can never write at once.

Uses the operating system's file locking (released automatically if a process dies, so there are no
stale locks). Re-entrant: nested use in one process is fine.
"""
import contextlib
import os
import threading
import time
from pathlib import Path

try:
    import fcntl
except ImportError:          # Windows
    fcntl = None
try:
    import msvcrt
except ImportError:          # POSIX
    msvcrt = None


class Busy(Exception):
    pass


_tlock = threading.RLock()
_held = {}                   # path -> [depth, filehandle]


def _try(fh):
    if fcntl:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False
    if msvcrt:
        try:
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    return True


def _release(fh):
    try:
        if fcntl:
            fcntl.flock(fh, fcntl.LOCK_UN)
        elif msvcrt:
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
    finally:
        fh.close()


@contextlib.contextmanager
def locked(path, timeout=60.0):
    path = os.path.realpath(str(path))   # one folder, one lock: /var vs /private/var (macOS), symlinks, Windows 8.3 short names
    if not _tlock.acquire(timeout=timeout):
        raise Busy()
    try:
        entry = _held.get(path)
        if entry is None:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            fh = open(path, "a+", encoding="utf-8")
            deadline = time.monotonic() + timeout
            while not _try(fh):
                if time.monotonic() > deadline:
                    fh.close()
                    raise Busy()
                time.sleep(0.05)
            entry = _held[path] = [0, fh]
        entry[0] += 1
        try:
            yield
        finally:
            entry[0] -= 1
            if entry[0] == 0:
                _held.pop(path, None)
                _release(entry[1])
    finally:
        _tlock.release()
