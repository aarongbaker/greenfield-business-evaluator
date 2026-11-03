"""Every `greenfield.py` line in SKILL.md and references parses with the real parser (W27; W28 reuses doc_commands for the README)."""
import re
import shlex
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skill" / "scripts"))
import cli  # noqa: E402

DOCS = [ROOT / "skill" / "SKILL.md", *sorted((ROOT / "skill" / "references").glob("*.md"))]
PLACEHOLDER = {"evaluation.json": "evaluation.json", "decision.json": "decision.json", "repo": ".", "folder": "research/x", "slug": "x",
               "short idea": "idea", "idea": "idea", "YOUR_BLENDED_RATE": "5", "evaluation.json>": "evaluation.json"}


def doc_commands(path):
    """argv lists (after `greenfield.py`) for every command in the file, backslash continuations joined, placeholders filled."""
    text = re.sub(r"\\\n\s*", " ", path.read_text(encoding="utf-8"))
    for m in re.finditer(r"python3 <skill dir>/scripts/greenfield\.py ([^`\n]+)", text):
        raw = re.sub(r"<([^>]+)>", lambda g: PLACEHOLDER.get(g.group(1), "x"), m.group(1))
        yield shlex.split(raw.split(" # ")[0])


class DocCliTests(unittest.TestCase):
    def test_no_script_form_commands_remain(self):
        for f in DOCS:
            self.assertNotRegex(f.read_text(encoding="utf-8"), r"python3 (<skill>|<skill-path>|scripts)/", f.name)

    def test_every_doc_command_parses_and_passes_json(self):
        parser, seen = cli.build_parser(), 0
        for f in DOCS:
            for argv in doc_commands(f):
                with self.subTest(file=f.name, argv=argv):
                    try:
                        parser.parse_args(argv)
                    except SystemExit:
                        self.fail("does not parse")
                    if "dashboard" not in argv:  # the server prints no JSON
                        self.assertIn("--json", argv)
                seen += 1
        self.assertGreater(seen, 15)


if __name__ == "__main__":
    unittest.main()
