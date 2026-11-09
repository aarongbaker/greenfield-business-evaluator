import contextlib
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
import unittest.mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "skill" / "scripts"))
import install
import gf_install
from gf_roles import ROLES
from gf_common import VERSION


def snap(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(pathlib.Path(root).rglob("*")) if p.is_file()}


def run(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        return install.main(list(argv)), out.getvalue()


class InstallTests(unittest.TestCase):
    def test_project_install_adds_guard_unless_opted_out(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(run("--project", d, "--platform", "claude", "--no-gitignore")[0], 0)
            self.assertIn("hook guard", (pathlib.Path(d) / ".claude/settings.local.json").read_text())
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(run("--project", d, "--platform", "claude", "--no-gitignore", "--no-guard")[0], 0)
            self.assertFalse((pathlib.Path(d) / ".claude/settings.local.json").exists())

    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.proj = pathlib.Path(t.name).resolve()
        self.args = ["--platform", "both", "--project", str(self.proj)]
        self.agent = self.proj / ".claude" / "agents" / "gf-market.md"

    def hooks(self, data):
        p = self.proj / ".claude" / "settings.local.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data))
        return p

    def test_dry_run_writes_nothing_and_matches_real_plan(self):
        before = snap(self.proj)
        rc, out = run(*self.args, "--dry-run")
        self.assertEqual((rc, snap(self.proj)), (0, before))
        self.assertIn(str(self.agent), out)
        _, targets = gf_install.plan("both", "project", self.proj, False)
        planned = [a["path"] for a in gf_install.plan_install(targets)]
        run(*self.args, "--no-gitignore")
        self.assertTrue(all(pathlib.Path(p).exists() for p in planned))

    def test_manifest_and_round_trip(self):
        pre = self.proj / "keep.txt"
        pre.write_text("x")
        before = snap(self.proj)
        run(*self.args, "--no-gitignore")
        man = gf_install.read_manifest(self.proj / ".claude/skills/greenfield-business-evaluator")
        self.assertEqual(man["version"], VERSION)
        self.assertEqual(len(man["agents"]), 9)
        self.assertEqual(run("uninstall", *self.args, "--dry-run")[0], 0)
        self.assertTrue(self.agent.exists())
        self.assertEqual(run("uninstall", *self.args, "--yes")[0], 0)
        self.assertEqual(snap(self.proj).keys() - before.keys(), set())
        self.assertFalse((self.proj / ".claude/skills/greenfield-business-evaluator").exists())
        self.assertEqual(run("uninstall", *self.args, "--yes")[0], 0)  # idempotent

    def test_edited_agent_survives_uninstall_and_blocks_force(self):
        run(*self.args, "--no-gitignore")
        self.agent.write_text("mine")
        rc, _ = run(*self.args, "--force")
        self.assertEqual(rc, 2)
        self.assertEqual(self.agent.read_text(), "mine")
        self.assertEqual(run("uninstall", *self.args, "--yes")[0], 0)
        self.assertEqual(self.agent.read_text(), "mine")
        self.assertFalse((self.proj / ".claude/agents/gf-problem.md").exists())

    def test_overwrite_modified_replaces(self):
        run(*self.args, "--no-gitignore")
        self.agent.write_text("mine")
        self.assertEqual(run(*self.args, "--force", "--overwrite-modified", "--no-gitignore")[0], 0)
        self.assertNotEqual(self.agent.read_text(), "mine")

    def test_legacy_uninstall_without_manifest(self):
        run(*self.args, "--no-gitignore")
        (self.proj / ".claude/skills/greenfield-business-evaluator/.greenfield-install.json").write_text("{broken")
        self.assertEqual(run("uninstall", *self.args, "--yes")[0], 0)
        self.assertFalse(self.agent.exists())

    def test_hooks_removed_third_party_and_other_agents_kept(self):
        run(*self.args, "--no-gitignore")
        other = self.proj / ".claude/agents/other.md"
        other.write_text("o")
        cmd = "python3 /x/gf_observe.py hook --project /p --provider claude"
        p = self.hooks({"hooks": {"PostToolUse": [{"hooks": [{"type": "command", "command": cmd}, {"type": "command", "command": "third.sh"}]}]}})
        self.assertEqual(run("uninstall", *self.args, "--yes")[0], 0)
        self.assertEqual(json.loads(p.read_text()), {"hooks": {"PostToolUse": [{"hooks": [{"type": "command", "command": "third.sh"}]}]}})
        self.assertTrue(other.exists())

    def test_keep_hooks(self):
        run(*self.args, "--no-gitignore")
        data = {"hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": "python3 gf_observe.py hook --project /p"}]}]}}
        p = self.hooks(data)
        run("uninstall", *self.args, "--yes", "--keep-hooks")
        self.assertEqual(json.loads(p.read_text()), data)

    def test_user_scope_with_patched_home(self):
        with unittest.mock.patch.dict(os.environ, {"HOME": str(self.proj)}):
            self.assertEqual(run("--scope", "user", "--platform", "claude")[0], 0)
            self.assertTrue(self.agent.exists())
            self.assertEqual(run("uninstall", "--scope", "user", "--platform", "claude", "--yes")[0], 0)
        self.assertFalse(self.agent.exists())

    def test_scope_all_removes_both(self):
        home = self.proj / "home"
        home.mkdir()
        proj = self.proj / "p"
        proj.mkdir()
        with unittest.mock.patch.dict(os.environ, {"HOME": str(home)}):
            run("--scope", "user", "--platform", "claude")
            run("--platform", "claude", "--project", str(proj), "--no-gitignore")
            self.assertEqual(run("uninstall", "--scope", "all", "--platform", "claude", "--project", str(proj), "--yes")[0], 0)
        self.assertEqual(snap(home), {})
        self.assertEqual(snap(proj), {})

    def test_uninstall_oserror_reports_and_continues(self):
        run(*self.args, "--no-gitignore")
        real = pathlib.Path.unlink
        def flaky(self_, missing_ok=False):
            if self_.name == "gf-market.md":
                raise PermissionError("denied")
            return real(self_, missing_ok=missing_ok)
        err = io.StringIO()
        with unittest.mock.patch.object(pathlib.Path, "unlink", flaky), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            rc = install.main(["uninstall", *self.args, "--yes"])
        self.assertEqual(rc, 1)
        self.assertIn("gf-market.md", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())
        self.assertTrue(self.agent.exists())
        self.assertFalse((self.proj / ".claude/agents/gf-problem.md").exists())

    def test_non_tty_needs_yes(self):
        run(*self.args, "--no-gitignore")
        self.assertEqual(run("uninstall", *self.args)[0], 2)
        self.assertTrue(self.agent.exists())

    def test_copy_failure_keeps_previous_install(self):
        run(*self.args, "--no-gitignore")
        skill = self.proj / ".claude/skills/greenfield-business-evaluator"
        before = snap(skill)
        with unittest.mock.patch("shutil.copytree", side_effect=OSError("boom")):
            with self.assertRaises(OSError):
                gf_install.install_skill(skill, True)
        self.assertEqual(snap(skill), before)
        self.assertFalse(skill.with_name(skill.name + ".tmp-stage").exists())

    def test_plan_shape(self):
        _, targets = gf_install.plan("claude", "project", self.proj, False)
        for a in gf_install.plan_install(targets):
            self.assertEqual(set(a), {"op", "path", "reason"})

    def test_plugin_manifests(self):
        d = ROOT / ".claude-plugin"
        plugin = json.loads((d / "plugin.json").read_text())
        market = json.loads((d / "marketplace.json").read_text())
        self.assertEqual(plugin["version"], VERSION)
        self.assertNotIn("hooks", plugin)
        self.assertTrue((ROOT / "skill" / "SKILL.md").is_file())
        self.assertEqual(sorted(plugin["agents"]), sorted(f"./platform/claude/agents/gf-{r.key}.md" for r in ROLES))
        self.assertTrue(all((ROOT / a).is_file() for a in plugin["agents"]))
        self.assertEqual(market["plugins"][0]["name"], plugin["name"])
        self.assertTrue((ROOT / market["plugins"][0]["source"]).is_dir())


if __name__ == "__main__":
    unittest.main()
