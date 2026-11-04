#!/usr/bin/env python3
"""Install the Greenfield skill: the no-dependency path (the code lives in skill/scripts/gf_install.py; Python 3.11+)."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "skill" / "scripts"))
from gf_install import *  # noqa: F401,F403  (tests and callers use install.main, install.GITIGNORE_MARK)
from gf_install import main

if __name__ == "__main__":
    raise SystemExit(main())
