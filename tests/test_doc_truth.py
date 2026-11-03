"""Doc-truth checks: the README and OBSERVABILITY.md must not repeat known-false statements.

Offline and cheap. The full "every README command runs as written" gate replaces this in W28.
"""

import ast
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKILL = ROOT / "skill"
README = ROOT / "README.md"
OBSERVABILITY = ROOT / "OBSERVABILITY.md"
DOCS = [README, OBSERVABILITY]

# Phrases that were false (or are stale) and must not come back.
STALE_PHRASES = ["do not make network requests", "extracted bundle", "succcess", "3.10"]

# Markdown files whose Python floor must read 3.11.
FLOOR_MARKDOWN = DOCS + [SKILL / "SKILL.md", SKILL / "references" / "v2-workflows.md"]
# Python entry points whose module docstring must read 3.11.
FLOOR_SCRIPTS = sorted((SKILL / "scripts").glob("*.py")) + [ROOT / "install.py", ROOT / "configure_hooks.py"]


def section(text, heading):
    """Return the body of a Markdown section (from its heading to the next heading of the same or higher level)."""
    match = re.search(rf"^(#+) {re.escape(heading)}\n(.*?)(?=^\1 |\Z)", text, re.S | re.M)
    return match.group(2) if match else ""


class DocTruthTests(unittest.TestCase):
    def test_no_stale_phrases_in_readme_or_observability(self):
        for doc in DOCS:
            text = doc.read_text(encoding="utf-8")
            for phrase in STALE_PHRASES:
                with self.subTest(doc=doc.name, phrase=phrase):
                    self.assertNotIn(phrase, text)

    def test_python_floor_is_3_11_everywhere(self):
        for doc in FLOOR_MARKDOWN:
            with self.subTest(doc=doc.name):
                self.assertNotIn("3.10", doc.read_text(encoding="utf-8"))
        for doc in DOCS:
            with self.subTest(doc=doc.name):
                self.assertIn("Python 3.11+", doc.read_text(encoding="utf-8"))
        for script in FLOOR_SCRIPTS:
            with self.subTest(script=script.name):
                docstring = ast.get_docstring(ast.parse(script.read_text(encoding="utf-8"))) or ""
                self.assertNotIn("3.10", docstring)

    def test_readme_installation_works_from_a_fresh_clone(self):
        installation = section(README.read_text(encoding="utf-8"), "Installation")
        self.assertIn("git clone https://github.com/aarongbaker/greenfield-business-evaluator.git", installation)
        self.assertIn("cd greenfield-business-evaluator", installation)

    def test_scripts_named_in_docs_exist(self):
        for doc in DOCS:
            text = doc.read_text(encoding="utf-8")
            for name in set(re.findall(r"(?<![\w/])(install|configure_hooks)\.py\b", text)):
                with self.subTest(doc=doc.name, script=name):
                    self.assertTrue((ROOT / f"{name}.py").is_file())
            for name in set(re.findall(r"scripts/([A-Za-z0-9_]+\.py)", text)):
                with self.subTest(doc=doc.name, script=name):
                    self.assertTrue((SKILL / "scripts" / name).is_file())


if __name__ == "__main__":
    unittest.main()
