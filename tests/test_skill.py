import copy
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skill" / "scripts"))
SPEC = importlib.util.spec_from_file_location("scorer", ROOT / "skill" / "scripts" / "score_project.py")
scorer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scorer)
TEMPLATE = json.loads((ROOT / "skill" / "assets" / "evaluation-template.json").read_text())
# Attestation keys live in a throwaway folder, never the real ~/.config.
os.environ["GF_CONFIG_DIR"] = tempfile.mkdtemp(prefix="gf-config-")
os.environ.pop("GF_ATTEST_KEY_FILE", None)


def attest(*args, **kwargs):
    """Record an attested ledger event as a test human at a terminal: local key plus a stubbed tty, so it signs confirm_via: tty."""
    import gf_ledger
    from unittest import mock
    gf_ledger.ensure_key()
    with mock.patch.object(gf_ledger, "tty_confirm", lambda summary: None):
        return gf_ledger.append(*args, **kwargs)


def write_event(ledger_path, artifact, key=None, kind="paid_test", pillars=("problem", "market")):
    """Append a raw event with the given artifact meta, bypassing append(): signed when key is given (legacy-style if not)."""
    import gf_ledger
    fields = {"observed_at": "2026-10-22", "kind": kind, "project": "Fixture", "hypothesis": "H", "outcome": "", "notes": "",
              "attester": "Jane Human", "human_attested": True, "artifact": artifact, "pillar_ids": sorted(pillars),
              "claim_id": "", "experiment_id": ""}
    return gf_ledger._write(ledger_path, fields, key)


def proceed_data(event_id, ledger="experiment-ledger.jsonl", pillars=("problem", "market")):
    """A filled fixture citing event_id at evidence 3 on the given core pillars. For Proceed use back_core()."""
    data = sample()
    data["execution"]["customer_validation_performed"] = True
    data["evidence_ledger"] = ledger
    for p in pillars:
        data["pillars"][p]["evidence"] = 3
        data["pillars"][p]["behaviors"] = [{"kind": "paid_test", "description": "Fixture only", "observed_at": "2026-10-22",
                                            "source_or_artifact": "receipt.txt", "verified": True, "ledger_event_id": event_id}]
    return data


def back_core(base, data, stamp="r"):
    """Bring data to Proceed: three distinct signed passing receipts in base for the five core pillars, re-assessed after them."""
    import datetime as dt
    import gf_materials
    data.setdefault("evaluation_id", "eval-fixture0")
    data["execution"]["customer_validation_performed"] = True
    data["evidence_ledger"] = "experiment-ledger.jsonl"
    bind = {**gf_materials.binding(data, base), "result": "pass"}
    events = []
    for i, group in enumerate((("problem", "market"), ("value", "economics"), ("distribution",))):
        name = f"{stamp}{i}.txt"
        (pathlib.Path(base) / name).write_text(f"SYNTHETIC TEST RECEIPT {stamp}{i}")
        event = attest(pathlib.Path(base) / "experiment-ledger.jsonl", "paid_test", data["project"]["name"], "Test measurable intent", outcome="synthetic fixture",
                       artifact=name, attester="Human Fixture", pillars=list(group), observed_at="2026-10-22", extra=bind)
        events.append(event)
        for p in group:
            data["pillars"][p]["evidence"] = 3
            data["pillars"][p]["behaviors"] = [{"kind": "paid_test", "description": "Fixture only", "observed_at": "2026-10-22",
                                                "source_or_artifact": name, "verified": True, "ledger_event_id": event["id"]}]
    later = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=1)).isoformat()
    for p in scorer.PILLAR_WEIGHTS:
        item = data["pillars"][p]
        item["assessed_at"] = later
        if p not in scorer.CORE and (item.get("quality") or 0) > 3:
            item["quality"] = 3  # no receipt, so the rubric caps it
    return events


def sample():
    data = copy.deepcopy(TEMPLATE)
    data["as_of"] = "2026-10-23"
    data["project"] = {"name": "Fixture", "idea": "Test concept", "initial_customer": "Small B2B buyers", "geography": "US", "business_type": "B2B SaaS", "goal": "bootstrapped"}
    data["execution"]["web_used"] = True
    data["execution"]["mode"] = "single-agent fallback"
    for p in scorer.PILLAR_WEIGHTS:
        data["pillars"][p]["quality"] = 4
        data["pillars"][p]["evidence"] = 1
    return data


class PolicyTests(unittest.TestCase):
    def test_template_requires_research(self):
        errors, warnings = scorer.validate(TEMPLATE)
        self.assertEqual(errors, [])
        decision = scorer.score(copy.deepcopy(TEMPLATE), warnings)
        self.assertEqual(decision["decision"], "RESEARCH_INCOMPLETE")
        self.assertIsNone(decision["weighted_quality_0_to_100"])

    def test_high_quality_without_behavior_is_not_go(self):
        data = sample()
        errors, warnings = scorer.validate(data)
        self.assertFalse(errors, errors)
        result = scorer.score(data, warnings)
        self.assertEqual(result["weighted_quality_0_to_100"], 60.0)  # research alone tops out at 3 of 5 per pillar
        self.assertEqual(result["decision"], "VALIDATE_BEFORE_BUILD")

    def test_claimed_high_evidence_requires_observation(self):
        data = sample()
        data["pillars"]["problem"]["evidence"] = 3
        errors, _ = scorer.validate(data)
        self.assertTrue(any("pillars.problem" in e and "behavior" in e for e in errors))

    def test_documented_core_behavior_allows_bounded_pilot(self):
        data=sample()
        with tempfile.TemporaryDirectory() as d:
            back_core(pathlib.Path(d),data)
            errors,warnings=scorer.validate(data,pathlib.Path(d))
            self.assertFalse(errors,errors)
            self.assertEqual(scorer.score(data,warnings)['decision'],'PROCEED_TO_BOUNDED_PILOT')

    def test_missing_or_wrong_schema_version_rejected(self):
        # Regression: without schema_version the ledger-receipt and
        # source-review checks were skipped, so fabricated "verified"
        # behaviors and pilot gates reached PROCEED_TO_BOUNDED_PILOT.
        data = sample()
        data["claims"] = [{"id": "C1", "pillar": "problem", "classification": "fact", "statement": "x",
                           "source_url": "https://example.com", "accessed_date": "2026-11-01"}]
        for p in scorer.PILLAR_WEIGHTS:
            data["pillars"][p].update(quality=5, evidence=5, finding="fabricated", claim_ids=["C1"],
                behaviors=[{"kind": "payment", "description": "fake", "observed_at": "2026-11-01",
                            "source_or_artifact": "fake.txt", "verified": True}])
        data["pilot_gates"] = {g: {"passed": True, "evidence_ids": ["EV-FAKE"]}
                               for g in scorer.PROFILES["general"]["pilot_gates"]}
        for version in (None, "1.0", 2, "2"):
            with self.subTest(version=version):
                d = copy.deepcopy(data)
                if version is None:
                    d.pop("schema_version", None)
                else:
                    d["schema_version"] = version
                errors, _ = scorer.validate(d)
                self.assertTrue(any("schema_version" in e for e in errors), errors)
                self.assertTrue(any("ledger receipt" in e for e in errors), errors)

    def test_confirmed_fatal_vetoes(self):
        data = sample()
        data["claims"] = [{"id": "C1", "pillar": "execution", "classification": "fact", "statement": "Example prohibition", "source_url": "https://example.org/rule", "source_title": "Example", "accessed_date": "2026-10-23"}]
        data["hard_blockers"] = [{"id": "R1", "fatal": True, "status": "confirmed", "finding": "Illustrative regulatory prohibition", "source_ids": ["C1"], "mitigation": "none"}]
        errors, warnings = scorer.validate(data)
        self.assertFalse(errors, errors)
        self.assertEqual(scorer.score(data, warnings)["decision"], "NO_GO")

    def test_unsourced_fatal_rejected(self):
        data = sample()
        data["hard_blockers"] = [{"id": "R1", "fatal": True, "status": "confirmed", "finding": "unsupported claim", "source_ids": [], "mitigation": "none"}]
        errors, _ = scorer.validate(data)
        self.assertTrue(any("confirmed fatal" in e for e in errors))

    def test_factual_claim_requires_provenance(self):
        data = sample()
        data["claims"] = [{"id": "C1", "pillar": "market", "classification": "fact", "statement": "There are billions of buyers", "source_url": ""}]
        errors, _ = scorer.validate(data)
        self.assertTrue(any("facts require" in e for e in errors))

    def test_invalid_market_range(self):
        data = sample()
        data["market_model"]["tam"].update({"low": 10, "base": 5, "high": 40})
        errors, _ = scorer.validate(data)
        self.assertTrue(any("low <= base" in e for e in errors))


class PackageTests(unittest.TestCase):
    def test_install_both(self):
        with tempfile.TemporaryDirectory() as directory:
            proc = subprocess.run([sys.executable, str(ROOT / "install.py"), "--platform", "both", "--project", directory], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            root = pathlib.Path(directory)
            self.assertTrue((root / ".claude/skills/greenfield-business-evaluator/SKILL.md").exists())
            self.assertTrue((root / ".agents/skills/greenfield-business-evaluator/SKILL.md").exists())
            self.assertEqual(len(list((root / ".claude/agents").glob("gf-*.md"))), 9)
            self.assertEqual(len(list((root / ".codex/agents").glob("gf-*.toml"))), 9)
            self.assertEqual(subprocess.run([sys.executable, str(ROOT / "install.py"), "--platform", "both", "--project", directory], capture_output=True).returncode, 2)

    def test_portable_skill_frontmatter(self):
        text = (ROOT / "skill/SKILL.md").read_text()
        self.assertTrue(text.startswith("---\nname: greenfield-business-evaluator\n"))
        self.assertIn("description:", text.partition("---\n")[2])

    def test_codex_roles_valid_toml(self):
        import tomllib
        for path in (ROOT / "platform/codex/agents").glob("gf-*.toml"):
            doc = tomllib.loads(path.read_text())
            self.assertTrue(all(k in doc for k in ("name", "description", "developer_instructions")), path.name)
            self.assertTrue(doc["name"].startswith("gf_"))


if __name__ == "__main__":
    unittest.main()
