"""W29: the generated DECISION.md block."""
import copy
import contextlib
import io
import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "skill" / "scripts"))
import gf_report  # noqa: E402
import score_project  # noqa: E402
from gf_common import GFError  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
SNAPS = ROOT / "tests" / "snapshots"
SHA = "ab" * 32
CASES = {"report-template.md": ROOT / "skill/assets/evaluation-template.json",
         "report-demo.md": ROOT / "skill/assets/demo-research/evaluation.json",
         "report-no-go.md": ROOT / "tests/fixtures/no-go.json",
         "report-validate-before-build.md": ROOT / "tests/fixtures/validate-before-build.json"}


def load(path):
    result, errors, _ = score_project.score_file(path)
    assert not errors, errors
    return result, json.loads(pathlib.Path(path).read_text())


class ReportTests(unittest.TestCase):
    def test_snapshots(self):
        for name, path in CASES.items():
            with self.subTest(name):
                dec, ev = load(path)
                self.assertEqual(gf_report.render_block(dec, ev, SHA), (SNAPS / name).read_text(encoding="utf-8"))

    def test_weight_order_every_profile(self):
        from gf_profiles import PROFILES
        dec, ev = load(CASES["report-demo.md"])
        for name, prof in PROFILES.items():
            with self.subTest(name):
                d = {**dec, "business_model_profile": name, "pillar_weights": prof["weights"]}
                rows = [r for r in gf_report.render_block(d, ev).splitlines() if r.startswith("| ") and "---" not in r][1:]
                ws = [int(r.split(" | ")[1]) for r in rows]
                self.assertEqual(ws, sorted(ws, reverse=True))

    def test_callout_matches_decision_for_every_verdict(self):
        dec, ev = load(CASES["report-demo.md"])
        for code, alert in gf_report.ALERTS.items():
            with self.subTest(code):
                d = {**dec, "decision": code, "headline": f"why {code}"}
                lines = gf_report.render_block(d, ev).splitlines()
                self.assertEqual(lines[lines.index(f"> [!{alert}]") + 1], f"> **{code}.** why {code}")
        self.assertEqual(set(gf_report.ALERTS), set(score_project.VERDICTS) - {"INVALID"})

    def test_rows_never_disagree_with_decision_json(self):
        dec, ev = load(CASES["report-demo.md"])
        rows = [r.split(" | ") for r in gf_report.render_block(dec, ev).splitlines() if r.startswith("| ") and "---" not in r][1:]
        self.assertEqual([r[0][2:].lower() for r in rows], [p for p, _ in sorted(dec["pillar_weights"].items(), key=lambda kv: -kv[1])])
        for r in rows:
            p = r[0][2:].lower()
            self.assertTrue(r[2].endswith(f" {dec['quality_scores'][p]}") and r[3].endswith(f" {dec['evidence_scores'][p]}"), r)

    def test_stale_decision_refused(self):
        dec, ev = load(CASES["report-demo.md"])
        ev["pillars"]["problem"]["quality"] = 1
        with self.assertRaises(GFError):
            gf_report.render_block(dec, ev)

    def test_null_gap_cell_escape_and_ascii(self):
        dec, ev = load(CASES["report-demo.md"])
        ev, dec = copy.deepcopy(ev), copy.deepcopy(dec)
        ev["pillars"]["problem"]["evidence"] = dec["evidence_scores"]["problem"] = 1  # quality 4, evidence 1: a gap
        ev["pillars"]["problem"]["finding"] = "a | b\nc"
        ev["pillars"]["timing"]["quality"] = dec["quality_scores"]["timing"] = None
        out = gf_report.render_block(dec, ev)
        self.assertIn("a \\| b c (gap)", out)
        self.assertIn("····· ", out.split("| Timing")[1].splitlines()[0])
        self.assertIn("not assessed", out)
        ascii_out = gf_report.render_block(dec, ev, ascii=True)
        self.assertTrue(ascii_out.splitlines()[0] == gf_report.START and "█" not in ascii_out)

    def test_merge_idempotent_preserves_narrative_and_ignores_fenced_markers(self):
        dec, ev = load(CASES["report-demo.md"])
        block = gf_report.render_block(dec, ev, SHA)
        fenced = f"```\n{gf_report.START}\n{gf_report.END}\n```\n"
        narrative = f"\n## Thesis\r\nmine  \n{fenced}tail without newline"
        memo = gf_report.merge(narrative, block)  # no markers outside the fence: inserted on top
        self.assertEqual(memo, block + "\n" + narrative)
        self.assertEqual(gf_report.merge(memo, block), memo)
        new = gf_report.render_block({**dec, "headline": "changed"}, ev, SHA)
        out = gf_report.merge(memo, new)
        self.assertTrue(out.startswith(new) and out.endswith(narrative))
        self.assertEqual(gf_report.merge("", block), block)

    def test_edited_lines_named(self):
        dec, ev = load(CASES["report-demo.md"])
        block = gf_report.render_block(dec, ev, SHA)
        memo = "intro\n" + block.replace("# SAMPLE", "# HAND", 1)
        self.assertEqual(gf_report.edited_lines(memo, block), [3])
        self.assertEqual(gf_report.edited_lines("intro\n" + block, block), [])
        self.assertEqual(gf_report.edited_lines(memo, ""), [])

    def test_cli_warns_on_hand_edit_and_rescore_changes_table(self):
        import cli
        with tempfile.TemporaryDirectory() as t:
            t = pathlib.Path(t)
            (t / "evaluation.json").write_text(CASES["report-demo.md"].read_text())
            def gf(*a):
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    return cli.main(["--project", str(t), *a]), err.getvalue()
            score = lambda: gf("score", str(t / "evaluation.json"), "--output", str(t / "decision.json"))[0]
            self.assertEqual(score(), 0)
            self.assertEqual(gf("report", str(t))[0], 0)
            first = (t / "DECISION.md").read_text()
            (t / "DECISION.md").write_text(first.replace("investment memo", "my memo", 1))
            _, err = gf("report", str(t))
            self.assertIn("lines 2)", err)
            self.assertIn("investment memo", (t / "DECISION.md").read_text())
            ev = json.loads((t / "evaluation.json").read_text())
            ev["pillars"]["problem"]["quality"] = 1
            (t / "evaluation.json").write_text(json.dumps(ev))
            self.assertEqual(score(), 0)
            self.assertEqual(gf("report", str(t))[0], 0)
            new = (t / "DECISION.md").read_text()
            self.assertNotEqual(new, first)
            row = lambda m: next(r for r in m.splitlines() if r.startswith("| Problem"))
            self.assertNotEqual(row(new), row(first))
            sha = lambda m: next(l for l in m.splitlines() if "sha256" in l)
            self.assertNotEqual(sha(new), sha(first))

    def test_cli_report_end_to_end(self):
        import cli
        with tempfile.TemporaryDirectory() as t:
            t = pathlib.Path(t)
            (t / "evaluation.json").write_text(CASES["report-demo.md"].read_text())
            def gf(*a):
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    return cli.main(["--project", str(t), *a]), out.getvalue(), err.getvalue()
            self.assertEqual(gf("score", str(t / "evaluation.json"), "--output", str(t / "decision.json"))[0], 0)
            (t / "DECISION.md").write_text("my notes\n")
            code, _, err = gf("report", str(t))
            self.assertEqual(code, 0)
            self.assertIn("inserted", err)
            memo = (t / "DECISION.md").read_text()
            self.assertTrue(memo.endswith("\nmy notes\n") and "sha256" in memo)
            self.assertEqual(gf("report", str(t))[0], 0)
            self.assertEqual((t / "DECISION.md").read_text(), memo)
            ev = json.loads((t / "evaluation.json").read_text())
            ev["pillars"]["problem"]["quality"] = 1
            (t / "evaluation.json").write_text(json.dumps(ev))
            self.assertEqual(gf("report", str(t))[0], 2)  # stale decision.json


if __name__ == "__main__":
    unittest.main()
