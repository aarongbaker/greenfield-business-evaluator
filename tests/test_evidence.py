"""W45/W46: bringing your own materials. The terminal confirmation is injected; everything else is the real CLI path."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skill/scripts"))
import cli
import gf_ledger
import gf_materials
import score_project


class Base(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name).resolve()
        env = mock.patch.dict(os.environ, {"GF_ATTEST_KEY_FILE": str(self.root / "key"), "GF_CONFIG_DIR": str(self.root / "cfg")})
        env.start()
        self.addCleanup(env.stop)
        conf = mock.patch.object(gf_ledger, "tty_confirm", lambda s: gf_ledger.ensure_key())
        conf.start()
        self.addCleanup(conf.stop)
        cwd = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, cwd)

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["--json", *argv, "--project", str(self.root)] if argv[0] == "start" else ["--json", *argv])
        return code, out.getvalue(), err.getvalue()

    def start(self, model="bootstrapped_saas", slug="idea"):
        code, out, err = self.run_cli("start", "--idea", "Books for dentists", "--model", model, "--slug", slug, "--no-plan", "--new")
        self.assertEqual(code, 0, err)
        self.folder = self.root / "research/greenfield" / slug
        self.ev = self.folder / "evaluation.json"
        data = self.data()
        data["experiments"] = [{"id": "EXP-2", "pillars": ["value", "economics"], "hypothesis": "They pay", "success_threshold": "3 of 10"}]
        self.ev.write_text(json.dumps(data))

    def data(self):
        return json.loads(self.ev.read_text())

    def csv(self, name="stripe.csv", body="amount,plan\n49,a\n49,b\n"):
        p = self.root / name
        p.write_text(body)
        return p

    def add(self, file, *extra, mat="presale", result="pass"):
        return self.run_cli("evidence", "add", str(file), "--as", mat, "--result", result, "--consent", "customer_terms", "--attester", "X", "--evaluation", str(self.ev), *extra)


class AddTests(Base):
    def test_dates_are_not_phone_numbers(self):
        f = self.root / "w.csv"
        f.write_text("signed_up,amount\n2026-11-01,49\n2026-11-02 10:30,49\n")
        self.assertEqual(gf_materials.pii_found(f), [])
        f.write_text("signed_up,contact\n2026-11-01,+1 (415) 555-0134\n")
        self.assertEqual(gf_materials.pii_found(f), ["phones"])

    def test_docs_example_matches_a_recorded_receipt(self):  # W53: docs/evidence.md shows what evidence add writes
        import re
        doc = (Path(__file__).resolve().parent.parent / "docs" / "evidence.md").read_text()
        shown = json.loads(re.search(r"```json\n(.*?)```", doc, re.S).group(1))
        self.start()
        self.assertEqual(self.add(self.csv(), "--pillar", "value", "--pillar", "economics", "--gate", "pricing_test", "--experiment", "EXP-2",
                                  "--outcome", "4 of 30 paid $49")[0], 0)
        d = self.data()
        got = d["pillars"]["value"]["behaviors"][0]
        self.assertEqual(set(got), set(shown["behaviors"][0]))
        self.assertEqual((got["kind"], got["description"], d["pillars"]["value"]["evidence"]), (shown["behaviors"][0]["kind"], "4 of 30 paid $49", 4))
        self.assertEqual(set(d["pilot_gates"]["pricing_test"]), set(next(iter(shown["pilot_gates"].values()))))

    def test_presale_links_pillars_and_gate_and_leaves_quality(self):
        self.start()
        before = self.data()["pillars"]["value"]["quality"]
        code, out, err = self.add(self.csv(), "--pillar", "value", "--pillar", "economics", "--gate", "pricing_test", "--experiment", "EXP-2")
        self.assertEqual(code, 0, err)
        d = self.data()
        self.assertEqual((d["pillars"]["value"]["evidence"], d["pillars"]["economics"]["evidence"]), (4, 4))
        self.assertEqual(d["pillars"]["value"]["quality"], before)
        self.assertTrue(d["pilot_gates"]["pricing_test"]["passed"])
        e = gf_ledger.read_ledger(self.folder / "experiment-ledger.jsonl")[0]
        self.assertEqual((e["material"], e["result"], e["evaluation_id"]), ("presale", "pass", d["evaluation_id"]))
        self.assertTrue((self.folder / e["artifact"]["path"]).is_file())

    def test_refusals_write_nothing(self):
        self.start("services")
        f = self.csv()
        cases = [(["--pillar", "value", "--gate", "pricing_test", "--experiment", "EXP-2"], "presale", "cannot close"),
                 (["--pillar", "distribution"], "loi", "allowed pillars"),
                 (["--pillar", "value"], "presale", "evidence experiment add"),
                 (["--pillar", "value"], "interviews", "leave it in materials/inbox")]
        for extra, mat, want in cases:
            code, _, err = self.add(f, *extra, mat=mat)
            self.assertEqual(code, 2, (mat, err))
            self.assertIn(want, err)
        self.assertFalse((self.folder / "experiment-ledger.jsonl").exists())

    def test_result_required(self):
        self.start()
        code, _, err = self.run_cli("evidence", "add", str(self.csv()), "--as", "presale", "--pillar", "timing", "--consent", "public", "--attester", "X", "--evaluation", str(self.ev))
        self.assertEqual(code, 2)
        self.assertIn("--result", err)

    def test_failed_gate_is_signed_but_not_linked(self):
        self.start()
        code, _, err = self.add(self.csv(), "--gate", "pricing_test", result="fail")
        self.assertEqual(code, 0, err)
        self.assertFalse((self.data().get("pilot_gates") or {}).get("pricing_test", {}).get("passed"))
        self.assertEqual(gf_ledger.read_ledger(self.folder / "experiment-ledger.jsonl")[0]["gate_ids"], ["pricing_test"])

    def test_one_file_backs_two_core_pillars_at_most(self):
        self.start()
        d = self.data()
        d["experiments"].append({"id": "EXP-3", "pillars": ["problem"], "hypothesis": "Pain"})
        self.ev.write_text(json.dumps(d))
        f = self.csv()
        self.assertEqual(self.add(f, "--pillar", "value", "--pillar", "economics", "--experiment", "EXP-2")[0], 0)
        code, _, err = self.add(f, "--pillar", "problem", "--experiment", "EXP-3")
        self.assertEqual(code, 2)
        self.assertIn("at most 2 core", err)

    def test_appended_export_counts_as_the_same_artifact(self):
        self.start()
        d = self.data()
        d["experiments"].append({"id": "EXP-3", "pillars": ["problem"], "hypothesis": "Pain"})
        self.ev.write_text(json.dumps(d))
        self.add(self.csv("a.csv", "x,y\n" + "".join(f"{i},1\n" for i in range(25))), "--pillar", "value", "--pillar", "economics", "--experiment", "EXP-2")
        code, _, err = self.add(self.csv("b.csv", "x,y\n" + "".join(f"{i},1\n" for i in range(20)) + "90,2\n"), "--pillar", "problem", "--experiment", "EXP-3")
        self.assertEqual(code, 2, err)

    def test_sibling_run_reuse_is_signed(self):
        self.start(slug="one")
        f = self.csv()
        self.add(f, "--pillar", "value", "--pillar", "economics", "--experiment", "EXP-2")
        self.start(slug="two")
        self.assertEqual(self.add(f, "--pillar", "value", "--pillar", "economics", "--experiment", "EXP-2")[0], 0)
        e = gf_ledger.read_ledger(self.folder / "experiment-ledger.jsonl")[0]
        self.assertTrue(e["reused_from"][0].startswith("one/EV-"))

    def test_raw_outside_a_run_is_refused(self):
        self.start()
        (self.root / "materials/raw").mkdir(parents=True)
        f = self.root / "materials/raw/x.csv"
        f.write_text("a\n1\n")
        code, _, err = self.add(f, "--pillar", "timing")
        self.assertEqual(code, 2)
        self.assertIn("outside a run folder", err)

    def test_failed_confirmation_leaves_no_copy(self):
        self.start()
        def no(s):
            raise gf_ledger.GFError("Confirmation code did not match; nothing was recorded")
        with mock.patch.object(gf_ledger, "tty_confirm", no):
            self.assertEqual(self.add(self.csv(), "--pillar", "timing")[0], 2)
        self.assertEqual([p.name for p in (self.folder / "receipts").iterdir() if p.name != ".gitignore"], [])


class PiiTests(Base):
    def test_email_column_refused_then_redacted_copy_accepted(self):
        self.start()
        raw = self.folder / "materials/raw/s.csv"
        raw.write_text("email,amount\na@b.co,49\n")
        code, _, err = self.add(raw, "--pillar", "timing")
        self.assertEqual(code, 2)
        self.assertIn("evidence redact", err)
        code, out, err = self.run_cli("evidence", "redact", str(raw), "--drop-column", "email")
        self.assertEqual(code, 0, err)
        red = self.folder / "materials/inbox/s.redacted.csv"
        self.assertEqual(red.read_text(), "amount\n49\n")
        self.assertEqual(self.add(red, "--pillar", "timing")[0], 0)

    def test_mask_with_no_match_writes_nothing_and_warns_on_names(self):
        self.start()
        raw = self.folder / "materials/raw/t.md"
        raw.write_text("Spoke with Ana Ruiz")
        _, out, _ = self.run_cli("evidence", "redact", str(raw), "--mask", "emails")
        self.assertIn(gf_materials.NAMES_WARNING, out)
        self.assertFalse((self.folder / "materials/inbox/t.redacted.md").exists())

    def test_preview_shows_type_size_rows_and_first_lines(self):
        p = self.csv()
        info = gf_materials._file_preview(p)
        self.assertEqual((info["type"], info["rows"]), ("text/csv", "2"))
        self.assertIn("amount,plan", info["first lines"])

    def test_doctor_flags_inbox_personal_data(self):
        self.start()
        inbox = self.folder / "materials/inbox"
        (inbox / "x.csv").write_text("email\na@b.co\n")
        self.assertTrue(gf_materials.inbox_warnings(self.folder))

    def test_binary_needs_declaration_and_real_magic(self):
        self.start()
        pdf = self.root / "x.pdf"
        pdf.write_bytes(b"PK\x03\x04zip")
        code, _, err = self.add(pdf, "--pillar", "timing", "--redacted")
        self.assertEqual(code, 2)
        self.assertIn("not really", err)
        pdf.write_bytes(b"%PDF-1.4")
        code, _, err = self.add(pdf, "--pillar", "timing")
        self.assertIn("not scanned", err)
        self.assertEqual(self.add(pdf, "--pillar", "timing", "--redacted")[0], 0)

    def test_status_flags_inbox_pii(self):
        self.start()
        (self.folder / "materials/inbox/n.txt").write_text("call me a@b.co")
        _, out, _ = self.run_cli("evidence", "status", "--evaluation", str(self.ev))
        self.assertIn("n.txt", json.loads(out)["warnings"][0])


class SetupTests(Base):
    def test_start_writes_id_and_folders_and_reserves_demo_slug(self):
        self.start()
        self.assertTrue(self.data()["evaluation_id"].startswith("eval-"))
        self.assertTrue((self.folder / "materials/raw").is_dir())
        code, _, err = self.run_cli("start", "--idea", "x", "--slug", "demo-proceed", "--no-plan", "--new")
        self.assertEqual(code, 2, err)

    def test_init_marks_legacy_only_without_an_id_snapshot(self):
        self.start()
        d = self.data()
        d.pop("evaluation_id")
        self.ev.write_text(json.dumps(d))
        gf_ledger.append(self.folder / "experiment-ledger.jsonl", "note", "p", "h")
        _, out, _ = self.run_cli("evidence", "init", "--evaluation", str(self.ev))
        self.assertFalse(json.loads(out)["legacy"])

    def test_experiment_add_and_assessed(self):
        self.start()
        self.assertEqual(self.run_cli("evidence", "experiment", "add", "--id", "EXP-9", "--pillar", "value", "--hypothesis", "h", "--evaluation", str(self.ev))[0], 0)
        self.assertEqual(self.run_cli("evidence", "experiment", "add", "--id", "EXP-9", "--pillar", "value", "--hypothesis", "h", "--evaluation", str(self.ev))[0], 2)
        self.assertEqual(self.run_cli("evidence", "assessed", "value", "--evaluation", str(self.ev))[0], 0)
        self.assertIn("T", self.data()["pillars"]["value"]["assessed_at"])


if __name__ == "__main__":
    unittest.main()
