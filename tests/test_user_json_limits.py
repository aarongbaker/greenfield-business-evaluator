"""User/private JSON read through gf_common.load_json: NaN and oversized files are refused in each module."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skill" / "scripts"))

import gf_context  # noqa: E402
import gf_guard  # noqa: E402
import gf_hooks  # noqa: E402
import gf_ledger  # noqa: E402
import gf_portfolio  # noqa: E402
import gf_runs  # noqa: E402
from gf_common import GFError  # noqa: E402

NAN_JSON = '{"claims": [{"claim_id": NaN}]}'


class UserJsonLimitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def write(self, name, text):
        path = self.dir / name
        path.write_text(text)
        return path

    def test_hooks_refuse_nan_settings(self):
        path = self.write("settings.json", '{"hooks": {"Stop": NaN}}')
        with self.assertRaises(GFError) as e:
            gf_hooks.transform(path, "cmd", "install", platform="claude")
        self.assertIn("NaN", str(e.exception))

    def test_runs_refuse_oversized_evaluation(self):
        path = self.write("evaluation.json", '{"claims": [], "pad": "' + "x" * (5 * 1024 * 1024) + '"}')
        with self.assertRaises(GFError) as e:
            gf_runs.coverage(self.dir, "run-1", path)
        self.assertIn("byte limit", str(e.exception))

    def test_ledger_refuses_nan_report(self):
        report = self.write("report.json", NAN_JSON)
        with mock.patch.object(gf_ledger, "load_key", return_value=None):
            with self.assertRaises(GFError) as e:
                gf_ledger.reviewed_claims(self.dir / "ledger.jsonl", report.name)
        self.assertIn("NaN", str(e.exception))

    def test_guard_fails_open_on_nan_evaluation(self):
        evaluation = self.write("evaluation.json", '{"evidence_ledger": NaN}')
        ctx = {"ledger": self.dir / "ledger.jsonl", "evaluation": evaluation}
        with mock.patch.object(gf_context, "run_context", return_value=ctx):
            paths = gf_guard.protected_paths(self.dir)
        self.assertIn(Path(self.dir / "ledger.jsonl").resolve(), paths)
        self.assertNotIn(Path(self.dir / "evidence.jsonl").resolve(), paths)

    def test_portfolio_refuses_nan_manifest(self):
        manifest = self.write("manifest.json", '{"opportunities": [NaN]}')
        with self.assertRaises(GFError) as e:
            gf_portfolio.run(manifest, self.dir / "out.json")
        self.assertIn("NaN", str(e.exception))
        self.assertFalse((self.dir / "out.json").exists())


if __name__ == "__main__":
    unittest.main()
