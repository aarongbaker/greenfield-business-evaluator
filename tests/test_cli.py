"""The `greenfield` command: help, --json, global flags, old-script parity, exit codes, run-id and active-run guards (W22)."""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skill" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import cli  # noqa: E402
import completion  # noqa: E402
from gf_common import VERSION  # noqa: E402
from test_v2 import BUDGET, portfolio_item  # noqa: E402

GF = [sys.executable, str(SCRIPTS / "greenfield.py")]
FIXTURE = ROOT / "tests" / "fixtures" / "validate-before-build.json"
TEMPLATE = ROOT / "skill" / "assets" / "evaluation-template.json"
ENV = {k: v for k, v in os.environ.items() if k != "GREENFIELD_NO_DEPRECATION"}


def gf(*args, cwd=None, input=""):
    return subprocess.run(GF + list(args), capture_output=True, text=True, cwd=cwd, input=input, env=ENV, timeout=60)


def tree(folder):
    return sorted(str(p.relative_to(folder)) for p in Path(folder).rglob("*"))


def commands(parser, prefix=()):
    """Every command path in the parser tree, hidden ones included."""
    for action in parser._actions:
        if hasattr(action, "choices") and isinstance(action.choices, dict):
            for name, sub in action.choices.items():
                yield (*prefix, name)
                yield from commands(sub, (*prefix, name))


class HelpTests(unittest.TestCase):
    def test_every_command_has_help_with_an_example(self):
        for path in commands(cli.build_parser()):
            with self.subTest(command=" ".join(path)), contextlib.redirect_stdout(io.StringIO()) as out:
                with self.assertRaises(SystemExit) as ex:
                    cli.main([*path, "--help"])
                self.assertEqual(ex.exception.code, 0)
                self.assertIn("examples:\n  greenfield", out.getvalue())

    def test_every_argument_has_help(self):
        def walk(parser, name):
            for a in parser._actions:
                if a.dest not in ("help", "version") and not hasattr(a.choices, "items"):
                    self.assertTrue(a.help, f"{name}: {a.dest}")
                for n, sub in (a.choices.items() if hasattr(a.choices, "items") else ()):
                    walk(sub, f"{name} {n}")
        walk(cli.build_parser(), "greenfield")

    def test_version_and_typo(self):
        self.assertEqual(gf("--version").stdout.strip(), f"greenfield {VERSION}")
        r = gf("scroe", "x.json")
        self.assertEqual(r.returncode, 2)
        self.assertIn("Did you mean 'score'?", r.stderr)

    def test_completion_scripts(self):
        words = completion.table(cli.build_parser())
        self.assertIn("score", words[""])
        self.assertNotIn("hook", words[""])  # hidden commands stay out
        self.assertIn("--role", words["task claim"])
        for shell in ("bash", "zsh", "fish"):
            with self.subTest(shell=shell):
                r = gf("completion", shell)  # piped, but still the raw script
                self.assertEqual(r.returncode, 0)
                self.assertIn("greenfield", r.stdout)
                self.assertFalse(r.stdout.startswith('"'))


class JsonEverywhereTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.p = Path(self.tmp.name)
        (self.p / "research").mkdir()
        shutil.copy(FIXTURE, self.p / "evaluation.json")
        (self.p / "art.md").write_text("findings\n")

    def ok(self, *args, input=""):
        r = gf("--json", "--project", str(self.p), *args, input=input)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_every_non_serving_command_prints_json(self):
        p = str(self.p)
        self.assertTrue(self.ok("install", "--no-gitignore")["installed"])
        self.assertEqual(len(self.ok("hooks", "install")["settings"]), 2)
        self.ok("hooks", "remove")
        rid = self.ok("start", "--idea", "Test idea", "--no-plan")["run_id"]
        self.assertEqual(self.ok("link", "--research-dir", "research")["research_dir"], "research")
        self.ok("task", "plan")
        self.ok("task", "claim", "--role", "gf-market")
        self.ok("task", "complete", "--role", "gf-market", "--artifact", f"{p}/art.md")
        self.ok("task", "claim", "--role", "gf-value")
        self.ok("task", "fail", "--role", "gf-value", "--reason", "no web")
        self.ok("task", "resume")
        self.ok("task", "set-rate", "--usd-per-million-tokens", "5")
        self.ok("task", "coverage", "--evaluation", f"{p}/evaluation.json")
        status = self.ok("status")
        self.assertEqual(status["run_id"], rid)
        self.assertEqual(status["tasks"]["tasks"]["gf-market"], "completed")
        self.assertIn("state", status["decision"])
        self.assertTrue(self.ok("event", "emit", "--event", "note", "--message", "hi")["id"])
        self.assertEqual(self.ok("ingest-codex", input="")["captured"], 0)
        self.assertFalse(self.ok("demo", "--new")["activated"])  # never displaces the real run
        self.assertIn("decision", self.ok("score", f"{p}/evaluation.json"))
        self.assertIn("total_sources", self.ok("sources", "check", f"{p}/evaluation.json", "--output", f"{p}/src.json"))
        ledger = f"{p}/ledger.jsonl"
        self.ok("ledger", "record", "--ledger", ledger, "--kind", "hypothesis", "--project-name", "X", "--hypothesis", "H")
        self.assertEqual(self.ok("ledger", "verify", "--ledger", ledger)["events"], 1)
        self.ok("ledger", "summary", "--ledger", ledger)
        items = [portfolio_item(self.p, "A"), portfolio_item(self.p, "B")]
        (self.p / "portfolio.json").write_text(json.dumps({"constraints": BUDGET, "opportunities": items}))
        self.assertEqual(self.ok("portfolio", f"{p}/portfolio.json", "--output", f"{p}/rank.json")["opportunities"], 2)
        self.assertIn("complete -F", self.ok("completion", "bash"))

    def test_global_flags_in_either_position(self):
        gf("--project", str(self.p), "start", "--idea", "Test idea")
        before = gf("--json", "--project", str(self.p), "status")
        after = gf("status", "--json", "--project", str(self.p))
        self.assertEqual(before.returncode, 0, before.stderr)
        self.assertEqual(before.stdout, after.stdout)
        a = gf("--json", "score", str(FIXTURE)).stdout
        self.assertEqual(a, gf("score", str(FIXTURE), "--json").stdout)

    def test_json_error_shape(self):
        r = gf("--json", "score", str(self.p / "missing.json"))
        self.assertEqual(r.returncode, 2)
        self.assertEqual(r.stdout, "")
        err = json.loads(r.stderr)["error"]
        self.assertEqual(set(err), {"code", "message", "path", "next"})


class OldScriptTests(unittest.TestCase):
    def test_old_scorer_same_stdout_and_hint_on_stderr(self):
        for path in (TEMPLATE, FIXTURE):
            with self.subTest(path=path.name):
                old = subprocess.run([sys.executable, str(SCRIPTS / "score_project.py"), str(path), "--json"], capture_output=True, text=True, env=ENV, timeout=60)
                new = gf("score", str(path), "--json")
                if old.returncode == 0:
                    self.assertEqual(old.stdout, new.stdout)
                self.assertEqual(old.returncode, new.returncode)
                self.assertIn("note: score_project.py is now 'greenfield score'", old.stderr)
                self.assertNotIn("note:", old.stdout + new.stderr)

    def test_hint_silenced_and_absent_from_hooks(self):
        r = subprocess.run([sys.executable, str(SCRIPTS / "score_project.py"), str(FIXTURE)], capture_output=True, text=True,
                           env={**ENV, "GREENFIELD_NO_DEPRECATION": "1"}, timeout=60)
        self.assertNotIn("note:", r.stderr)
        with tempfile.TemporaryDirectory() as d:
            r = subprocess.run([sys.executable, str(SCRIPTS / "gf_observe.py"), "hook", "--project", d, "--provider", "claude"],
                               input="{}", capture_output=True, text=True, env=ENV, timeout=60)
        self.assertEqual(r.stderr, "")


class ExitCodeTests(unittest.TestCase):
    def test_codes(self):
        with tempfile.TemporaryDirectory() as d:
            ledger = Path(d) / "ledger.jsonl"
            ledger.write_text('{"seq": 1}\n')
            self.assertEqual(gf("ledger", "verify", "--ledger", str(ledger)).returncode, 1)
            self.assertEqual(gf("--project", d, "hooks", "install").returncode, 3)  # skill not installed
            for bad in (str(ledger), str(Path(d) / "missing")):
                r = gf("--project", bad, "status")
                self.assertEqual(r.returncode, 2)
                self.assertIn(bad, r.stderr)
                self.assertNotIn("Traceback", r.stderr)

    def test_ctrl_c_on_dashboard(self):
        with tempfile.TemporaryDirectory() as d:
            p = subprocess.Popen(GF + ["--json", "--project", d, "dashboard", "--port", "0"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                self.assertIn("url", json.loads(p.stdout.readline()))
                p.send_signal(signal.SIGINT)
                _, err = p.communicate(timeout=30)
            finally:
                p.kill()
            self.assertEqual(p.returncode, 130)
            self.assertNotIn("Traceback", err)

    def test_closed_pipe_is_quiet(self):
        with subprocess.Popen(GF + ["score", str(FIXTURE)], stdout=subprocess.PIPE, stderr=subprocess.PIPE) as p:
            p.stdout.close()  # like `| head -1` exiting before the write
            err = p.stderr.read().decode()
        self.assertNotIn("BrokenPipeError", err)
        self.assertNotIn("Traceback", err)


RUN_COMMANDS = [["status"], ["link", "--research-dir", "."], ["task", "plan"], ["task", "claim", "--role", "gf-market"],
                ["task", "complete", "--role", "gf-market", "--artifact", "x"], ["task", "fail", "--role", "gf-market", "--reason", "x"],
                ["task", "resume"], ["task", "coverage", "--evaluation", "x"], ["task", "set-rate", "--usd-per-million-tokens", "1"],
                ["event", "emit", "--event", "note"], ["ingest-codex"]]


class RunGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.top = Path(self.tmp.name)
        self.p = self.top / "a" / "b" / "proj"
        self.p.mkdir(parents=True)

    def test_bad_run_ids_exit_2_and_write_nothing(self):  # A8
        for run in ("../../escaped", "/tmp/abs", "", "a/b"):
            for cmd in RUN_COMMANDS:
                with self.subTest(run=run, cmd=cmd[:2]):
                    before = tree(self.top)
                    r = gf("--project", str(self.p), *cmd, "--run", run)
                    self.assertEqual(r.returncode, 2, r.stderr)
                    self.assertNotIn("Traceback", r.stderr)
                    self.assertEqual(tree(self.top), before)

    def test_bad_active_json_is_ignored(self):
        (self.p / ".greenfield-observe").mkdir()
        (self.p / ".greenfield-observe" / "active.json").write_text('{"run_id": "../x"}')
        r = gf("--project", str(self.p), "status")
        self.assertEqual(r.returncode, 2)
        self.assertIn("No active run", r.stderr)

    def test_demo_run_never_writes_into_the_bundled_files(self):
        demo = ROOT / "skill" / "assets" / "demo-research"
        before = {str(p.relative_to(demo)): p.read_bytes() for p in demo.rglob('*') if p.is_file()}
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(gf("demo", cwd=d).returncode, 0)
            self.assertEqual(gf("score", cwd=d).returncode, 0)  # scored, not saved
            for args in (("plan", "--add-experiments"), ("evidence", "assessed", "problem"), ("sources", "check")):
                r = gf(*args, cwd=d)
                self.assertEqual(r.returncode, 2, args)
                self.assertIn("reserved for the bundled demo", r.stderr)
        self.assertEqual({str(p.relative_to(demo)): p.read_bytes() for p in demo.rglob('*') if p.is_file()}, before)

    def test_start_and_demo_refuse_while_a_run_is_active(self):  # A9
        rid = json.loads(gf("--json", "--project", str(self.p), "start", "--idea", "Real").stdout)["run_id"]
        active = self.p / ".greenfield-observe" / "active.json"
        before = active.read_bytes()
        for cmd in (["start", "--idea", "Other"], ["demo"]):
            with self.subTest(cmd=cmd[0]):
                r = gf("--project", str(self.p), *cmd)
                self.assertEqual(r.returncode, 2)
                self.assertIn(rid, r.stderr)
                self.assertEqual(active.read_bytes(), before)


class ScaffoldTests(unittest.TestCase):
    """W24: start scaffolds the run; later commands find it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.p = Path(self.tmp.name)

    def run_gf(self, *args, code=0):
        r = gf("--json", "--project", str(self.p), *args)
        self.assertEqual(r.returncode, code, r.stderr)
        return json.loads(r.stdout if code == 0 else r.stderr)

    def test_slug_table(self):
        import gf_observe
        long = "word " * 40
        for idea, want in (("AI bookkeeping for dentists", "ai-bookkeeping-for-dentists"), ("  Hello,   World!! ", "hello-world"),
                           ("Café Ünïcode", "cafe-unicode"), ("日本語のアイデア", "idea-20261103"), ("🚀🚀", "idea-20261103"),
                           ("the and of", "the-and-of")):
            self.assertEqual(gf_observe.slugify(idea, "2026-11-03"), want, idea)
        s = gf_observe.slugify(long, "2026-11-03")
        self.assertTrue(len(s) <= 48 and s.endswith("word") and gf_observe.SLUG_RE.match(s), s)

    def test_start_then_score_defaults_to_the_run(self):
        out = self.run_gf("start", "--idea", "AI bookkeeping for dentists", "--model", "services", "--as-of", "2026-11-03")
        folder = self.p / out["research_dir"]
        self.assertEqual(out["research_dir"], "research/greenfield/ai-bookkeeping-for-dentists")
        data = json.loads((folder / "evaluation.json").read_text())
        self.assertEqual((data["as_of"], data["project"]["business_model"], data["execution"]["mode"]), ("2026-11-03", "services", "not_started"))
        self.assertTrue((folder / "specialists").is_dir())
        self.assertEqual(data["evidence_ledger"], "experiment-ledger.jsonl")
        self.assertEqual(self.run_gf("score")["decision"], "RESEARCH_INCOMPLETE")
        self.assertEqual(json.loads((folder / "decision.json").read_text())["decision"], "RESEARCH_INCOMPLETE")
        self.assertTrue(self.run_gf("status")["research_dir"].endswith("ai-bookkeeping-for-dentists"))
        self.run_gf("ledger", "record", "--kind", "hypothesis", "--project-name", "X", "--hypothesis", "H")
        self.assertTrue((folder / "experiment-ledger.jsonl").exists())
        self.run_gf("ledger", "verify")

    def test_start_stores_depth_and_gives_both_platforms_the_same_hint(self):  # W54
        out = self.run_gf("start", "--idea", "x idea", "--depth", "deep", "--no-plan")
        self.assertEqual(json.loads((self.p / out["evaluation"]).read_text())["execution"]["depth"], "deep")
        claude, codex = (n.split("greenfield-business-evaluator ", 1)[1] for n in out["next"][:2])
        self.assertEqual(claude, codex)
        self.assertIn("research folder: research/greenfield/x-idea", claude)

    def test_start_asks_for_a_profile_on_a_terminal(self):  # W54
        args = cli.build_parser().parse_args(["--project", str(self.p), "start", "--idea", "y idea", "--no-plan"])
        with contextlib.redirect_stderr(io.StringIO()), mock.patch("sys.stdin.isatty", return_value=True), \
                mock.patch("sys.stderr.isatty", return_value=True), mock.patch("builtins.input", side_effect=["nope", "services"]):
            out = cli.h_start(args)
        self.assertEqual(json.loads((self.p / out["evaluation"]).read_text())["project"]["business_model"], "services")
        out = self.run_gf("start", "--idea", "z idea", "--new", "--no-plan")  # piped: no question, general
        self.assertEqual(json.loads((self.p / out["evaluation"]).read_text())["project"]["business_model"], "general")

    def test_default_today_and_no_plan(self):
        import datetime as dt
        out = self.run_gf("start", "--idea", "x idea", "--no-plan")
        self.assertEqual(json.loads((self.p / out["evaluation"]).read_text())["as_of"], dt.date.today().isoformat())
        self.assertFalse(list((self.p / ".greenfield-observe").rglob("tasks*")))

    def test_second_start_refused_and_never_overwrites(self):
        self.run_gf("start", "--idea", "same idea")
        before = tree(self.p)
        self.assertEqual(self.run_gf("start", "--idea", "same idea", code=2)["error"]["code"], "invalid_input")
        self.assertEqual(tree(self.p), before)
        ev = self.p / "research/greenfield/same-idea/evaluation.json"
        ev.write_text('{"mine": 1}')
        self.run_gf("start", "--idea", "same idea", "--new", code=2)
        self.assertEqual(ev.read_text(), '{"mine": 1}')

    def test_bad_date_and_slug_exit_2(self):
        self.run_gf("start", "--idea", "x", "--as-of", "2026-13-40", code=2)
        self.run_gf("start", "--idea", "x", "--slug", "../up", code=2)
        self.assertFalse((self.p / "research").exists())

    def test_no_active_run_and_explicit_path_still_work(self):
        for cmd in (("score",), ("sources", "check"), ("ledger", "verify")):
            self.assertIn("No active run", self.run_gf(*cmd, code=2)["error"]["message"])
        shutil.copy(FIXTURE, self.p / "e.json")
        self.assertEqual(self.run_gf("score", str(self.p / "e.json"))["decision"], "VALIDATE_BEFORE_BUILD")
        self.assertFalse((self.p / "decision.json").exists())

    def test_research_dir_escape_rejected(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        (self.p / "research").symlink_to(outside.name)
        self.run_gf("start", "--idea", "escape", code=2)
        self.assertEqual(os.listdir(outside.name), [])

    def test_template_scores_incomplete_without_a_date(self):
        data = json.loads(TEMPLATE.read_text())
        self.assertEqual(data["as_of"], "")
        (self.p / "t.json").write_text(json.dumps(data))
        out = self.run_gf("score", str(self.p / "t.json"))
        self.assertEqual(out["decision"], "RESEARCH_INCOMPLETE")
        self.assertTrue(any("as_of" in w for w in out["warnings"]))


if __name__ == "__main__":
    unittest.main()
