"""W42/W43/W40/W41: what a signed receipt must be before it can carry a Proceed."""
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from test_skill import attest, back_core, sample, scorer

PROCEED = "PROCEED_TO_BOUNDED_PILOT"


class ReceiptRules(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.base = pathlib.Path(t.name).resolve()
        self.data = sample()
        self.events = back_core(self.base, self.data)

    def run_score(self):
        errors, warnings = scorer.validate(self.data, self.base)
        self.assertFalse(errors, errors)
        return scorer.score(self.data, warnings)

    def extra_receipt(self, name, pillars, result="pass", **over):
        (self.base / name).write_text("SYNTHETIC " + name)
        from gf_materials import idea_sha
        bind = {"evaluation_id": self.data["evaluation_id"], "run_slug": self.base.name, "idea_sha": idea_sha(self.data["project"]), "result": result, **over}
        return attest(self.base / "experiment-ledger.jsonl", "paid_test", "Fixture", "H", artifact=name, attester="Human", pillars=pillars, observed_at="2026-10-22", extra=bind)

    def test_distinct_receipts_reach_proceed(self):
        self.assertEqual(self.run_score()["decision"], PROCEED)

    def test_one_file_cannot_back_three_core_pillars(self):
        (self.base / "shared.txt").write_text("same")
        for pillars in (["problem", "market"], ["value"]):
            attest(self.base / "experiment-ledger.jsonl", "paid_test", "F", "H", artifact="shared.txt", attester="Human", pillars=pillars)
        errors, _ = scorer.validate(self.data, self.base)
        self.assertTrue(any("at most 2 core pillars" in e for e in errors), errors)

    def test_quality_above_a_mixed_receipt_blocks_proceed(self):
        self.extra_receipt("mixed.txt", ["market"], result="mixed")  # paid_test at 4 outranks nothing: same ceiling, newest governs
        self.data["pillars"]["market"]["quality"] = 5
        r = self.run_score()
        self.assertNotEqual(r["decision"], PROCEED)
        self.assertTrue(any(i["key"].startswith(("rubric:market", "assess:market")) for i in r["receipt_gaps"]), r["receipt_gaps"])

    def test_receipt_after_assessment_needs_reassessing(self):
        self.extra_receipt("late.txt", ["problem"])
        self.data["pillars"]["problem"]["assessed_at"] = "2026-01-01T00:00:00+00:00"
        r = self.run_score()
        self.assertNotEqual(r["decision"], PROCEED)
        self.assertIn("assess:problem", [i["key"] for i in r["receipt_gaps"]])

    def test_failed_core_receipt_says_stop(self):
        self.extra_receipt("fail.txt", ["value"], result="fail")
        import datetime as dt
        self.data["pillars"]["value"]["assessed_at"] = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=2)).isoformat()
        self.data["pillars"]["value"]["quality"] = 2
        r = self.run_score()
        self.assertEqual(r["failed_core"], ["value"])
        self.assertIn("stop, or reframe", r["next_step"])

    def test_receipt_for_another_run_does_not_count(self):
        self.extra_receipt("other.txt", ["timing"], run_slug="some-other-run")
        _, warnings = scorer.validate(self.data, self.base)
        self.assertTrue(any("belongs to another evaluation" in w for w in warnings), warnings)

    def test_receipt_for_a_changed_idea_does_not_count(self):
        self.data["project"]["idea"] = "A different concept"
        _, warnings = scorer.validate(self.data, self.base)
        self.assertTrue(any("different idea" in w for w in warnings), warnings)
        self.assertNotEqual(scorer.score(self.data, warnings)["decision"], PROCEED)


if __name__ == "__main__":
    unittest.main()
