"""W52: the bundled worked example reaches Proceed only in its own folder, unedited."""
import contextlib
import fnmatch
import io
import json
import os
import pathlib
import shutil
import sys
import tempfile
import tomllib
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from test_skill import ROOT, scorer
import cli
import gf_ledger
import gf_materials
import gf_observe

DEMO = gf_ledger.DEMO_DIR


def run_cli(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = cli.main(list(argv))
    return code, out.getvalue()


class DemoProceed(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = pathlib.Path(t.name).resolve()

    def copy(self, slug):
        dst = self.root / "research" / "greenfield" / slug
        shutil.copytree(DEMO, dst)
        return dst

    def test_demo_proceed_json(self):
        code, out = run_cli("--project", str(self.root), "--json", "demo", "--proceed")
        result = json.loads(out)
        self.assertEqual((code, result["decision"], result["weighted_quality_0_to_100"], result["demo"]), (0, "PROCEED_TO_BOUNDED_PILOT", 76.6, True))
        self.assertFalse((self.root / ".greenfield-observe").exists())
        self.assertEqual(json.loads((DEMO / "decision.json").read_text())["decision"], "PROCEED_TO_BOUNDED_PILOT")

    def test_text_is_stamped_demo(self):
        result = scorer.score_file(DEMO / "evaluation.json")[0]
        args = cli.build_parser().parse_args(["demo", "--proceed"])
        with mock.patch.object(cli, "_color", lambda a: False):
            self.assertTrue(cli.t_demo(result, args).startswith("DEMO:"))

    def test_real_finished_run_stays_active(self):
        rid = gf_observe.new_run(self.root, "Real idea", "claude")
        gf_observe.emit(self.root, rid, "run_completed")
        run_cli("--project", str(self.root), "--json", "demo", "--proceed")
        run_cli("--project", str(self.root), "--json", "demo")
        self.assertEqual(gf_observe.active_run(self.root), rid)

    def test_edited_demo_verifies_nothing(self):
        moved = self.root / "demo-proceed"
        shutil.copytree(DEMO, moved)
        with mock.patch.object(gf_ledger, "DEMO_DIR", moved):
            self.assertEqual(scorer.score_file(moved / "evaluation.json")[0]["decision"], "PROCEED_TO_BOUNDED_PILOT")
            data = json.loads((moved / "evaluation.json").read_text())
            data["project"]["idea"] += " and hygienists"
            (moved / "evaluation.json").write_text(json.dumps(data, indent=2) + "\n")
            result, errors, _ = scorer.score_file(moved / "evaluation.json")
        self.assertTrue(errors or result["decision"] != "PROCEED_TO_BOUNDED_PILOT")

    def assert_dead(self, folder):
        result, errors, _ = scorer.score_file(folder / "evaluation.json")
        self.assertTrue(errors, result and result["decision"])
        facts = gf_materials.analyze(json.loads((folder / "evaluation.json").read_text()), folder / "experiment-ledger.jsonl", folder)
        self.assertFalse(facts["intact"])

    def test_copy_into_another_run_verifies_nothing_under_any_key(self):
        folder = self.copy("x")
        self.assert_dead(folder)
        with mock.patch.dict(os.environ, GF_ATTEST_KEY_FILE=str(DEMO / "demo-attest.key")):
            self.assert_dead(folder)
            with mock.patch.object(gf_ledger, "tty_confirm", lambda s: None):
                self.assertTrue(all(r["action"] == "refused" for r in gf_ledger.reattest(folder / "experiment-ledger.jsonl")))
        with self.assertRaises(gf_materials.GFError):
            gf_materials.init(folder, folder / "evaluation.json")

    def test_copy_under_the_demo_slug_verifies_nothing(self):
        folder = self.copy("demo-proceed")
        self.assert_dead(folder)
        with mock.patch.object(gf_ledger, "tty_confirm", lambda s: None):
            out = gf_ledger.reattest(folder / "experiment-ledger.jsonl")
        self.assertTrue(out and all(r["action"] == "refused" for r in out))
        with self.assertRaises(gf_materials.GFError):
            gf_materials.init(folder, folder / "evaluation.json")

    def test_package_data_ships_every_demo_file(self):
        globs = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["setuptools"]["package-data"]["greenfield_evaluator"]
        for f in DEMO.rglob("*"):
            if f.is_file():
                rel = f.relative_to(ROOT / "skill").as_posix()
                self.assertTrue(any(fnmatch.fnmatch(rel, g) and rel.count("/") == g.count("/") for g in globs), rel)


if __name__ == "__main__":
    unittest.main()
