import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "skill" / "assets" / "demo-research"


class DemoResearchTest(unittest.TestCase):
    def test_sample_scores_without_errors(self):
        r = subprocess.run(
            [sys.executable, str(ROOT / "skill/scripts/score_project.py"), str(DEMO / "evaluation.json"), "--json"],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("ERROR", r.stderr)
        self.assertEqual(json.loads(r.stdout)["decision"], "VALIDATE_BEFORE_BUILD")

    def test_labelled_sample(self):
        p = json.loads((DEMO / "evaluation.json").read_text())["project"]
        self.assertIn("SAMPLE DATA", p["name"])
        self.assertIn("SAMPLE DATA", p["idea"])
        self.assertTrue((DEMO / "README.md").exists())


if __name__ == "__main__":
    unittest.main()
