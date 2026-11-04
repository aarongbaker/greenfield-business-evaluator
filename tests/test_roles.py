import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'skill/scripts'))
import gf_roles as r
import gf_profiles
import gf_observe
import gf_runs

LEGACY="^gf[-_](problem|market|competition|economics|value|distribution|execution|timing|redteam)$"


class RoleTests(unittest.TestCase):
    def test_table(self):
        self.assertEqual(len(r.ROLES),9)
        self.assertEqual(len({x.key for x in r.ROLES}),9)
        self.assertEqual(len({x.display for x in r.ROLES}),9)
        self.assertEqual([x.key for x in r.ROLES if x.pillar is None],['redteam'])
        self.assertEqual([x.pillar for x in r.SPECIALISTS],list(gf_profiles.BASE))
    def test_observe_agents(self):
        self.assertEqual(gf_observe.AGENTS,[x.claude_id for x in r.ROLES])
    def test_coverage_order(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);rid=gf_observe.new_run(root,'x');gf_runs.plan(root,rid)
            ev=root/'e.json';ev.write_text(json.dumps({'claims':[],'pillars':{}}))
            self.assertEqual(list(gf_runs.coverage(root,rid,ev)),[x.pillar for x in r.SPECIALISTS])
    def test_matcher(self):
        m=r.hook_matcher();self.assertEqual(m,LEGACY)
        for x in r.ROLES:
            self.assertTrue(re.match(m,x.claude_id));self.assertTrue(re.match(m,x.codex_id))
        for bad in ('gf-other','xgf-market','gf-market-2'):self.assertIsNone(re.match(m,bad))
    def test_normalize(self):
        for x in r.ROLES:
            self.assertIs(r.normalize(x.claude_id),x);self.assertIs(r.normalize(x.codex_id.upper()),x)
        self.assertIsNone(r.normalize('gf-nope'));self.assertIsNone(r.normalize(None))
    def test_generated_files(self):
        for x in r.ROLES:
            md=(ROOT/'platform/claude/agents'/f'{x.claude_id}.md').read_text(encoding='utf-8')
            self.assertIn(f'\n# {x.display}\n',md)
            toml=(ROOT/'platform/codex/agents'/f'{x.claude_id}.toml').read_text(encoding='utf-8')
            self.assertIn(f'name = "{x.codex_id}"',toml)
    def test_readme(self):
        text=(ROOT/'README.md').read_text(encoding='utf-8')
        for x in r.ROLES:
            self.assertIn(f'| {x.display} | `{x.claude_id}` |',text)
    def test_state_roles(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);rid=gf_observe.new_run(root,'x')
            roles=gf_observe.current_state(root,rid)['roles']
            self.assertEqual(len(roles),9);self.assertEqual(roles[2],{'id':'gf-value','name':'Customer Value','pillar':'value'})


if __name__=='__main__':unittest.main()
