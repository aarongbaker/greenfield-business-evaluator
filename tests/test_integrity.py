"""W42/W43/W40/W41: what a signed receipt must be before it can carry a Proceed."""
import argparse
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from test_skill import attest, back_core, sample, scorer
import gf_evidence
import gf_ledger
import gf_materials
from gf_common import GFError

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



class SourceReviews(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.base = pathlib.Path(t.name).resolve()
        self.ev = self.base / "evaluation.json"
        self.report = self.base / "source-verification.json"
        self.ledger = self.base / "experiment-ledger.jsonl"
        self.claims = [{"id": "C1", "pillar": "market", "classification": "fact", "statement": "Market fact", "source_url": "https://example.org/a",
                        "accessed_date": "2026-10-23", "supporting_quote": "quoted text"}]
        self.page = {"url": "https://example.org/a", "content_sha256": "aaa", "text": "the quoted text here"}
        self.write()

    def write(self):
        data = sample()
        data["evaluation_id"] = "eval-x"
        data["claims"] = self.claims
        self.ev.write_text(json.dumps(data))

    def sources(self, force=False):
        with mock.patch.object(gf_evidence, "fetch_public", lambda url: self.page):
            return gf_evidence.check(self.ev, self.report, allow_network=True, force=force)

    def args(self):
        return argparse.Namespace(kind="source_review", ledger=str(self.ledger), artifact=str(self.report), claim_id="C1", gate=None)

    def review(self):
        attest(self.ledger, "source_review", "F", "H", outcome="supported", artifact="source-verification.json", attester="Human", claim_id="C1", extra=gf_ledger._review_binding(self.args()))

    def valid(self):
        return gf_ledger.reviewed_claims(self.ledger, "source-verification.json")

    def test_page_noise_and_new_claims_keep_the_review(self):
        self.sources()
        self.review()
        self.page = {**self.page, "content_sha256": "bbb", "text": "changed page, the quoted text here"}
        before = self.report.read_bytes()
        self.sources()
        self.assertEqual(self.report.read_bytes(), before)
        self.claims.append({**self.claims[0], "id": "C2", "source_url": "https://example.org/b"})
        self.write()
        self.sources()
        self.assertEqual(self.valid(), {"C1": "supported"})

    def test_changed_excerpt_voids_only_with_force(self):
        self.sources()
        self.review()
        self.page = {**self.page, "text": "nothing relevant"}
        with self.assertRaisesRegex(GFError, "1 source reviews will be voided: C1"):
            self.sources()
        self.assertEqual(self.valid(), {"C1": "supported"})
        self.sources(force=True)
        self.assertEqual(self.valid(), {})

    def test_hand_edited_entry_is_refused_and_flagged(self):
        self.sources()
        report = json.loads(self.report.read_text())
        report["claims"][0]["excerpt_check"] = "not_found"
        self.report.write_text(json.dumps(report))
        with self.assertRaisesRegex(GFError, "not produced by greenfield sources check"):
            gf_ledger._review_binding(self.args())
        self.assertTrue(gf_materials._bad_entries(json.loads(self.ev.read_text()), self.base))

    def test_new_key_created_by_sources_check(self):
        self.sources()
        self.assertTrue(gf_ledger.load_key())


class IdeaChange(ReceiptRules):
    def typo(self, text):
        self.data["project"]["idea"] = text
        (self.base / "evaluation.json").write_text(json.dumps(self.data))

    def test_typo_keeps_receipts_and_is_printed_forever(self):
        self.typo("Test concepts")
        gf_materials.reidea(self.base / "experiment-ledger.jsonl", confirm=lambda s: None)
        r = self.run_score()
        self.assertEqual(r["decision"], PROCEED)
        self.assertIn("receipts carried across an idea change", r["warnings"])

    def test_reframe_refused(self):
        self.typo("Something else altogether for other people")
        with self.assertRaisesRegex(GFError, "more than a typo"):
            gf_materials.reidea(self.base / "experiment-ledger.jsonl", confirm=lambda s: None)

    def test_limit_is_cumulative(self):
        self.typo("Test concept AAAA")
        gf_materials.reidea(self.base / "experiment-ledger.jsonl", confirm=lambda s: None)
        self.typo("Test concept AAAABBBBBBB")
        with self.assertRaisesRegex(GFError, "more than a typo"):
            gf_materials.reidea(self.base / "experiment-ledger.jsonl", confirm=lambda s: None)


if __name__ == "__main__":
    unittest.main()
