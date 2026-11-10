"""W51: Mission Control matrix (receipts, gates, plan line) and DECISION.md (recompute, receipts table)."""
import argparse
import json
import os
import pathlib
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from test_skill import attest, sample, scorer
import gf_ledger
import gf_materials
import gf_observe
import gf_report
from gf_common import GFError


class Matrix(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = pathlib.Path(t.name).resolve()
        self.folder = self.root / "research" / "greenfield" / "demo-proceed"
        shutil.copytree(gf_ledger.DEMO_DIR, self.folder)
        patch = mock.patch.object(gf_ledger, "DEMO_DIR", self.folder)  # stands in for the pinned bundled path
        patch.start()
        self.addCleanup(patch.stop)
        os.utime(self.folder / "decision.json")  # a git checkout leaves mtimes in any order; the stored decision is current
        self.rid = gf_observe.new_run(self.root, "demo copy", "claude", research_dir=self.folder)

    def view(self):
        gf_observe._decision_cache.clear()
        return gf_observe.decision_view(self.root, self.rid)

    def test_matrix_shows_receipts_gates_and_proceed(self):
        v = self.view()
        self.assertEqual(v["verdict"]["decision"], "PROCEED_TO_BOUNDED_PILOT")
        econ = next(p for p in v["pillars"] if p["key"] == "economics")
        self.assertEqual(len(econ["receipts"]), 1)
        r = econ["receipts"][0]
        self.assertEqual((r["material"], r["result"], r["intact"]), ("invoice", "pass", True))
        self.assertIn("$2,400", r["threshold"])
        self.assertTrue(all(g["closed"] for g in v["gates"]))
        self.assertEqual(len(v["gates"]), 3)
        self.assertIsNone(v["plan"])
        self.assertEqual(v["next_step"]["text"], scorer.score_file(self.folder / "evaluation.json")[0]["next_step"])

    def test_edited_receipt_shows_cross_and_drops_the_verdict(self):
        (self.folder / "receipts" / "referrals.csv").write_text("edited")
        v = self.view()
        self.assertNotEqual(v["verdict"]["decision"], "PROCEED_TO_BOUNDED_PILOT")
        dist = next(p for p in v["pillars"] if p["key"] == "distribution")
        self.assertFalse(dist["receipts"][0]["intact"])

    def report(self):
        return gf_report._handler(argparse.Namespace(folder=self.folder, ascii=False, project=self.root, run=None))

    def test_report_is_stamped_demo_and_lists_receipts(self):
        self.report()
        md = (self.folder / "DECISION.md").read_text()
        self.assertIn("# DEMO: SAMPLE Clinic Compliance Audits", md)
        self.assertIn("**DEMO PROCEED_TO_BOUNDED_PILOT.**", md)
        self.assertIn("**Receipts behind this verdict**", md)
        self.assertEqual(md.count("| invoice | pass |"), 2)
        self.assertIn("| gate delivery_capacity |", md)
        self.assertIn("How much to trust Proceed", md)

    def test_hand_edited_decision_is_refused(self):
        dec = self.folder / "decision.json"
        d = json.loads(dec.read_text())
        d["weighted_quality_0_to_100"] = 99.0
        dec.write_text(json.dumps(d))
        with self.assertRaisesRegex(GFError, "does not match a fresh score"):
            self.report()
        self.assertFalse((self.folder / "DECISION.md").exists())


class FailedGate(unittest.TestCase):
    def test_fail_receipt_on_a_gate_cannot_close(self):
        with tempfile.TemporaryDirectory() as t:
            root = pathlib.Path(t).resolve()
            base = root / "research" / "greenfield" / "reg"
            base.mkdir(parents=True)
            data = sample()
            data.update(evaluation_id="eval-gate0001", evidence_ledger="experiment-ledger.jsonl")
            data["project"]["business_model"] = "regulated"
            (base / "memo.txt").write_text("SYNTHETIC memo")
            e = attest(base / "experiment-ledger.jsonl", "feasibility_proof", "F", "H", artifact="memo.txt", attester="Human", pillars=[],
                       observed_at="2026-10-22", extra={**gf_materials.binding(data, base), "material": "memo", "gate_ids": ["compliance_path"], "result": "fail"})
            (base / "evaluation.json").write_text(json.dumps(data))
            rid = gf_observe.new_run(root, "reg", "claude", research_dir=base)
            v = gf_observe.decision_view(root, rid)
            gate = next(g for g in v["gates"] if g["gate"] == "compliance_path")
            self.assertEqual(gate["text"], f"compliance_path · {e['id']} fail (cannot close)")
            other = next(g for g in v["gates"] if g["gate"] == "jurisdiction_review")
            self.assertTrue(other["text"].startswith("jurisdiction_review · needs "))
            self.assertTrue(v["plan"]["text"].startswith("To 7"))


if __name__ == "__main__":
    unittest.main()
