"""W55: the skill's instructions never tell the agent to attest, hand-write ledger_event_id or assessed_at."""
from pathlib import Path
import re
import unittest

SKILL = Path(__file__).resolve().parent.parent / "skill"
FILES = [SKILL / "SKILL.md", *sorted((SKILL / "references").glob("*.md"))]
FENCE = re.compile(r"^```\w*\n(.*?)^```", re.S | re.M)


def sentences(text):
    return re.split(r"(?<=[.;])\s+", FENCE.sub("", text))


class SkillLint(unittest.TestCase):
    def test_attester_commands_are_for_the_founder(self):
        for f in FILES:
            for block in FENCE.findall(f.read_text(encoding="utf-8")):
                if "--attester" in block:
                    with self.subTest(file=f.name):
                        self.assertIn("founder", block, "an --attester command must be printed for the founder, not run")

    def test_no_hand_written_ledger_event_id_or_assessed_at(self):
        for f in FILES:
            for s in sentences(f.read_text(encoding="utf-8")):
                if re.search(r"\b(put|write|place|type|set)\b", s, re.I) and re.search(r"ledger_event_id|assessed_at", s):
                    with self.subTest(file=f.name, sentence=s[:120]):
                        self.assertRegex(s, r"\b[Nn]ever\b")

    def test_keeps_evaluation_id_and_stamps_with_evidence_assessed(self):
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("keep `evaluation_id` unchanged", text)
        self.assertIn("greenfield evidence assessed", text)
        self.assertIn("materials/inbox/", text)
        self.assertIn("Never read `materials/raw/`", text)


if __name__ == "__main__":
    unittest.main()
