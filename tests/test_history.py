"""W49: quality is a finding (change log, blocker rules), confirm_via, a shortened ledger, and legacy adoption."""
import argparse
import contextlib
import io
import datetime as dt
import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from test_skill import ROOT, attest, back_core, sample, scorer, write_event
import cli
import gf_ledger
import gf_materials


def later():
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=2)).isoformat()


class Run(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = pathlib.Path(t.name).resolve()
        self.base = self.root / "research" / "greenfield" / "idea"
        self.base.mkdir(parents=True)
        self.ev = self.base / "evaluation.json"
        self.data = sample()
        self.data["evaluation_id"] = "eval-hist0001"
        self.data["evidence_ledger"] = "experiment-ledger.jsonl"
        self.data["execution"]["customer_validation_performed"] = True
        for p in scorer.PILLAR_WEIGHTS:
            self.data["pillars"][p]["quality"] = 3
        self.save()

    def save(self):
        self.ev.write_text(json.dumps(self.data))

    def track(self):
        self.save()
        return cli._track(argparse.Namespace(evaluation=self.ev, project=self.root))

    def scored(self):
        self.save()
        result, errors, _ = scorer.score_file(self.ev)
        return result, errors

    def receipt(self, name, pillars, material="presale", kind="paid_test", result="pass", outcome="4 of 30 paid $49"):
        (self.base / name).write_text("SYNTHETIC " + name)
        return attest(self.base / "experiment-ledger.jsonl", kind, "F", "H", outcome=outcome, artifact=name, attester="Human", pillars=pillars,
                      observed_at="2026-10-22", extra={**gf_materials.binding(self.data, self.base), "material": material, "result": result})


class ChangeLog(Run):
    def test_research_qualities_summarized_and_raise_without_receipt_flagged(self):
        self.data["pillars"]["market"]["quality"] = 4
        log = self.track()
        self.assertIn("7 findings set at quality ≤3", log)
        self.assertIn("market quality unset→4 set above what evidence supports (no receipt yet)", log)

    def test_hand_edit_prints_on_every_score(self):
        self.track()
        self.data["pillars"]["economics"].update(quality=5, assessed_at=later())
        first = self.track()
        self.data["pillars"]["economics"]["quality"] = 3
        second = self.track()  # undone, but the cumulative log keeps it
        for log in (first, second):
            self.assertTrue(any(line.startswith("economics quality 3→5") for line in log), log)

    def test_receipt_then_raise_is_covered(self):
        self.track()
        e = self.receipt("presale.csv", ["economics"])
        self.data["pillars"]["economics"]["quality"] = 5
        line = next(x for x in self.track() if x.startswith("economics quality 3→5"))
        self.assertEqual(line, f'economics quality 3→5 · {e["id"]} presale pass: "4 of 30 paid $49"')

    def test_fail_or_customer_action_does_not_cover_a_raise_to_5(self):
        self.track()
        self.receipt("fail.csv", ["economics"], result="fail")
        self.receipt("signups.csv", ["value"], material="signups", kind="customer_action")
        self.data["pillars"]["economics"].update(quality=5, assessed_at=later())
        self.data["pillars"]["value"].update(quality=5, assessed_at=later())
        log = self.track()
        self.assertTrue(any(x.startswith("economics quality 3→5 changed by hand since") for x in log), log)
        self.assertTrue(any(x.startswith("value quality 3→5 changed by hand since") for x in log), log)

    def test_evaluation_id_change_and_claim_edits_print(self):
        self.data["claims"] = [{"id": "C1", "pillar": "market", "classification": "fact", "statement": "x",
                                "source_url": "https://example.org", "accessed_date": "2026-10-23"}]
        self.data["pillars"]["market"]["claim_ids"] = ["C1"]
        self.track()
        self.data["claims"][0]["classification"] = "estimate"
        self.data["pillars"]["market"]["claim_ids"] = []
        self.data["evaluation_id"] = "eval-other000"
        log = self.track()
        for text in ("evaluation_id changed: eval-hist0001 → eval-other000", "claim C1 reclassified: fact → estimate", "claim C1 unlinked from market"):
            self.assertIn(text, log)
        self.data["claims"] = []
        self.assertIn("claim C1 deleted", self.track())

    def test_output_flag_and_plain_score_both_append(self):
        for extra in ([], ["--output", str(self.root / "x.json")]):
            with contextlib.redirect_stdout(io.StringIO()):
                cli.main(["--project", str(self.root), "score", str(self.ev), *extra])
        self.assertEqual(sum('"snapshot"' in x for x in (self.base / "quality-history.jsonl").read_text().splitlines()), 2)

    def test_demos_and_fixtures_get_no_history(self):
        for ev in (ROOT / "skill/assets/demo-research/evaluation.json", ROOT / "tests/fixtures/validate-before-build.json"):
            self.assertIsNone(cli._track(argparse.Namespace(evaluation=ev, project=ROOT)))
            self.assertFalse((ev.parent / "quality-history.jsonl").exists())


class Blockers(Run):
    def setUp(self):
        super().setUp()
        self.data["hard_blockers"] = [{"id": "B1", "status": "plausible", "fatal": True, "finding": "maybe illegal", "source_ids": []}]
        self.track()

    def test_deleted_fatal_blocker_prints_and_errors(self):
        self.data["hard_blockers"] = []
        self.assertIn("blocker B1 was deleted (it was fatal)", self.track())
        self.assertIn("blocker B1 was deleted: restore it and resolve it with resolved_by", self.scored()[1])

    def test_fatal_false_or_resolved_without_resolved_by_errors(self):
        self.data["hard_blockers"][0]["fatal"] = False
        self.assertIn("hard_blockers B1: fatal changed to false without resolved_by", self.scored()[1])
        self.data["hard_blockers"][0].update(fatal=True, status="resolved")
        self.assertIn("hard_blockers B1: a resolved fatal blocker needs resolved_by", self.scored()[1])

    def test_resolved_by_a_verified_receipt_is_accepted(self):
        e = self.receipt("memo.md", ["execution"], material="memo", kind="feasibility_proof")
        self.data["hard_blockers"][0].update(status="resolved", resolved_by=[e["id"]])
        self.assertFalse([x for x in self.scored()[1] if "B1" in x])
        self.data["hard_blockers"][0]["resolved_by"] = ["C9"]
        self.assertTrue(any("resolved_by 'C9'" in x for x in self.scored()[1]))


class Confirmation(Run):
    def proceed(self):
        for p in scorer.CORE:
            self.data["pillars"][p]["quality"] = 4
        back_core(self.base, self.data)
        result, errors = self.scored()
        self.assertFalse(errors, errors)
        self.assertEqual(result["decision"], "PROCEED_TO_BOUNDED_PILOT")

    def test_fixture_receipts_sign_tty(self):
        self.proceed()
        self.assertEqual({e.get("confirm_via") for e in gf_ledger.read_ledger(self.base / "experiment-ledger.jsonl")}, {"tty"})

    def test_injected_event_blocks_proceed_except_through_score_trusted(self):
        self.proceed()
        (self.base / "extra.txt").write_text("SYNTHETIC extra")
        gf_ledger.append(self.base / "experiment-ledger.jsonl", "paid_test", "F", "H", artifact="extra.txt", attester="Human", pillars=["timing"],
                         confirm=lambda s: None, extra={**gf_materials.binding(self.data, self.base), "material": "presale", "result": "pass"})
        result, _ = self.scored()
        self.assertEqual(result["decision"], "VALIDATE_BEFORE_BUILD")
        self.assertEqual(len(result["injected_events"]), 1)
        self.assertIn("at a terminal", result["next_step"])
        self.assertEqual(scorer._score_trusted(self.ev, allow_injected=True)[0]["decision"], "PROCEED_TO_BOUNDED_PILOT")
        self.assertNotIn("allow_injected", scorer.score_file.__code__.co_varnames)

    def test_shortened_ledger_blocks_proceed_on_every_later_score(self):
        self.proceed()
        ledger = self.base / "experiment-ledger.jsonl"
        gf_ledger.append(ledger, "note", "F", "a note the founder later cut")
        self.track()
        ledger.write_text("".join(ledger.read_text().splitlines(keepends=True)[:-1]))
        for _ in range(2):
            result, _ = self.scored()
            self.assertTrue(result["ledger_shortened"])
            self.assertNotEqual(result["decision"], "PROCEED_TO_BOUNDED_PILOT")
            self.assertIn("experiment ledger was shortened", " ".join(result["warnings"]))
            self.track()

    def test_new_key_warns_without_blocking(self):
        self.proceed()
        with mock.patch.object(gf_ledger, "key_id", lambda key: "other0000000"):
            errors, warnings = scorer.validate(json.loads(self.ev.read_text()), self.base)
        w = [x for x in warnings if "not the one that signed the first receipt" in x]
        self.assertTrue(w)
        self.assertNotIn("ledger reattest", w[0])

    def test_rubric_warning_text(self):
        self.receipt("p.csv", ["problem"], material="signups", kind="customer_action")
        self.data["pillars"]["problem"].update(quality=5, evidence=3)
        _, warnings = scorer.validate(self.data, self.base)
        self.assertIn("pillars.problem: quality 5 is above what evidence 3 supports (4)", warnings)


class Adoption(Run):
    def legacy_event(self, signed=True, name="old.txt"):
        (self.base / name).write_text("SYNTHETIC old")
        meta = gf_ledger.artifact_digest(name, self.base)
        return write_event(self.base / "experiment-ledger.jsonl", meta, key=gf_ledger.load_key() if signed else None, pillars=("economics",))

    def reattest(self):
        with mock.patch.object(gf_ledger, "tty_confirm", lambda s: None):
            return gf_ledger.reattest(self.base / "experiment-ledger.jsonl", adopt=lambda e: ("presale", "pass"))

    def init_legacy(self):
        del self.data["evaluation_id"]
        self.save()
        gf_materials.init(self.base, self.ev)
        self.data = json.loads(self.ev.read_text())
        self.assertTrue(self.data["legacy"])

    def test_legacy_run_adopts_and_the_receipt_counts(self):
        gf_ledger.ensure_key()
        e = self.legacy_event()
        self.init_legacy()
        self.assertEqual([r["action"] for r in self.reattest()], ["adopted"])
        facts = gf_materials.analyze(self.data, self.base / "experiment-ledger.jsonl", self.base)
        self.assertIn(e["id"], facts["intact"])
        self.assertEqual(facts["rubric"]["economics"], 5)
        self.assertEqual(self.reattest(), [])

    def test_start_run_adopts_nothing(self):
        gf_ledger.ensure_key()
        self.legacy_event()
        gf_materials.snapshot(self.base, self.data)  # what start writes
        self.data["legacy"] = True  # typed by hand: does nothing
        self.save()
        self.assertEqual([r["action"] for r in self.reattest()], ["refused"])

    def test_never_signed_after_first_signed_is_refused(self):
        gf_ledger.ensure_key()
        self.legacy_event(name="a.txt")
        self.legacy_event(signed=False, name="b.txt")
        self.init_legacy()
        self.assertEqual([r["action"] for r in self.reattest()], ["adopted", "refused"])

    def test_artifact_outside_the_run_is_skipped(self):
        gf_ledger.ensure_key()
        outside = self.root / "outside.txt"
        outside.write_text("SYNTHETIC out")
        meta = {"path": str(outside), "sha256": gf_ledger.artifact_digest(outside, self.root)["sha256"]}
        write_event(self.base / "experiment-ledger.jsonl", meta, key=gf_ledger.load_key())
        self.init_legacy()
        self.assertEqual([r["action"] for r in self.reattest()], ["skipped"])


if __name__ == "__main__":
    unittest.main()
