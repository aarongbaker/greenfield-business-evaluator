"""W50 score planner and the W41 findings-cap stop."""
import copy
import datetime as dt
import json
import pathlib
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from test_skill import ROOT, attest, back_core, sample, scorer
import gf_materials
import gf_plan

DEMO = ROOT / "skill/assets/demo-research"
PII = {"signups", "presale", "channel", "analytics", "invoice", "loi"}


def later():
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=2)).isoformat()


class Demo(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.dir = pathlib.Path(t.name).resolve() / "demo-research"
        shutil.copytree(DEMO, self.dir)
        self.ev = self.dir / "evaluation.json"

    def test_demo_route(self):
        out = gf_plan.for_cli(self.ev)
        r = out["routes"][0]
        self.assertEqual((out["start_total"], r["receipts"], r["total"]), (60.0, 3, 76.0))
        self.assertEqual([a["pillar"] for a in out["above_evidence"]], ["problem", "market", "value", "competition", "execution"])
        self.assertEqual({p: q for p, q in r["quality_targets"].items() if p in scorer.CORE}, dict.fromkeys(scorer.CORE, 4))
        self.assertEqual(sorted(s["experiment_id"] for s in r["steps"]), ["EXP-1", "EXP-2", "EXP-3"])
        self.assertTrue(any(m.startswith("greenfield sources check") for m in out["manual"]))
        self.assertIn("Cheapest route to 75", gf_plan.render(out))

    def test_route_option_writes_that_route_and_it_becomes_the_plan(self):
        from gf_common import GFError
        second = gf_plan.for_cli(self.ev)["routes"][1]
        out = gf_plan.for_cli(self.ev, add=True, route=2)
        self.assertEqual(sorted(out["added_experiments"]), sorted(s["experiment_id"] for s in second["steps"]))
        rows = {x["id"]: x for x in json.loads(self.ev.read_text())["experiments"]}
        self.assertEqual([rows[s["experiment_id"]]["method"] for s in second["steps"]], [s["title"] for s in second["steps"]])
        now = gf_plan.for_cli(self.ev)["routes"][0]  # the route the founder set up is the one the plan and the score follow
        self.assertEqual([(s["entry"], s["pillars"], s["new_experiment"]) for s in now["steps"]], [(s["entry"], s["pillars"], False) for s in second["steps"]])
        with self.assertRaises(GFError):
            gf_plan.for_cli(self.ev, add=True, route=0)

    def test_no_source_step_once_a_report_exists(self):
        (self.dir / "source-verification.json").write_text('{"claims": []}')
        data = json.loads(self.ev.read_text())
        data["verification_report"] = "source-verification.json"
        self.ev.write_text(json.dumps(data))
        self.assertFalse(any("sources check" in m for m in gf_plan.for_cli(self.ev)["manual"]))

    def test_add_experiments_then_score_and_plan_agree(self):
        out = gf_plan.for_cli(self.ev, add=True)
        self.assertEqual(out["added_experiments"], ["EXP-1", "EXP-2", "EXP-3"])
        rows = {x["id"]: x for x in json.loads(self.ev.read_text())["experiments"]}
        self.assertTrue(rows["EXP-1"]["pillars"] and rows["EXP-1"]["success_threshold"])
        again = gf_plan.for_cli(self.ev)["routes"][0]["steps"][0]
        self.assertFalse(again["new_experiment"])
        result = scorer.score_file(self.ev)[0]
        self.assertEqual(result["next_experiment"]["id"], again["experiment_id"])
        self.assertEqual(result["route"]["steps"][0]["experiment_id"], again["experiment_id"])


class Profiles(unittest.TestCase):
    def data(self, profile, q=4, e=1):
        d = sample()
        d["project"]["business_model"] = profile
        for p in scorer.PILLAR_WEIGHTS:
            d["pillars"][p].update(quality=q, evidence=e)
        return d

    def routes(self, profile, target=75, **kw):
        return gf_plan.plan(self.data(profile, **kw), {}, target=target, slug="idea")["routes"]

    def test_pii_files_never_go_straight_to_inbox(self):
        for profile in scorer.PROFILES:
            for target in (75, 90, 100):
                for r in self.routes(profile, target):
                    for s in r["steps"]:
                        if s["entry"]["as"] not in PII:
                            continue
                        with self.subTest(profile=profile, target=target, step=s["entry"]["as"]):
                            self.assertIn("/materials/raw/", s["bring"])
                            if s["bring"].endswith(".pdf"):
                                self.assertTrue(s["redact"].startswith("redact by hand"))
                                self.assertIn(".redacted.pdf --", s["command"])
                                self.assertIn("--redacted", s["command"])
                            else:
                                self.assertTrue(s["redact"].startswith("greenfield evidence redact"))
                                self.assertRegex(s["command"], r"\.redacted\.\w+ --as")

    def test_slack_ranks_first(self):
        top = self.routes("venture_startup", q=3, e=2)[0]
        self.assertGreaterEqual(top["total"], 76.0)

    def test_services_closes_two_gates_with_two_ops_records(self):
        steps = self.routes("services")[0]["steps"]
        ops = [s for s in steps if s["entry"]["as"] == "ops-record"]
        self.assertEqual(sorted(s["gate"] for s in ops), ["delivery_capacity", "owner_dependence"])

    def test_regulated_closes_each_gate_with_its_own_item(self):
        for r in self.routes("regulated"):
            gated = [s for s in r["steps"] if s.get("gate")]
            self.assertEqual(sorted(s["gate"] for s in gated), sorted(scorer.PROFILES["regulated"]["pilot_gates"]))
            self.assertTrue(all(s["entry"]["kind"] == "feasibility_proof" for s in gated))

    def test_target_100_covers_every_pillar_fast(self):
        for profile in scorer.PROFILES:
            with self.subTest(profile):
                start = time.perf_counter()
                r = self.routes(profile, 100)[0]
                self.assertLess(time.perf_counter() - start, 2)
                self.assertEqual(r["total"], 100.0)
                self.assertEqual(set(p for s in r["steps"] for p in s["pillars"]), set(scorer.PILLAR_WEIGHTS))

    def test_gates_only_from_the_materials_gates_column(self):
        for profile in scorer.PROFILES:
            for r in self.routes(profile, 100) + self.routes(profile):
                for s in r["steps"]:
                    if s.get("gate"):
                        self.assertIn(s["gate"], gf_materials.MATERIALS[s["entry"]["as"]][3])

    def test_catalog_matches_materials(self):
        for e in gf_plan.catalog():
            self.assertEqual(e["kind"], gf_materials.MATERIALS[e["as"]][0])


class FromReceipts(unittest.TestCase):
    """Plans read from a real signed ledger."""

    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.base = pathlib.Path(t.name).resolve()
        self.data = sample()
        self.data["evaluation_id"] = "eval-plan"
        self.data["execution"]["customer_validation_performed"] = True
        self.data["evidence_ledger"] = "experiment-ledger.jsonl"

    def receipt(self, name, pillars, material="presale", kind="paid_test", result="pass", gate=None):
        (self.base / name).write_text("SYNTHETIC " + name)
        return attest(self.base / "experiment-ledger.jsonl", kind, "F", "H", artifact=name, attester="Human", pillars=pillars, observed_at="2026-10-22",
                      extra={**gf_materials.binding(self.data, self.base), "material": material, "gate_ids": [gate] if gate else [], "result": result})

    def scored(self):
        errors, warnings = scorer.validate(self.data, self.base)
        self.assertFalse(errors, errors)
        return scorer.score(copy.deepcopy(self.data), warnings), warnings.facts

    def test_route_receipts_score_what_the_planner_projected(self):
        result, facts = self.scored()
        route = gf_plan.plan(self.data, facts, slug=self.base.name)["routes"][0]
        for i, s in enumerate(route["steps"]):
            self.receipt(f"step{i}.txt", s["pillars"], s["entry"]["as"], s["entry"]["kind"], gate=s.get("gate"))
        for p in scorer.PILLAR_WEIGHTS:
            self.data["pillars"][p].update(quality=route["quality_targets"][p], evidence=route["evidence_after"][p], assessed_at=later())
        after, _ = self.scored()
        self.assertEqual(after["decision"], "PROCEED_TO_BOUNDED_PILOT")
        self.assertEqual(after["weighted_quality_0_to_100"], route["total"])

    def test_score_runs_the_planner_once(self):
        with mock.patch.object(gf_plan, "choose", wraps=gf_plan.choose) as chooser:
            result, _ = self.scored()
            scorer.verdict_gap(result)
        self.assertEqual(chooser.call_count, 1)

    def test_failed_gate_is_not_replanned(self):
        self.data["project"]["business_model"] = "regulated"
        self.receipt("memo.txt", [], "memo", "feasibility_proof", result="fail", gate="compliance_path")
        _, facts = self.scored()
        out = gf_plan.plan(self.data, facts)
        self.assertIn("gate compliance_path failed: change the plan and retest, or reframe", out["manual"])
        self.assertFalse(any(s.get("gate") == "compliance_path" for r in out["routes"] for s in r["steps"]))

    def evidence_five(self, qualities):
        for i, group in enumerate((("problem", "market", "competition"), ("value", "economics", "timing"), ("distribution", "execution"))):
            self.receipt(f"repeat{i}.csv", list(group), "repeat", "repeat_purchase")
        for p in scorer.PILLAR_WEIGHTS:
            self.data["pillars"][p].update(evidence=5, quality=qualities.get(p, 3), assessed_at=later())

    def test_findings_cap_stop_at_evidence_five(self):
        self.evidence_five({"problem": 4, "market": 4, "value": 4})
        result, _ = self.scored()
        self.assertEqual(result["weighted_quality_0_to_100"], 70.0)
        self.assertIsNone(result["route"])
        self.assertTrue(result["findings_cap"])
        self.assertEqual(result["headline"], "Evidence is in and findings hold quality at 70.0/100, below the 75 bar: stop or reframe")
        self.assertIn("stop, or reframe", result["next_step"])
        self.assertTrue(any(i.get("by_experiment") is False for i in result["gap"]))
        self.assertIn("(not reachable by another experiment)", scorer.gap_text(result["gap"]))

    def test_capped_mixed_pillar_gets_one_higher_receipt_not_a_stop(self):
        back_core(self.base, self.data)
        for p in scorer.PILLAR_WEIGHTS:
            self.data["pillars"][p].update(quality=4 if p in scorer.CORE else 2, assessed_at=later())
        result, _ = self.scored()
        self.assertEqual(result["weighted_quality_0_to_100"], 72.0)
        self.assertFalse(result["findings_cap"])
        self.assertIsNotNone(result["route"])
        self.assertIn("greenfield plan --add-experiments", result["next_step"])


if __name__ == "__main__":
    unittest.main()
