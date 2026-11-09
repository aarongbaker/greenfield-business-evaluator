"""W23: greenfield doctor and profiles. Temp dirs and a patched HOME/GF_CONFIG_DIR only; never the real ~/.claude or ~/.config."""
import contextlib
import io
import json
import os
import shlex
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skill" / "scripts"))
import cli  # noqa: E402
import gf_doctor  # noqa: E402
import gf_hooks  # noqa: E402
import gf_install  # noqa: E402
import gf_ledger  # noqa: E402
import gf_platform  # noqa: E402
import gf_profiles  # noqa: E402


def gf(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class DoctorCase(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.home = Path(t.name).resolve() / "home"
        self.proj = Path(t.name).resolve() / "proj"
        self.home.mkdir()
        self.proj.mkdir()
        for p in (mock.patch.dict(os.environ, {"HOME": str(self.home), "GF_CONFIG_DIR": str(self.home / "cfg")}),
                  mock.patch("shutil.which", return_value=None)):
            p.start()
            self.addCleanup(p.stop)
        os.environ.pop("GF_ATTEST_KEY_FILE", None)

    def checks(self, **kw):
        return {r["id"]: r for r in gf_doctor.run_checks(self.proj, **kw)}

    def install(self, hooks=False):
        base, targets = gf_install.plan("both", "project", self.proj, False)
        gf_install.install(targets, False)
        if hooks:
            gf_hooks.configure("install", self.proj, "both", guard=True)

    def status(self, id, **kw):
        return self.checks(**kw)[id]["status"]


class Rows(DoctorCase):
    def test_every_fix_is_nonempty_when_not_passing(self):
        for r in gf_doctor.run_checks(self.proj):
            if r["status"] in ("fail", "warn"):
                self.assertTrue(r["fix"], r["id"])

    def test_python_too_old(self):
        with mock.patch.object(gf_doctor.sys, "version_info", (3, 10, 0)):
            r = self.checks()["environment.python"]
        self.assertEqual((r["status"], bool(r["fix"])), ("fail", True))

    def test_windows_platform_exit_3_and_doctor_still_runs(self):
        with mock.patch.object(gf_platform, "HAS_FCNTL", False), mock.patch.object(gf_doctor.sys, "platform", "win32"):
            code, out, _ = gf("--json", "--project", str(self.proj), "doctor")
        d = json.loads(out)
        self.assertEqual((code, d["summary"]["exit_code"]), (3, 3))
        self.assertIn("WSL", next(c for c in d["checks"] if c["id"] == "environment.platform")["fix"])

    def test_shadowing_binary_with_other_version(self):
        done = subprocess.CompletedProcess([], 0, stdout="greenfield 0.0.1\n")
        with mock.patch("shutil.which", return_value="/x/greenfield"), mock.patch("subprocess.run", return_value=done):
            self.assertEqual(self.status("environment.which"), "warn")

    def test_install_missing_then_present_intact(self):
        self.assertEqual(self.status("install.present"), "fail")
        self.install()
        c = self.checks()
        self.assertEqual([c[k]["status"] for k in ("install.present", "install.intact", "install.shadowing", "install.agents")], ["pass"] * 4)

    def test_edited_install_file_fails_intact(self):
        self.install()
        (self.proj / ".claude/skills/greenfield-business-evaluator/SKILL.md").write_text("edited")
        self.assertEqual(self.status("install.intact"), "fail")

    def test_missing_and_stale_agent_roles(self):
        self.install()
        agents = self.proj / ".claude/agents"
        (agents / "gf-market.md").write_text("old")
        self.assertEqual(self.status("install.agents"), "warn")
        (agents / "gf-market.md").unlink()
        self.assertEqual(self.status("install.agents"), "fail")

    def test_shadowing_user_and_project_versions(self):
        self.install()
        user = self.home / ".claude/skills/greenfield-business-evaluator"
        user.mkdir(parents=True)
        (user / ".greenfield-version").write_text("0.0.1\n")
        r = self.checks()["install.shadowing"]
        self.assertEqual(r["status"], "warn")
        self.assertIn("uninstall", r["fix"])

    def hook_file(self, data):
        p = self.proj / ".claude/settings.local.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data))

    def test_hooks_absent_is_info(self):
        self.assertEqual(self.status("hooks.configured"), "info")

    def test_hooks_installed_pass(self):
        self.install(hooks=True)
        c = self.checks()
        self.assertEqual([c[k]["status"] for k in ("hooks.configured", "hooks.script_path", "hooks.guard", "hooks.stale_posttooluse")], ["pass"] * 4)

    def test_hook_script_path_missing(self):
        cmd = f"python3 {self.proj}/gone/gf_observe.py hook --project {self.proj} --provider claude"
        self.hook_file({"hooks": {"SubagentStart": [{"hooks": [{"type": "command", "command": cmd}]}]}})
        c = self.checks()
        self.assertEqual((c["hooks.script_path"]["status"], c["hooks.guard"]["status"]), ("fail", "warn"))

    def test_stale_posttooluse_fixed_by_hooks_install(self):
        self.install(hooks=True)
        p = self.proj / ".claude/settings.local.json"
        data = json.loads(p.read_text())
        data["hooks"]["PostToolUse"] = [{"hooks": [{"type": "command", "command": f"python3 {gf_hooks.script_for(self.proj, 'claude')} hook --project {self.proj} --provider claude"}]}]
        p.write_text(json.dumps(data))
        r = self.checks()["hooks.stale_posttooluse"]
        self.assertEqual(r["status"], "warn")
        self.assertEqual(r["fix"].split()[:3], ["greenfield", "hooks", "install"])
        self.assertEqual(gf("--project", str(self.proj), "hooks", "install")[0], 0)
        self.assertNotIn("PostToolUse", json.loads(p.read_text())["hooks"])
        self.assertEqual(self.status("hooks.stale_posttooluse"), "pass")

    def test_loose_permissions_fixed(self):
        d = self.proj / ".greenfield-observe"
        d.mkdir(mode=0o755)
        d.chmod(0o755)
        (d / "x.json").write_text("{}")
        self.assertEqual(self.status("privacy.permissions"), "fail")
        gf_doctor.apply_fixes(self.proj, gf_doctor.run_checks(self.proj))
        self.assertEqual(self.status("privacy.permissions"), "pass")

    def test_ignore_lines_missing_then_idempotent_fix(self):
        self.assertEqual(self.status("privacy.ignored"), "fail")
        self.assertTrue(gf_doctor.apply_fixes(self.proj, gf_doctor.run_checks(self.proj)))
        self.assertEqual(self.status("privacy.ignored"), "pass")
        before = (self.proj / ".gitignore").read_text()
        self.assertEqual(gf_doctor.apply_fixes(self.proj, gf_doctor.run_checks(self.proj)), [])
        self.assertEqual((self.proj / ".gitignore").read_text(), before)

    def test_fix_on_read_only_gitignore_reports_not_crashes(self):
        with mock.patch.object(Path, "write_text", side_effect=OSError(30, "Read-only file system")):
            done = gf_doctor.apply_fixes(self.proj, gf_doctor.run_checks(self.proj))
        self.assertIn("could not update .gitignore", done[0])

    def test_tracked_private_files_fail_and_fix_is_not_run(self):
        git = lambda *a: subprocess.run(["git", "-C", str(self.proj), *a], capture_output=True, check=True, timeout=30)
        try:
            git("init", "-q")
        except (OSError, subprocess.CalledProcessError):
            self.skipTest("git unavailable")
        (self.proj / ".gitignore").write_text(".greenfield-observe/\nresearch/greenfield/\n")
        (self.proj / "research/greenfield").mkdir(parents=True)
        (self.proj / "research/greenfield/a.md").write_text("secret")
        git("add", "-f", "research/greenfield/a.md")
        with mock.patch("shutil.which", side_effect=lambda n: "/usr/bin/git" if n == "git" else None):
            r = self.checks()["privacy.ignored"]
        self.assertEqual(r["status"], "fail")
        self.assertIn("git rm -r --cached", r["fix"])
        self.assertEqual(gf_doctor.apply_fixes(self.proj, [r]), [])

    def run_files(self, ledger_lines=(), evaluation=None):
        gf("--project", str(self.proj), "start", "--idea", "Test idea", "--no-plan")
        ctx = __import__("gf_context").run_context(self.proj)
        ctx["research_dir"].mkdir(parents=True, exist_ok=True)
        if ledger_lines:
            ctx["ledger"].write_text("\n".join(ledger_lines) + "\n")
        if evaluation is not None:
            ctx["evaluation"].write_text(evaluation)
        return ctx

    def test_legacy_absolute_receipt_warns(self):
        ctx = self.run_files()
        gf_ledger.ensure_key()
        art = ctx["research_dir"] / "a.txt"
        art.write_text("x")
        gf_ledger._write(ctx["ledger"], {"observed_at": "2026-01-01", "kind": "note", "project": "P", "hypothesis": "H", "outcome": "", "notes": "",
                                              "attester": "", "human_attested": False, "artifact": {"path": str(art), "sha256": "0" * 64, "bytes": 1},
                                              "pillar_ids": [], "claim_id": "", "experiment_id": ""}, gf_ledger.load_key())
        r = self.checks()["attestation.legacy_receipts"]
        self.assertEqual(r["status"], "warn")
        self.assertIn("evidence add", r["fix"])

    def test_hmac_key_missing_then_loose_then_ok(self):
        self.assertEqual(self.status("attestation.hmac_key"), "warn")
        path, _ = gf_ledger.ensure_key()
        self.assertEqual(self.status("attestation.hmac_key"), "pass")
        path.chmod(0o644)
        r = self.checks()["attestation.hmac_key"]
        self.assertEqual(r["status"], "fail")
        self.assertTrue(r["fix"].startswith("chmod 600"))

    def test_active_run_broken(self):
        d = self.proj / ".greenfield-observe"
        d.mkdir()
        (d / "active.json").write_text("{not json")
        r = self.checks()["run.active"]
        self.assertEqual((r["status"], r["fix"]), ("fail", "greenfield start --new"))

    def test_evaluation_readiness_lists_what_is_missing(self):
        self.run_files(evaluation="{}")
        r = self.checks()["run.readiness"]
        self.assertEqual(r["status"], "warn")
        self.assertIn("greenfield score", r["fix"])

    def test_ledger_chain_broken(self):
        self.run_files(ledger_lines=['{"seq": 1, "previous_hash": "GENESIS", "hash": "bad"}'])
        r = self.checks()["run.ledger"]
        self.assertEqual(r["status"], "fail")
        self.assertIn("line 1", r["detail"])
        self.assertTrue(r["fix"])

    def test_no_socket_without_network_and_fast(self):
        self.install(hooks=True)
        start = time.monotonic()
        with mock.patch.object(socket, "socket", side_effect=AssertionError("socket opened")), \
                mock.patch.object(socket, "create_connection", side_effect=AssertionError("socket opened")):
            self.assertIn(gf("--json", "--project", str(self.proj), "doctor")[0], (0, 1))
        self.assertLess(time.monotonic() - start, 2)

    def test_network_flag_checks_port_and_host(self):
        busy = mock.MagicMock()
        busy.__enter__.return_value.connect_ex.return_value = 0
        with mock.patch.object(socket, "socket", return_value=busy), mock.patch.object(socket, "create_connection", side_effect=OSError("offline")):
            c = self.checks(network=True)
        self.assertEqual((c["dashboard.port"]["status"], c["network.reachability"]["status"]), ("warn", "warn"))
        self.assertIn("--port 8766", c["dashboard.port"]["fix"])


class Loop(DoctorCase):
    def test_empty_project_fix_commands_reach_exit_0(self):
        code, out, _ = gf("--json", "--project", str(self.proj), "doctor")
        self.assertEqual(code, 1)
        fails = [r for r in json.loads(out)["checks"] if r["status"] == "fail"]
        self.assertTrue(fails and all(r["fix"] for r in fails))
        for r in fails:
            argv = shlex.split(r["fix"])
            self.assertEqual(argv[0], "greenfield", r)
            self.assertIn(gf("--project", str(self.proj), *argv[1:])[0], (0,), r["fix"])
        code, out, _ = gf("--json", "--project", str(self.proj), "doctor")
        self.assertEqual(code, 0, [r for r in json.loads(out)["checks"] if r["status"] == "fail"])

    def test_fix_flag_is_idempotent(self):
        gf("--project", str(self.proj), "doctor", "--fix")
        first = (self.proj / ".gitignore").read_text()
        code, out, _ = gf("--json", "--project", str(self.proj), "doctor", "--fix")
        self.assertEqual(json.loads(out)["fixed"], [])
        self.assertEqual((self.proj / ".gitignore").read_text(), first)

    def test_text_report_has_markers_summary_and_fix(self):
        code, out, _ = gf("--project", str(self.proj), "doctor", "--no-color")
        # not a TTY here, so force the text view through --json absence check below
        self.assertEqual(code, 1)
        text = gf_doctor._text(json.loads(out), None)
        self.assertIn("[FAIL]", text)
        self.assertIn("fix: greenfield install --platform both", text)
        self.assertRegex(text, r"\d+ problems?, \d+ warnings?\. Run the fix commands above\.")


class Profiles(unittest.TestCase):
    def test_every_gate_has_help_and_every_profile_a_use_when(self):
        gates = {g for p in gf_profiles.PROFILES.values() for g in p["pilot_gates"]}
        self.assertEqual(len(gates), 17)
        self.assertEqual(gates, set(gf_profiles.GATE_HELP))
        self.assertEqual(set(gf_profiles.USE_WHEN), set(gf_profiles.PROFILES))

    def test_list_show_compare_json_round_trip(self):
        code, out, _ = gf("--json", "profiles")
        rows = json.loads(out)["profiles"]
        self.assertEqual([r["name"] for r in rows], list(gf_profiles.PROFILES))
        for name, p in gf_profiles.PROFILES.items():
            code, out, _ = gf("--json", "profiles", "show", name)
            d = json.loads(out)
            self.assertEqual((code, d["weights"], [g["id"] for g in d["pilot_gates"]], d["questions"]), (0, p["weights"], p["pilot_gates"], p["questions"]))
            self.assertTrue(all(g["description"] and g["evidence_example"] for g in d["pilot_gates"]))
        d = json.loads(gf("--json", "profiles", "compare", "bootstrapped_saas", "venture_startup")[1])
        self.assertEqual(next(r for r in d["rows"] if r["pillar"] == "market")["diff"], 13)

    def test_text_views_and_unknown_name(self):
        self.assertIn("delivery_margin", gf_profiles._text(gf_profiles.describe("bootstrapped_saas"), None))
        self.assertIn("gates", gf_profiles._text({"profiles": gf_profiles.summary()}, None))
        code, _, err = gf("profiles", "show", "nope")
        self.assertEqual(code, 2)
        self.assertIn("unknown profile", err)


if __name__ == "__main__":
    unittest.main()
