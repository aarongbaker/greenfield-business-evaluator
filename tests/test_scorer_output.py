import contextlib
import copy
import io
import json
import os
import pathlib
import tempfile
import unittest
from unittest import mock

from test_skill import ROOT, TEMPLATE, attest, sample, scorer

FIXTURES = ROOT / "tests" / "fixtures"
SNAPSHOTS = ROOT / "tests" / "snapshots"
TEMPLATE_PATH = ROOT / "skill" / "assets" / "evaluation-template.json"


class Tty(io.StringIO):
    encoding = "utf-8"

    def isatty(self):
        return True


def run_main(argv, tty):
    out, err = (Tty() if tty else io.StringIO()), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), mock.patch.dict(os.environ, {"TERM": "xterm"}):
        code = scorer.main([str(a) for a in argv])
    return code, out.getvalue(), err.getvalue()


def scored(data, base=None):
    errors, warnings = scorer.validate(data, base)
    assert not errors, errors
    return scorer.score(data, warnings)


def receipt_data(base, quality):
    """Core evidence 3 backed by a real attested receipt in base, every pillar at the given quality."""
    (base / "receipt.txt").write_text("SYNTHETIC TEST RECEIPT")
    event = attest(base / "experiments.jsonl", "paid_test", "Fixture", "Test measurable intent", outcome="synthetic fixture",
                   artifact="receipt.txt", attester="Human Fixture", pillars=list(scorer.CORE))
    data = sample()
    data["execution"]["customer_validation_performed"] = True
    data["evidence_ledger"] = "experiments.jsonl"
    for p in scorer.PILLAR_WEIGHTS:
        data["pillars"][p]["quality"] = quality
    for p in scorer.CORE:
        data["pillars"][p]["evidence"] = 3
        data["pillars"][p]["behaviors"] = [{"kind": "paid_test", "description": "Fixture only", "observed_at": "2026-10-22",
                                            "source_or_artifact": "receipt.txt", "verified": True, "ledger_event_id": event["id"]}]
    return data


class SnapshotTests(unittest.TestCase):
    """Wave 2 gate: the text a person sees for the template and a filled VALIDATE_BEFORE_BUILD fixture."""

    def check(self, path, name):
        result, errors, _ = scorer.score_file(path)
        self.assertFalse(errors, errors)
        text = scorer.render_text(result, color=False)
        self.assertEqual(text, (SNAPSHOTS / name).read_text(encoding="utf-8"))
        return text

    def test_template_snapshot(self):
        text = self.check(TEMPLATE_PATH, "template.txt")
        self.assertLessEqual(len(text.splitlines()), 27)
        self.assertTrue(text.startswith("● RESEARCH INCOMPLETE"))

    def test_validate_fixture_snapshot(self):
        self.check(FIXTURES / "validate-before-build.json", "validate-before-build.txt")

    def test_ascii_fallback(self):
        result, _, _ = scorer.score_file(FIXTURES / "validate-before-build.json")
        result["project"] = "Café 🚀 مرحبا"
        scorer.render_text(result, color=False, glyphs="ascii").encode("ascii")


class FieldTests(unittest.TestCase):
    def assert_fields(self, result, decision, headline, next_step):
        self.assertEqual(result["decision"], decision)
        self.assertEqual(result["verdict_label"], scorer.VERDICTS[decision]["label"])
        self.assertEqual(result["headline"], headline)
        self.assertEqual(result["next_step"], next_step)
        self.assertTrue(0 < len(result["headline"]) <= 90 and "\n" not in result["headline"])
        self.assertEqual(result["deprecated_fields"], ["memo_label", "source_review_gate_open"])

    def test_research_incomplete(self):
        self.assert_fields(scored(copy.deepcopy(TEMPLATE)), "RESEARCH_INCOMPLETE",
                           "Research incomplete: 8 of 8 pillars unassessed, no live web research",
                           "Fill pillar quality scores and run live web research, then re-score.")

    def test_validate_before_build(self):
        data = sample()
        data["pillars"]["economics"]["evidence"] = 0
        self.assert_fields(scored(data), "VALIDATE_BEFORE_BUILD",
                           "Evidence is thin on economics and problem: test these before building",
                           "Record a paid-test result for economics with gf_ledger.py, then re-score.")
        data["experiments"] = [{"id": "X1", "hypothesis": "Ten HR leads pay $50 for a benchmark"}]
        self.assertEqual(scored(data)["next_step"],
                         "Run X1 (Ten HR leads pay $50 for a benchmark), record the result with gf_ledger.py, then re-score.")

    def test_no_go(self):
        self.assert_fields(scorer.score_file(FIXTURES / "no-go.json")[0], "NO_GO",
                           "Fatal blocker confirmed: R1 Illustrative regulatory prohibition",
                           "Do not build; revisit only if new sourced evidence resolves blocker R1.")

    def test_pivot_and_proceed(self):
        with tempfile.TemporaryDirectory() as d:
            base = pathlib.Path(d)
            self.assert_fields(scored(receipt_data(base, 1), base), "PIVOT",
                               "Behavior-backed evidence shows a severe weakness in problem, market, value, economics and…",
                               "Reframe the idea around the weak core pillar and evaluate it as a new evaluation.json.")
            self.assert_fields(scored(receipt_data(base, 4), base), "PROCEED_TO_BOUNDED_PILOT",
                               "All five core pillars clear the evidence gates: run a bounded pilot",
                               "Run a bounded pilot against its pre-committed thresholds; do not scale yet.")

    def test_headline_strips_controls_and_caps_length(self):
        data = sample()
        data["claims"] = [{"id": "C1", "pillar": "execution", "classification": "fact", "statement": "x",
                           "source_url": "https://example.org/rule", "accessed_date": "2026-10-23"}]
        data["hard_blockers"] = [{"id": "R1", "fatal": True, "status": "confirmed", "source_ids": ["C1"],
                                  "finding": "Line one\nline two\x1b[31m ‮" + "🚀" * 200}]
        h = scored(data)["headline"]
        self.assertEqual(len(h), 90)
        self.assertNotRegex(h, "[\n\x1b‮]")

    def test_source_review_pending_matches_source_risk(self):
        clean = scored(sample())
        self.assertFalse(clean["source_review_pending"])
        self.assertTrue(clean["source_review_gate_open"])  # deprecated key keeps its old value
        data = sample()
        data["claims"] = [{"id": "C1", "pillar": "market", "classification": "fact", "statement": "x",
                           "source_url": "https://example.org", "accessed_date": "2026-10-23"}]
        risky = scored(data)
        self.assertTrue(risky["source_review_pending"])
        self.assertFalse(risky["source_review_gate_open"])

    def test_pre_w12_keys_unchanged(self):
        old = json.loads((FIXTURES / "decision-pre-w12.json").read_text())
        new = scorer.score_file(FIXTURES / "validate-before-build.json")[0]
        self.assertEqual({k: new[k] for k in old}, old)


def apply_gap(data, result):
    """Apply every requirement verdict_gap() lists to data and the warnings score() would see."""
    data = copy.deepcopy(data)
    warnings = [w for w in result["warnings"]]
    for item in scorer.verdict_gap(result):
        k = item["key"]
        if "field" in item:
            data["pillars"][item["pillar"]][item["field"]] = item["needed"]
        elif k == "web":
            data["execution"]["web_used"] = True
        elif k == "started":
            data["as_of"] = "2026-11-03"
            data["project"] = {a: ("X" if str(b).startswith("REPLACE_") else b) for a, b in data["project"].items()}
        elif k.startswith("blocker:"):
            for b in data["hard_blockers"]:
                if b.get("id") == k[8:]:
                    b["status"] = "resolved"
        elif k.startswith("gate:"):
            data.setdefault("pilot_gates", {})[k[5:]] = {"passed": True, "evidence_ids": ["EV-x"]}
        elif k == "source_review":
            data["verification_report"] = "report.json"
            warnings = [w for w in warnings if not w.startswith(("Unreviewed public source", "Could not validate source"))]
        elif k == "reattest":
            warnings = [w for w in warnings if "gf_ledger.py reattest" not in w]
    return data, [w for w in warnings if not w.startswith(("Unmet business-model", "Public citations", "No actual", "No live"))]


class VerdictGapTests(unittest.TestCase):
    def cases(self):
        paths = [TEMPLATE_PATH, ROOT / "skill/assets/demo-research/evaluation.json", *sorted(FIXTURES.glob("*.json"))]
        for path in paths:
            result, errors, _ = scorer.score_file(path)
            if result:
                yield path.name, json.loads(path.read_text()), result
        with tempfile.TemporaryDirectory() as d:
            base = pathlib.Path(d)
            for q in (1, 2, 4):
                data = receipt_data(base, q)
                data["project"]["business_model"] = "bootstrapped_saas"
                data["hard_blockers"] = [{"id": "B9", "status": "plausible", "fatal": True, "finding": "x", "source_ids": []}]
                yield f"receipts-q{q}", data, scored(data, base)

    def test_verdict_gap_reaches_target(self):
        seen = set()
        for name, data, result in self.cases():
            seen.add(result["decision"])
            fixed, warnings = apply_gap(data, result)
            after = scorer.score(fixed, list(warnings))
            if result["decision"] == "NO_GO":  # the gap names only the blocker; once it is resolved the next gap applies
                self.assertNotEqual(after["decision"], "NO_GO", name)
                fixed, warnings = apply_gap(fixed, after)
                after = scorer.score(fixed, warnings)
            self.assertEqual(after["decision"], "PROCEED_TO_BOUNDED_PILOT", name)
        self.assertTrue({"RESEARCH_INCOMPLETE", "VALIDATE_BEFORE_BUILD", "NO_GO", "PIVOT"} <= seen, seen)

    def test_verdict_gap_empty_when_proceed(self):
        with tempfile.TemporaryDirectory() as d:
            base = pathlib.Path(d)
            result = scored(receipt_data(base, 4), base)
        self.assertEqual(result["decision"], "PROCEED_TO_BOUNDED_PILOT")
        self.assertEqual(scorer.verdict_gap(result), [])
        self.assertNotIn("To reach", scorer.render_text(result, color=False))

    def test_gap_order_and_shared_text(self):
        result = scorer.score_file(TEMPLATE_PATH)[0]
        gap = scorer.verdict_gap(result)
        self.assertEqual([i["current"] for i in gap[:8]], [None] * 8)  # unassessed pillars first
        no_go = scorer.score_file(FIXTURES / "no-go.json")[0]
        self.assertEqual(scorer.verdict_gap(no_go), [{"key": "blocker:R1", "text": "Resolve blocker R1"}])
        text = " ".join(scorer.render_text(no_go, color=False).split())
        self.assertIn("To reach Proceed: " + scorer.gap_text(scorer.verdict_gap(no_go)), text)


class WarningTests(unittest.TestCase):
    def test_groups_and_order(self):
        out = scorer.summarize_warnings(["pillars.timing: no claims linked", "Other", "pillars.market: no claims linked",
                                         "Unmet business-model pilot gates: g1", "claims[0]: source has no access date"])
        self.assertEqual(out, ["Unmet business-model pilot gates: g1", "claims[0]: source has no access date",
                               "2 pillars have no linked claims: timing, market", "Other"])

    def test_more_than_five_groups(self):
        result = scorer.score_file(FIXTURES / "validate-before-build.json")[0]
        result["warnings"] = [f"warning {i}" for i in range(7)]
        text = scorer.render_text(result, color=False)
        self.assertIn("top 5 shown", text)
        self.assertIn("  +2 more", text)
        self.assertIn("warning 6", scorer.render_text(result, color=False, all_warnings=True))


class ModeTests(unittest.TestCase):
    def test_mode_matrix(self):
        with tempfile.TemporaryDirectory() as d:
            out_file = pathlib.Path(d) / "decision.json"
            code, out, err = run_main([TEMPLATE_PATH], tty=True)
            self.assertEqual((code, err), (0, ""))
            self.assertTrue(out.startswith("\033[1;2m● RESEARCH INCOMPLETE"))
            for argv, tty in (([TEMPLATE_PATH], False), ([TEMPLATE_PATH, "--json"], True)):
                code, out, err = run_main(argv, tty)
                self.assertEqual(json.loads(out)["decision"], "RESEARCH_INCOMPLETE")
                self.assertIn("WARNING: ", err)
                self.assertNotIn("\033", out + err)
            code, out, err = run_main([TEMPLATE_PATH, "--output", out_file], tty=True)
            self.assertEqual(err, "")
            self.assertTrue(out.endswith(f"Saved decision.json to {out_file}\n"))
            self.assertEqual(json.loads(out_file.read_text())["decision"], "RESEARCH_INCOMPLETE")
            out_file.unlink()
            for tty, extra in ((False, []), (True, ["--json"])):
                code, out, err = run_main([TEMPLATE_PATH, "--output", out_file] + extra, tty)
                self.assertEqual((code, out), (0, ""))
                self.assertIn("WARNING: ", err)
                self.assertTrue(out_file.exists())

    def test_no_color(self):
        code, out, _ = run_main([TEMPLATE_PATH, "--no-color"], tty=True)
        self.assertNotIn("\033", out)
        with mock.patch.dict(os.environ, {"NO_COLOR": "1"}):
            with contextlib.redirect_stdout(Tty()) as out:
                scorer.main([str(TEMPLATE_PATH)])
        self.assertNotIn("\033", out.getvalue())

    def test_invalid_input_exits_2(self):
        with tempfile.TemporaryDirectory() as d:
            bad = pathlib.Path(d) / "e.json"
            bad.write_text("{}")
            code, out, err = run_main([bad], tty=True)
            self.assertEqual((code, out), (2, ""))
            self.assertIn("ERROR: ", err)


if __name__ == "__main__":
    unittest.main()
