"""W26: native Windows has no fcntl. Locking commands refuse there with a clear message; everything else runs.

Windows is simulated on Linux and macOS by making `import fcntl` fail in a subprocess. The
CI `windows` job runs the two command classes on a real Windows runner.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
import importlib
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skill" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import gf_platform  # noqa: E402
from test_v2 import BUDGET, portfolio_item  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "validate-before-build.json"
GF = [sys.executable, str(SCRIPTS / "greenfield.py")]
# Same entry point as greenfield.py, but with fcntl unimportable, as on native Windows.
NO_FCNTL = "import sys; sys.modules['fcntl'] = None; sys.path.insert(0, sys.argv[1]); from cli import main; raise SystemExit(main(sys.argv[2:]))"
ENV = {k: v for k, v in os.environ.items() if k != "GREENFIELD_NO_DEPRECATION"}

# Every command that takes a file lock (cli.LOCKING_COMMANDS), with arguments that would otherwise succeed.
LOCKING = {
    "start": ["start", "--idea", "Test idea"],
    "demo": ["demo"],
    "task": ["task", "plan"],
    "event emit": ["event", "emit", "--event", "note", "--message", "x"],
    "ledger record": ["ledger", "record", "--ledger", "ledger.jsonl", "--kind", "note", "--project-name", "P", "--hypothesis", "H"],
    "hook": ["hook", "--provider", "claude"],
    "ingest-codex": ["ingest-codex"],
}


def run(args, cwd, windows=False, stdin=""):
    """Run greenfield with args; windows=True makes fcntl unimportable. Output is decoded as UTF-8 on every platform."""
    cmd = [sys.executable, "-c", NO_FCNTL, str(SCRIPTS), *args] if windows else GF + list(args)
    return subprocess.run(cmd, cwd=cwd, capture_output=True, encoding="utf-8", input=stdin, env=ENV, timeout=120)


def tree(folder):
    return sorted(str(p.relative_to(folder)) for p in Path(folder).rglob("*"))


class WindowsLockingCommands(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.p = Path(self.tmp.name)

    def test_each_locking_command_refuses_with_exit_3_and_writes_nothing(self):
        for name, argv in LOCKING.items():
            with self.subTest(command=name):
                before = tree(self.p)
                r = run(["--json", *argv], self.p, windows=True)
                self.assertEqual(r.returncode, 3, r.stderr)
                self.assertEqual(json.loads(r.stderr)["error"]["code"], "unsupported_platform")
                self.assertIn(f"`greenfield {name}` needs POSIX file locking", json.loads(r.stderr)["error"]["message"])
                self.assertNotIn("Traceback", r.stderr)
                self.assertEqual(tree(self.p), before, "a refused command must not create or change files")

    def test_text_message_names_wsl(self):
        r = run(["start", "--idea", "Test idea"], self.p, windows=True)
        self.assertEqual(r.returncode, 3)
        self.assertIn("POSIX file locking, which native Windows does not have", r.stderr)
        self.assertIn("WSL", r.stderr)
        self.assertIn("score, ledger verify, portfolio and doctor", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_help_and_version_still_run(self):
        for argv in (["--version"], ["task", "--help"], ["start", "--help"]):
            with self.subTest(argv=argv):
                r = run(argv, self.p, windows=True)
                self.assertEqual(r.returncode, 0, r.stderr)


class WindowsReadOnlyCommands(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.p = Path(self.tmp.name)
        shutil.copy(FIXTURE, self.p / "evaluation.json")

    def test_score_gives_the_same_decision_as_with_fcntl(self):
        linux = run(["--json", "score", "evaluation.json"], self.p)
        windows = run(["--json", "score", "evaluation.json"], self.p, windows=True)
        self.assertEqual(linux.returncode, 0, linux.stderr)
        self.assertEqual(windows.returncode, 0, windows.stderr)
        self.assertEqual(json.loads(windows.stdout), json.loads(linux.stdout))

    def test_ledger_verify_runs(self):
        # A recorded fixture, not `ledger record`: recording takes a lock, which real Windows refuses.
        shutil.copy(ROOT / "tests" / "fixtures" / "ledger-note.jsonl", self.p / "ledger.jsonl")
        r = run(["--json", "ledger", "verify", "--ledger", "ledger.jsonl"], self.p, windows=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_portfolio_runs_and_matches(self):
        item = portfolio_item(self.p, "Good")
        (self.p / "manifest.json").write_text(json.dumps({"constraints": BUDGET, "opportunities": [item]}))
        args = ["--json", "portfolio", "manifest.json", "--output", "ranking.json"]
        linux = run(args, self.p)
        self.assertEqual(linux.returncode, 0, linux.stderr)
        windows = run(args, self.p, windows=True)
        self.assertEqual(windows.returncode, 0, windows.stderr)
        self.assertEqual(json.loads(windows.stdout), json.loads(linux.stdout))

    def test_install_warns_about_wsl_and_installs(self):
        r = run(["--json", "install", "--no-gitignore", "--platform", "claude", "--scope", "project"], self.p, windows=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("WSL", r.stderr)
        self.assertTrue(any(self.p.joinpath(".claude").rglob("*.md")))


class PlatformGate(unittest.TestCase):
    def test_module_imports_without_fcntl_and_refuses_locks(self):
        with mock.patch.dict(sys.modules, {"fcntl": None}):
            module = importlib.reload(gf_platform)
            self.assertFalse(module.HAS_FCNTL)
            with self.assertRaises(module.UnsupportedPlatform) as caught:
                module.require_locking("greenfield task")
            self.assertEqual(caught.exception.code, 3)
            self.assertEqual(caught.exception.json_code, "unsupported_platform")
        self.addCleanup(importlib.reload, gf_platform)  # restore the real module for other tests

    def test_fcntl_is_used_only_in_gf_platform(self):
        pattern = re.compile(r"\bimport fcntl\b|\bfcntl\.")
        offenders = []
        for path in sorted(SCRIPTS.glob("*.py")):
            if path.name == "gf_platform.py":
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if not line.lstrip().startswith("#") and pattern.search(line):
                    offenders.append(f"{path.name}:{number}")
        self.assertEqual(offenders, [], "lock calls must go through gf_platform")


if __name__ == "__main__":
    unittest.main()
