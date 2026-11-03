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
import unittest.mock

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
            if ".git" in path.parts or path.name == "_version.py":
                continue
            with self.subTest(file=str(path.relative_to(ROOT))):
                self.assertEqual(literal.findall(path.read_text(encoding="utf-8")), [])

    def test_changelog_has_current_version(self):
        self.assertIn(f"## [{VERSION}]", (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"))


class GitignoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.proj = pathlib.Path(self.tmp.name)
        (self.proj / ".git").mkdir()
        self.gi = self.proj / ".gitignore"

    def run_(self, *extra, tty=None, answer=""):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), unittest.mock.patch("builtins.input", return_value=answer), \
                unittest.mock.patch.object(sys.stdin, "isatty", return_value=bool(tty)):
            install.main(["--platform", "claude", "--project", str(self.proj), *extra])
        return out.getvalue()

    def test_non_tty_prints_only(self):
        out = self.run_()
        self.assertFalse(self.gi.exists())
        self.assertIn(".greenfield-observe/", out)

    def test_flag_twice_one_block(self):
        self.gi.write_text("node_modules")  # no trailing newline
        self.run_("--gitignore")
        self.run_("--gitignore", "--force")
        text = self.gi.read_text()
        self.assertEqual(text.count(install.GITIGNORE_MARK), 1)
        self.assertEqual(text.splitlines()[:2], ["node_modules", install.GITIGNORE_MARK])
        self.assertIn("research/greenfield/", text)

    def test_tty_yes_and_no(self):
        self.run_(tty=True, answer="n")
        self.assertFalse(self.gi.exists())
        self.run_("--force", tty=True, answer="")
        self.assertIn(".greenfield-observe/", self.gi.read_text())

    def test_no_gitignore_flag(self):
        self.run_("--no-gitignore", tty=True)
        self.assertFalse(self.gi.exists())

    def test_variant_forms_present(self):
        self.gi.write_text("/.greenfield-observe\nresearch/greenfield\n")
        self.run_("--gitignore")
        self.assertEqual(self.gi.read_text(), "/.greenfield-observe\nresearch/greenfield\n")

    def test_no_git_or_user_scope_untouched(self):
        (self.proj / ".git").rmdir()
        self.run_("--gitignore")
        self.assertFalse(self.gi.exists())

    def test_symlinked_gitignore_prints_and_continues(self):
        target = self.proj / "real"
        target.write_text("")
        self.gi.symlink_to(target)
        out = self.run_("--gitignore")
        self.assertEqual(target.read_text(), "")
        self.assertIn("Add these lines", out)


if __name__ == "__main__":
    unittest.main()
