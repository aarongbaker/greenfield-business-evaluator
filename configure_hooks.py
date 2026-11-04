#!/usr/bin/env python3
"""Opt-in local observability hooks (the code lives in skill/scripts/gf_hooks.py; Python 3.11+)."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "skill" / "scripts"))
from gf_hooks import *  # noqa: F401,F403  (tests and callers use configure_hooks.transform)
from gf_hooks import main
from gf_common import old_entry

if __name__ == "__main__":
    raise SystemExit(old_entry(main, "configure_hooks.py", "greenfield hooks"))
