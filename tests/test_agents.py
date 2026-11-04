import re, subprocess, sys, tempfile, tomllib, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
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
        with tempfile.TemporaryDirectory() as t:
            out = Path(t)
            for p in ('claude', 'codex'):
                (out / 'platform' / p / 'agents').mkdir(parents=True)
            make_agents.generate(out)
            for f in (ROOT / 'platform').glob('*/agents/gf-*'):
                self.assertEqual(f.read_bytes(), (out / f.relative_to(ROOT)).read_bytes(), f.name)


if __name__ == '__main__':
    unittest.main()
