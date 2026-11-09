"""W7 never-throws fuzz test (standard library only).

GF_FUZZ_ITERATIONS (cases per seed, default 2000) and GF_FUZZ_SEED allow long local runs.
A failure prints the seed, case number and mutated JSON so it can be replayed.
"""
import contextlib
import copy
import json
import os
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / 'skill' / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import gf_ledger
import score_project as scorer
from test_skill import back_core

ITERATIONS = int(os.environ.get('GF_FUZZ_ITERATIONS', '2000'))
SEED = int(os.environ.get('GF_FUZZ_SEED', '20261103'))
CLI_SAMPLES = 25  # per seed, so 50 CLI runs in all
VERDICTS = {'NO_GO', 'PIVOT', 'RESEARCH_INCOMPLETE', 'VALIDATE_BEFORE_BUILD', 'PROCEED_TO_BOUNDED_PILOT'}


def _claim(**kw):
    c = {'id': 'C1', 'pillar': 'market', 'classification': 'fact', 'statement': 'x',
         'source_url': 'https://example.org/a', 'accessed_date': '2026-10-23'}
    c.update(kw)
    return c


# Audited crash inputs (security review M3 probes + code audit A5): (path, value) edits.
CRASHES = {
    'business_model_list': [(('project', 'business_model'), [1])],
    'business_model_empty_list': [(('project', 'business_model'), [])],
    'claim_pillar_list': [(('claims',), [_claim(pillar=['x'])])],
    'claim_classification_dict': [(('claims',), [_claim(classification={})])],
    'blocker_status_list': [(('hard_blockers',), [{'id': 'R1', 'fatal': True, 'status': [1], 'finding': 'x', 'source_ids': []}])],
    'claim_ids_nested_list': [(('pillars', 'market', 'claim_ids'), [['x']])],
    'non_dict_claim_with_ledger_and_report': [(('claims',), ['x']), (('evidence_ledger',), 'ledger.jsonl'),
                                              (('verification_report',), 'report.json')],
    'pillars_list': [(('pillars',), [])],
    'project_string': [(('project',), 'x')],
    'quality_bool': [(('pillars', 'market', 'quality'), True)],
    'gate_evidence_ids_int': [(('project', 'business_model'), 'services'),
                              (('pilot_gates',), {'paid_engagement': {'passed': True, 'evidence_ids': 5}})],
    'ledger_path_list': [(('evidence_ledger',), [1]), (('verification_report',), 'report.json')],
    'ledger_path_nul': [(('evidence_ledger',), 'a\x00b')],
    'bad_ipv6_url': [(('claims',), [_claim(source_url='http://[')])],
    'huge_int_market': [(('market_model',), {'tam': {'low': 10 ** 400, 'base': 1, 'high': 2}})],
}


def set_path(data, path, value):
    node = data
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value


@contextlib.contextmanager
def seeded():
    """Temp folder with a signing key, receipt, ledger and report; yields (base, {name: evaluation}) for the two seeds."""
    with tempfile.TemporaryDirectory() as t:
        base = Path(t)
        (base / 'attest.key').write_bytes(os.urandom(32))
        with mock.patch.dict(os.environ, {'GF_ATTEST_KEY_FILE': str(base / 'attest.key')}):
            yield base, make_seeds(base)


def make_seeds(base):
    template = json.loads((ROOT / 'skill/assets/evaluation-template.json').read_text(encoding='utf-8'))
    proceed = json.loads((ROOT / 'tests/fixtures/validate-before-build.json').read_text(encoding='utf-8'))
    (base / 'report.json').write_text('{"claims": []}')
    back_core(base, proceed)
    template['evaluation_id'] = proceed['evaluation_id']
    return {'template': template, 'proceed': proceed}


def paths(node, prefix=()):
    yield prefix
    if isinstance(node, dict):
        for k, v in node.items():
            yield from paths(v, prefix + (k,))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from paths(v, prefix + (i,))


def get(node, path):
    for key in path:
        node = node[key]
    return node


def random_value(rng, depth=0):
    choices = [None, True, False, rng.randint(-10, 10), 10 ** 400, rng.choice([-0.5, 2.5, 1e308, 0.0]),
               rng.choice(['', ' ', 'x', 'fact', 'market', 'confirmed', 'general', 'services', 'EV-' + 'f' * 12,
                           '../../outside.jsonl', 'http://[', 'https://example.org', '2026-10-23', 'é‮', 'y' * 500]),
               [], {}]
    if depth < 2:
        choices += [[random_value(rng, depth + 1)], {'k': random_value(rng, depth + 1)}]
    return rng.choice(choices)


def mutate(rng, data):
    for _ in range(rng.randint(1, 5)):
        op = rng.randrange(4)
        all_paths = list(paths(data))
        if op == 0:  # replace a node
            path = rng.choice(all_paths[1:])
            set_path(data, path, random_value(rng))
        elif op in (1, 2):
            dicts = [p for p in all_paths if isinstance(get(data, p), dict)]
            node = get(data, rng.choice(dicts))
            if op == 1 and node:  # delete a key
                del node[rng.choice(list(node))]
            else:  # add an unknown key
                node['unknown_' + str(rng.randrange(100))] = random_value(rng)
        elif isinstance(data.get('claims'), list):  # duplicate a claim id
            claims = data['claims']
            if not any(isinstance(c, dict) for c in claims):
                claims.append(_claim())
            claims.append(copy.deepcopy(rng.choice([c for c in claims if isinstance(c, dict)])))
    return data


def receipts_verify(data, base):
    """Independent oracle: PROCEED is only allowed when every core pillar and every passed gate has an intact receipt."""
    ledger = base / data['evidence_ledger']
    for p in scorer.CORE:
        # Decision 5: a receipt counts from its signed pillar_ids, linked from evaluation.json or not.
        if not any(p in e.get('pillar_ids', []) and gf_ledger.verified_behavior(ledger, e['id'], p)[0] for e in gf_ledger.read_ledger(ledger)):
            return False
    profile = scorer.PROFILES[data['project'].get('business_model', 'general')]
    for gate in profile['pilot_gates']:
        ids = data['pilot_gates'][gate]['evidence_ids']
        # The fixture ledger holds no source reviews, so only EV- receipts can back a gate.
        if not all(isinstance(e, str) and e.startswith('EV-') and gf_ledger.verified_behavior(ledger, e)[0] for e in ids):
            return False
    return True


def run_cli(data, base):
    p = base / 'evaluation.json'
    p.write_text(json.dumps(data))
    return subprocess.run([sys.executable, str(SCRIPTS / 'score_project.py'), str(p)], capture_output=True, text=True)


class FuzzTests(unittest.TestCase):
    def check(self, data, base, label):
        def fail(msg):
            self.fail(f'{label}: {msg}\nreplay: GF_FUZZ_SEED={SEED}\n{json.dumps(data, default=repr)[:20000]}')
        try:
            errors, warnings = scorer.validate(copy.deepcopy(data), base)
        except Exception as exc:
            fail(f'validate() raised {type(exc).__name__}: {exc}')
        if not (isinstance(errors, list) and isinstance(warnings, list) and all(isinstance(e, str) for e in errors + warnings)):
            fail('validate() must return (list[str], list[str])')
        if errors:
            return errors
        try:
            result = scorer.score(copy.deepcopy(data), warnings)
        except Exception as exc:
            fail(f'score() raised {type(exc).__name__}: {exc}')
        if result['decision'] not in VERDICTS:
            fail('unknown decision ' + repr(result['decision']))
        if result['decision'] == 'PROCEED_TO_BOUNDED_PILOT' and not receipts_verify(data, base):
            fail('PROCEED_TO_BOUNDED_PILOT without intact receipts')
        return errors

    def test_seeds_score_as_expected(self):
        with seeded() as (base, seeds):
            for name, want in (('template', 'RESEARCH_INCOMPLETE'), ('proceed', 'PROCEED_TO_BOUNDED_PILOT')):
                errors, warnings = scorer.validate(copy.deepcopy(seeds[name]), base)
                self.assertFalse(errors, errors)
                self.assertEqual(scorer.score(copy.deepcopy(seeds[name]), warnings)['decision'], want)

    def test_audited_crash_inputs(self):
        with seeded() as (base, seeds):
            for seed_name, seed in seeds.items():
                for case, edits in CRASHES.items():
                    with self.subTest(seed=seed_name, case=case):
                        data = copy.deepcopy(seed)
                        for path, value in edits:
                            set_path(data, path, copy.deepcopy(value))
                        self.assertTrue(self.check(data, base, f'{seed_name}/{case}'), 'expected validation errors')
                        if case != 'huge_int_market':  # handled the same in-process; JSON can carry it too
                            r = run_cli(data, base)
                            self.assertEqual(r.returncode, 2, r.stderr)
                            self.assertNotIn('Traceback', r.stderr)

    def test_never_throws(self):
        with seeded() as (base, seeds):
            for n, (name, seed) in enumerate(seeds.items()):
                rng = random.Random(SEED * 10 + n)
                sample = set(rng.sample(range(ITERATIONS), min(CLI_SAMPLES, ITERATIONS)))
                for i in range(ITERATIONS):
                    data = mutate(rng, copy.deepcopy(seed))
                    self.check(data, base, f'{name} case {i}')
                    if i in sample:
                        r = run_cli(data, base)
                        if r.returncode not in (0, 2) or 'Traceback' in r.stderr:
                            self.fail(f'{name} case {i}: CLI exit {r.returncode}\n{r.stderr}\nreplay: GF_FUZZ_SEED={SEED}\n'
                                      + json.dumps(data, default=repr)[:20000])


if __name__ == '__main__':
    unittest.main()
