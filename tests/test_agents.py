import re, subprocess, sys, tomllib, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
import make_agents

TOOLS = ["WebSearch", "WebFetch", "Read", "Grep", "Glob"]
FORBID = {"Bash", "Write", "Edit", "NotebookEdit", "Agent"}


class AgentTests(unittest.TestCase):
    def test_claude_agents_have_research_tools_only(self):
        # A2: without Bash/Write an agent cannot run `gf_ledger.py record --attester ...`.
        files = sorted((ROOT / 'platform/claude/agents').glob('gf-*.md'))
        self.assertEqual(len(files), 9)
        for f in files:
            tools = re.search(r'^tools: (.*)$', f.read_text(encoding='utf-8'), re.M).group(1).split(', ')
            self.assertEqual(tools, TOOLS, f.name)
            self.assertFalse(FORBID & set(tools), f.name)

    def test_codex_agents_read_only_sandbox(self):
        files = sorted((ROOT / 'platform/codex/agents').glob('gf-*.toml'))
        self.assertEqual(len(files), 9)
        for f in files:
            self.assertEqual(tomllib.loads(f.read_text(encoding='utf-8'))['sandbox_mode'], 'read-only', f.name)

    def test_generated_agents_match_committed(self):
        want = make_agents.generate()
        self.assertEqual(len(want), 18)
        for rel, text in want.items():
            self.assertEqual((ROOT / rel).read_bytes(), text.encode('utf-8'), rel)

    def test_check_mode_flags_a_hand_edit(self):
        run = lambda: subprocess.run([sys.executable, str(ROOT / 'tools/make_agents.py'), '--check'], capture_output=True, text=True)
        self.assertEqual(run().returncode, 0)
        f = ROOT / 'platform/claude/agents/gf-market.md'
        orig = f.read_bytes()
        try:
            f.write_bytes(orig + b'x\n')
            r = run()
            self.assertEqual(r.returncode, 1)
            self.assertIn('gf-market.md', r.stderr)
        finally:
            f.write_bytes(orig)

    def test_agents_name_no_hardcoded_skill_paths_or_cli(self):
        for rel, text in make_agents.generate().items():
            self.assertNotIn('.claude/skills', text, rel)
            self.assertNotIn('.agents/skills', text, rel)
            self.assertNotIn('greenfield ', text, rel)


if __name__ == '__main__':
    unittest.main()
