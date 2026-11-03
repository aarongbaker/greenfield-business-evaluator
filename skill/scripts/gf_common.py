#!/usr/bin/env python3
"""Shared helpers: path confinement, safe JSON loading, atomic writes, number checks, errors.

Standard library only.
"""
from __future__ import annotations
import json
import math
import os
from pathlib import Path
import sys
from uuid import uuid4

VERSION = "2.0.0"
MAX_JSON_BYTES = 5 * 1024 * 1024


class GFError(ValueError):
    """User-facing error; subclasses ValueError so existing `except ValueError` callers keep working."""
    def __init__(self, what, *, path=None, hint=None, code=2):
        super().__init__(what)
        self.what, self.path, self.hint, self.code = what, path, hint, code

    def as_dict(self):
        """Return the error as a JSON-ready dict."""
        return {"error": self.what, "path": None if self.path is None else str(self.path), "next": self.hint, "code": self.code}


def report(err, *, stream=sys.stderr):
    """Print `ERROR:` plus optional path and next-step lines; return the exit code (2 by default)."""
    print(f"ERROR: {err}", file=stream)
    if getattr(err, "path", None) is not None:
        print(f"  path: {err.path}", file=stream)
    if getattr(err, "hint", None):
        print(f"  next: {err.hint}", file=stream)
    return getattr(err, "code", 2)


def resolve_inside(base, candidate, *, must_exist=False):
    """Resolve candidate under base (following symlinks); raise GFError unless it lands at or below base."""
    text = str(candidate)
    if not text or "\x00" in text:
        raise GFError(f"invalid path {text!r}: empty or contains a NUL byte", path=base)
    try:
        root = Path(base).resolve(strict=True)
    except (OSError, RuntimeError) as e:
        raise GFError(f"base folder does not exist: {base}", path=base) from e
    target = (root / candidate).resolve()
    if not target.is_relative_to(root):
        raise GFError(f"{text} is outside {root}", path=target)
    if must_exist and not target.exists():
        raise GFError(f"{text} does not exist", path=target)
    return target


def _reject_constant(name):
    raise GFError(f"{name} is not allowed in JSON")


def _no_duplicates(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise GFError(f"duplicate JSON key {key!r}")
        out[key] = value
    return out


def load_json(path, *, max_bytes=MAX_JSON_BYTES, expect=dict, reject_duplicates=True, allow_nan=False):
    """Load a size-limited UTF-8 (BOM ok) JSON file; reject NaN/Infinity, duplicate keys, deep nesting, wrong top-level type."""
    path = Path(path)
    try:
        if path.stat().st_size > max_bytes:
            raise GFError(f"{path.name} is {path.stat().st_size} bytes, over the {max_bytes} byte limit", path=path)
        with open(path, "rb") as f:
            raw = f.read(max_bytes + 1)  # one extra byte catches a file that grew after stat()
    except OSError as e:
        raise GFError(f"cannot read {path.name}: {e.strerror or e}", path=path) from e
    if len(raw) > max_bytes:
        raise GFError(f"{path.name} is over the {max_bytes} byte limit", path=path)
    try:
        data = json.loads(raw.decode("utf-8-sig"),
                          object_pairs_hook=_no_duplicates if reject_duplicates else None,
                          parse_constant=None if allow_nan else _reject_constant)
    except GFError as e:
        raise GFError(f"{path.name}: {e}", path=path) from None
    except UnicodeDecodeError as e:
        raise GFError(f"{path.name} is not valid UTF-8 (byte {e.start})", path=path) from None
    except json.JSONDecodeError as e:
        raise GFError(f"{path.name} is not valid JSON (line {e.lineno}, column {e.colno})", path=path) from None
    except RecursionError:
        raise GFError(f"{path.name} is nested too deeply", path=path) from None
    if expect is not None and not isinstance(data, expect):
        raise GFError(f"{path.name}: expected a JSON {getattr(expect, '__name__', expect)} at top level, got {type(data).__name__}", path=path)
    return data


def atomic_write(path, data, *, mode=None):
    """Write bytes or str via a same-folder temp file, fsync and os.replace; mode None keeps the existing mode."""
    path = Path(path)
    if mode is None:
        try:
            mode = path.stat().st_mode & 0o7777
        except FileNotFoundError:
            pass
    tmp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    # 0o666 lets the umask pick a new file's mode, as write_text did; O_EXCL refuses an existing name.
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600 if mode is not None else 0o666)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data.encode("utf-8") if isinstance(data, str) else data)
            f.flush()
            os.fsync(f.fileno())
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    if os.name == "posix":
        try:
            dfd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        except OSError:
            pass  # some network filesystems refuse fsync on a folder


def atomic_write_json(path, obj, *, mode=None):
    """Atomically write obj as 2-space UTF-8 JSON with a trailing newline; NaN/Infinity raise ValueError."""
    atomic_write(path, json.dumps(obj, indent=2, ensure_ascii=False, allow_nan=False) + "\n", mode=mode)


def finite_nonneg(value, where, limit=None):
    """Return value as float if it is an int/float (not bool), finite, >= 0 and <= limit; else raise GFError naming where."""
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or (limit is not None and value > limit):
        raise GFError(f"{where} requires a finite nonnegative number" + (f" <= {limit}" if limit else ""))
    return float(value)
