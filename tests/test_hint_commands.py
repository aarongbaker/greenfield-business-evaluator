"""Every `greenfield ...` command the code prints names a real subcommand and real flags."""
import argparse
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skill" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import cli  # noqa: E402

FILES = [*(f for f in SCRIPTS.glob("*.py") if f.name != "cli.py"),  # cli.py examples are templated
         ROOT / "skill" / "assets" / "mission-control.html"]
CMD = re.compile(r"(?<![\w-])greenfield ((?:[\w./-]+ ?)+)")


def check(argv, parser):
    """Walk subcommands, then check each --flag exists on the leaf; return an error string or None."""
    for i, tok in enumerate(argv):
        sub = next((a for a in parser._actions if isinstance(a, argparse._SubParsersAction)), None)
        if tok.startswith("-") or tok == "x" or sub is None:  # "x" is a template field
            break
        if tok not in sub.choices:
            return None if i == 0 else f"unknown subcommand {tok!r}"  # first word may be prose
        parser = sub.choices[tok]
    flags = {o for a in parser._actions for o in a.option_strings}
    bad = [t for t in argv if t.startswith("--") and t not in flags]
    return f"unknown option {bad[0]}" if bad else None


class HintCommands(unittest.TestCase):
    def test_printed_commands_exist(self):
        root, seen = cli.build_parser(), 0
        top = next(a for a in root._actions if isinstance(a, argparse._SubParsersAction)).choices
        for f in FILES:
            text = re.sub(r"\{[^{}]*\}", "x", f.read_text(encoding="utf-8"))  # f-string fields
            for m in CMD.finditer(text):
                argv = m.group(1).split()
                if argv[0] not in top:
                    continue  # prose such as "greenfield is ..."
                with self.subTest(file=f.name, cmd=m.group(0)):
                    self.assertIsNone(check(argv, root))
                seen += 1
        self.assertGreater(seen, 10)


if __name__ == "__main__":
    unittest.main()
