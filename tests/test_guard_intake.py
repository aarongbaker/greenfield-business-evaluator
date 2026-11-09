"""W47: the guard covers intake commands, signed files and materials/raw. Friction only; the tty and HMAC are the locks."""
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "skill/scripts"))
import gf_guard as g


class Guard(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = pathlib.Path(t.name).resolve()
        self.run_dir = self.root / "research/greenfield/idea"
        (self.run_dir / "materials/raw").mkdir(parents=True)
        (self.run_dir / "receipts").mkdir()
        (self.run_dir / "evaluation.json").write_text("{}")

    def decide(self, tool, **inp):
        return g.decide(tool, inp, str(self.root))

    def test_denied_commands(self):
        for cmd in ('sh -c "greenfield evidence add x --as presale --attester me"', "greenfield evidence redact materials/raw/x.csv --mask emails",
                    "greenfield ledger reattest", "greenfield ledger reidea", "cat materials/raw/x.csv", "cp a/experiment-ledger.jsonl b/",
                    "script -q /dev/null greenfield evidence add x", "unbuffer greenfield ledger record --kind source_review --attester me",
                    "expect -c 'spawn greenfield evidence add x'", """python3 -c "import pty; pty.spawn(['greenfield','evidence','add','x'])\"""", "echo x > receipts/fake.txt"):
            with self.subTest(cmd):
                self.assertTrue(self.decide("Bash", command=cmd))

    def test_allowed_commands(self):
        for cmd in ("grep -r receipts docs/", "greenfield evidence link EV-1", "greenfield ledger verify --ledger experiment-ledger.jsonl",
                    "greenfield task coverage --verification-report x/source-verification.json", "greenfield ledger record --ledger experiment-ledger.jsonl --kind hypothesis",
                    "greenfield sources check --output source-verification.json", "python3 script.py"):  # script.py importing gf_ledger: known bypass, documented
            with self.subTest(cmd):
                self.assertIsNone(self.decide("Bash", command=cmd))

    def test_file_tools(self):
        for name in ("receipts/x", "quality-history.jsonl", "source-verification.json", "materials/raw/x.csv"):
            with self.subTest(name):
                self.assertTrue(self.decide("Write", file_path=str(self.run_dir / name)))
        self.assertIsNone(self.decide("Write", file_path=str(self.root / "src/receipts/views.py")))

    def test_reads(self):
        raw = str(self.run_dir / "materials/raw/x.csv")
        self.assertEqual(self.decide("Read", file_path=raw), g.RAW_DENIED)
        self.assertEqual(self.decide("Grep", path=str(self.run_dir / "materials/raw"), pattern="a"), g.RAW_DENIED)
        self.assertEqual(self.decide("Grep", path=str(self.run_dir), pattern="a"), g.RAW_DENIED)
        self.assertEqual(self.decide("Glob", pattern="materials/*/x.csv"), g.RAW_DENIED)
        self.assertIsNone(self.decide("Read", file_path=str(self.run_dir / "experiment-ledger.jsonl")))
        self.assertIsNone(self.decide("Glob", pattern="src/**/*.py"))


if __name__ == "__main__":
    unittest.main()
