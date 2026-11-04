import contextlib
import io
import pathlib
import py_compile
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "skill" / "scripts"))
import install
from gf_common import VERSION

SCRIPTS = ["score_project", "gf_portfolio", "gf_observe", "gf_ledger", "gf_runs", "gf_evidence"]
ENTRY_POINTS = [ROOT / "skill" / "scripts" / f"{name}.py" for name in SCRIPTS] + [ROOT / "install.py", ROOT / "configure_hooks.py"]
BYTECODE = ("*.pyc", "__pycache__", "*.tmp-*")


def leftovers(folder):
    return [p for p in folder.rglob("*") if any(p.match(pat) for pat in BYTECODE)]


def run_install(project, *extra):
    with contextlib.redirect_stdout(io.StringIO()):
        return install.main(["--platform", "both", "--project", str(project), *extra])


class PackageTests(unittest.TestCase):
    def test_install_has_no_bytecode(self):
        before = {p for p in ROOT.rglob("__pycache__") if ".git" not in p.parts}
        try:
            for path in ENTRY_POINTS + [ROOT / "skill" / "scripts" / "gf_profiles.py", ROOT / "skill" / "scripts" / "gf_common.py"]:
                py_compile.compile(str(path), doraise=True)
            self.assertTrue(list((ROOT / "skill" / "scripts").rglob("*.pyc")))
            with tempfile.TemporaryDirectory() as temp:
                self.assertEqual(run_install(pathlib.Path(temp)), 0)
                self.assertEqual(leftovers(pathlib.Path(temp)), [])
        finally:
            for p in set(ROOT.rglob("__pycache__")) - before:
                if ".git" not in p.parts:
                    shutil.rmtree(p)

    def test_force_reinstall_removes_stale_bytecode(self):
        with tempfile.TemporaryDirectory() as temp:
            project = pathlib.Path(temp)
            run_install(project)
            stale = project / ".claude" / "skills" / "greenfield-business-evaluator" / "scripts" / "stale.pyc"
            stale.parent.mkdir(parents=True, exist_ok=True)
            stale.write_bytes(b"")
            self.assertEqual(run_install(project, "--force"), 0)
            self.assertFalse(stale.exists())
            self.assertEqual(leftovers(project), [])

    def test_install_records_version(self):
        with tempfile.TemporaryDirectory() as temp:
            run_install(pathlib.Path(temp))
            marker = pathlib.Path(temp) / ".claude" / "skills" / "greenfield-business-evaluator" / ".greenfield-version"
            self.assertEqual(marker.read_text(encoding="utf-8").strip(), VERSION)

    def test_version_flag(self):
        for path in ENTRY_POINTS:
            with self.subTest(script=path.name):
                result = subprocess.run([sys.executable, str(path), "--version"], capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0)
                self.assertEqual(result.stdout.strip(), f"{path.name} {VERSION}")

    def test_single_version_source(self):
        literal = re.compile(r"""['"]\d+\.\d+\.\d+['"]""")
        for path in ROOT.rglob("*.py"):
            if ".git" in path.parts or path.name == "gf_common.py":
                continue
            with self.subTest(file=str(path.relative_to(ROOT))):
                self.assertEqual(literal.findall(path.read_text(encoding="utf-8")), [])

    def test_changelog_has_current_version(self):
        self.assertIn(f"## [{VERSION}]", (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
