"""W27 self-attestation guard: deny/allow table, file-tool payloads, hook install/remove, end-to-end hook command. Temp dirs only."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skill" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import gf_guard  # noqa: E402
import gf_hooks  # noqa: E402
from gf_common import atomic_write_json  # noqa: E402

REC = "greenfield ledger record --ledger l.jsonl --kind paid_test --project-name X --hypothesis H"
DENY = [
    REC + " --attester Jane --artifact r.txt",
    REC + " --attester=Jane",
    "python3 skill/scripts/gf_ledger.py record --ledger l.jsonl --kind paid_test --attester Jane --artifact r.txt",
    "python3 scripts/greenfield.py ledger record --kind source_review --attester Jane",
    "python3 /x/scripts/greenfield.py --json ledger record --attester Jane --kind note",
    "python3 -m greenfield_evaluator ledger record --attester Jane",
    "cd /tmp/proj && " + REC + " --attester Jane",
    "cd proj; " + REC + " --attester Jane",
    "true | " + REC + " --attester Jane",
    "GF_X=1 " + REC + " --attester Jane",
    "env FOO=bar python3 gf_ledger.py record --attester Jane",
    "bash -c '" + REC + " --attester Jane'",
    "sh -lc \"cd p && " + REC + " --attester Jane\"",
    "bash -c \"bash -c '" + REC + " --attester Jane'\"",
    "echo hi\n" + REC + " --attester Jane",
    'echo "greenfield ledger record --attester"',  # documented harmless false positive
    "cat ~/.config/greenfield/attest.key",
    "cp x $GF_CONFIG_DIR/attest.key",
    "rm -rf ~/.config/greenfield",
    "bash -c 'unterminated greenfield ledger record --attester x",  # unparseable and mentions the ledger: fail closed
    # inline code names a signed file inside one quoted token
    "python3 -c \"import json;print(open('source-verification.json').read())\"",
    "python3 -c \"open('research/x/experiment-ledger.jsonl','a').write('x')\"",
    "node -e \"require('fs').readFileSync('materials/raw/w.csv')\"",
    "python3 -c \"open('research/x/receipts/r.txt')\"",
]
ALLOW = [
    "greenfield ledger verify --ledger l.jsonl",
    "greenfield ledger summary",
    "greenfield ledger record --kind hypothesis --project-name X --hypothesis H",
    "python3 gf_ledger.py record --kind hypothesis --hypothesis H",
    "grep attester notes.md",
    "othertool record --attester Jane",
    "othertool --attester Jane --flag",
    "git commit -m 'fix'",
    "greenfield score --json && greenfield ledger verify",
    "ls -la && echo done",
    "bash -c 'greenfield ledger verify'",
    "echo 'unterminated",  # unparseable but never mentions the ledger: fail open
    "python3 -c \"open('my-source-verification.json.bak')\"",  # a different file that only contains the name
    "cat materials/rawdata.csv",
]


class DecideTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = Path(self.tmp.name) / "cfg"
        p = mock.patch.dict(os.environ, {"GF_CONFIG_DIR": str(self.cfg)})
        p.start()
        self.addCleanup(p.stop)

    def test_bash_deny_table(self):
        self.assertGreaterEqual(len(DENY) + len(ALLOW), 25)
        for cmd in DENY:
            reason = gf_guard.decide("Bash", {"command": cmd}, self.tmp.name)
            self.assertTrue(reason, cmd)
        self.assertIn("your own terminal", gf_guard.decide("Bash", {"command": DENY[0]}))
        self.assertIn(DENY[0].split(" --attester")[0], gf_guard.decide("Bash", {"command": DENY[0]}))

    def test_globbed_key_and_ledger_paths_denied(self):
        proj = Path(self.tmp.name)
        self.cfg.mkdir()
        (self.cfg / "attest.key").write_bytes(b"k")
        run = proj / "research" / "x"
        run.mkdir(parents=True)
        (run / "evaluation.json").write_text("{}")
        (run / "experiment-ledger.jsonl").write_text("")
        for cmd in (f"cat {proj}/cf*/att*", "cat $GF_CONFIG_DIR/*", "cat research/*/experiment-led*"):
            self.assertTrue(gf_guard.decide("Bash", {"command": cmd}, proj), cmd)
        for cmd in ("ls research/*", "grep -r foo .", "greenfield ledger verify --ledger research/*/experiment-ledger.jsonl"):
            self.assertIsNone(gf_guard.decide("Bash", {"command": cmd}, proj), cmd)

    def test_bash_allow_table(self):
        for cmd in ALLOW:
            self.assertIsNone(gf_guard.decide("Bash", {"command": cmd}, self.tmp.name), cmd)

    def test_file_tools(self):
        proj = Path(self.tmp.name)
        for tool, key in (("Write", "file_path"), ("Edit", "file_path"), ("MultiEdit", "file_path"), ("NotebookEdit", "notebook_path")):
            for target in ("research/x/experiment-ledger.jsonl", "sub/../research/experiment-ledger.jsonl", str(self.cfg / "attest.key")):
                self.assertTrue(gf_guard.decide(tool, {key: target}, proj), (tool, target))
            self.assertIsNone(gf_guard.decide(tool, {key: "notes.md"}, proj))
            # W60: the assistant drafts into outreach/, so the guard leaves it open; materials/raw/ stays closed to reads
            self.assertIsNone(gf_guard.decide(tool, {key: "research/greenfield/x/outreach/EXP-1/prospects.csv"}, proj))
        self.assertIsNone(gf_guard.decide("Read", {"file_path": "research/greenfield/x/outreach/EXP-1/prospects.csv"}, proj))
        self.assertTrue(gf_guard.decide("Read", {"file_path": "research/greenfield/x/materials/raw/waitlist.csv"}, proj))

    def test_symlink_into_config_dir_is_caught(self):
        self.cfg.mkdir()
        link = Path(self.tmp.name) / "innocent.txt"
        link.symlink_to(self.cfg / "attest.key")
        self.assertTrue(gf_guard.decide("Write", {"file_path": str(link)}, self.tmp.name))

    def test_ledger_named_by_active_evaluation(self):
        proj = Path(self.tmp.name)
        env = {**os.environ, "GREENFIELD_NO_DEPRECATION": "1"}
        r = subprocess.run([sys.executable, str(SCRIPTS / "greenfield.py"), "--project", str(proj), "start", "--idea", "t", "--json"],
                           capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        folder = Path(json.loads(r.stdout)["research_dir"]) if Path(json.loads(r.stdout)["research_dir"]).is_absolute() else proj / json.loads(r.stdout)["research_dir"]
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "evaluation.json").write_text(json.dumps({"evidence_ledger": "custom-name.jsonl"}))
        self.assertTrue(gf_guard.decide("Write", {"file_path": str(folder / "custom-name.jsonl")}, proj))

    def test_unknown_payloads_allow(self):
        for tool, inp in (("Read", {"file_path": "x"}), ("Bash", {}), ("Bash", None), ("Write", {}), ("WebFetch", {"url": "u"})):
            self.assertIsNone(gf_guard.decide(tool, inp))

    def test_guard_response_shape_for_both_hosts(self):
        for host in ("claude", "codex"):
            raw = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": DENY[0]}, "cwd": self.tmp.name}
            out = gf_guard.guard_response(raw, self.tmp.name)["hookSpecificOutput"]
            self.assertEqual((out["hookEventName"], out["permissionDecision"]), ("PreToolUse", "deny"), host)
        self.assertIsNone(gf_guard.guard_response({"hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_input": {"command": DENY[0]}}))
        self.assertIsNone(gf_guard.guard_response("junk"))


class HookInstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.proj = Path(self.tmp.name)
        for base in (".claude", ".agents"):
            d = self.proj / base / "skills" / gf_hooks.NAME / "scripts"
            d.mkdir(parents=True)
            (d / "gf_observe.py").write_text("")
            (d / "greenfield.py").write_text(f"import runpy, sys; sys.path.insert(0, {str(SCRIPTS)!r}); runpy.run_path({str(SCRIPTS / 'greenfield.py')!r}, run_name='__main__')\n")
        self.other = {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "echo mine"}]}], "Stop": [{"hooks": [{"type": "command", "command": "afplay x"}]}]}, "model": "x"}
        for name in ("claude", "codex"):
            path = gf_hooks.path_for(self.proj, name)
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(path, self.other)
        self.before = {n: gf_hooks.path_for(self.proj, n).read_bytes() for n in ("claude", "codex")}

    def cmds(self, name):
        data = json.loads(gf_hooks.path_for(self.proj, name).read_text())
        return [h["command"] for g in data["hooks"].get("PreToolUse", []) for h in g["hooks"]]

    def test_install_guard_only_then_remove_is_byte_identical(self):
        gf_hooks.configure("install", self.proj, "both", guard=True, observe=False)
        for n in ("claude", "codex"):
            cmds = self.cmds(n)
            self.assertEqual(sum("hook guard --project" in c for c in cmds), 1, n)
            self.assertFalse(any("gf_observe.py" in c for c in cmds), n)
            self.assertIn("echo mine", cmds)
        gf_hooks.configure("install", self.proj, "both", guard=True, observe=False)  # idempotent
        self.assertEqual(sum("hook guard" in c for c in self.cmds("claude")), 1)
        gf_hooks.configure("remove", self.proj, "both")
        self.assertEqual(self.before, {n: gf_hooks.path_for(self.proj, n).read_bytes() for n in ("claude", "codex")})

    def test_full_install_has_both_and_guard_only_keeps_observability(self):
        gf_hooks.configure("install", self.proj, "claude", guard=True)
        cmds = self.cmds("claude")
        self.assertTrue(any("gf_observe.py" in c for c in cmds) and any("hook guard" in c for c in cmds))
        gf_hooks.configure("install", self.proj, "claude", guard=True, observe=False)
        self.assertTrue(any("gf_observe.py" in c for c in self.cmds("claude")))
        gf_hooks.configure("remove", self.proj, "both")
        self.assertEqual(self.before["claude"], gf_hooks.path_for(self.proj, "claude").read_bytes())

    def test_plain_install_without_guard_leaves_guard_alone(self):
        gf_hooks.configure("install", self.proj, "claude", guard=True, observe=False)
        gf_hooks.configure("install", self.proj, "claude")
        self.assertTrue(any("hook guard" in c for c in self.cmds("claude")))

    def test_installed_command_denies_end_to_end(self):
        gf_hooks.configure("install", self.proj, "claude", guard=True, observe=False)
        cmd = next(c for c in self.cmds("claude") if "hook guard" in c)
        env = {**os.environ, "GF_CONFIG_DIR": str(self.proj / "cfg")}
        run = lambda command: subprocess.run(cmd, shell=True, input=json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command}}),
                                             capture_output=True, text=True, env=env, timeout=60)
        denied = run(DENY[0])
        self.assertEqual(denied.returncode, 0)
        self.assertEqual(json.loads(denied.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")
        ok = run("greenfield ledger verify")
        self.assertEqual((ok.returncode, ok.stdout), (0, ""))
        bad = subprocess.run(cmd, shell=True, input="not json", capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual((bad.returncode, bad.stdout), (0, ""))  # fails open


if __name__ == "__main__":
    unittest.main()
