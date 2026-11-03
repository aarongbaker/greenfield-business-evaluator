import copy
import json
from pathlib import Path
import subprocess
import sys
import os
import stat
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'skill/scripts'))
import gf_ledger as ledger
import gf_evidence as evidence
import gf_profiles as profiles
import gf_runs
import gf_observe
import gf_portfolio
from test_skill import attest,sample,scorer

class LedgerTests(unittest.TestCase):
    def test_behavior_requires_human_and_receipt(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'events.jsonl';receipt=Path(d)/'receipt.txt';receipt.write_text('sample')
            with self.assertRaises(ValueError):attest(p,'paid_test','X','H',artifact='receipt.txt')
            event=attest(p,'paid_test','X','H',artifact='receipt.txt',attester='Test human',pillars=['problem'])
            self.assertTrue(ledger.verified_behavior(p,event['id'],'problem')[0])
            self.assertFalse(ledger.verified_behavior(p,event['id'],'market')[0])
            receipt.write_text('altered')
            self.assertFalse(ledger.verified_behavior(p,event['id'],'problem')[0])
    def test_append_only_tamper_detected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'events.jsonl';ledger.append(p,'hypothesis','X','Pain?')
            ledger.append(p,'failure','X','Pain?',outcome='failed')
            self.assertEqual(len(ledger.read_ledger(p)),2)
            p.write_text(p.read_text().replace('failed','succeeded'))
            with self.assertRaises(ValueError):ledger.read_ledger(p)
    def test_source_review_bound_to_report(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);report=root/'report.json';report.write_text('{"status":"retrieved","claims":[{"claim_id":"C1"}]}')
            p=root/'events.jsonl'
            attest(p,'source_review','X','Claim C1',outcome='supported',artifact='report.json',attester='Human',claim_id='C1')
            self.assertEqual(ledger.reviewed_claims(p,report),{'C1':'supported'})
            report.write_text('{"status":"modified"}')
            self.assertEqual(ledger.reviewed_claims(p,report),{})

class EvidenceTests(unittest.TestCase):
    def test_private_url_rejected(self):
        def resolver(*args,**kwargs):return [(2,1,6,'',('127.0.0.1',80))]
        with self.assertRaises(ValueError):evidence.check_public_url('http://localhost/private')
        with self.assertRaises(ValueError):evidence.check_public_url('http://lookalike.example/private',resolver)
    def test_source_retrieval_and_quote_check(self):
        data={'claims':[{'id':'C1','source_url':'https://example.org/a','independent_origin':'Same Study','statement':'Data support 200 outcomes',
              'supporting_quote':'Data support 200 outcomes','published_date':'2020-01-01'},
              {'id':'C2','source_url':'https://example.org/b','independent_origin':'Same Study','statement':'Another outcome'}]}
        def fixture(_url):return {'url':_url,'content_sha256':'testhash','text':'Data support 200 outcomes in report','bytes':32,'mime':'text/plain'}
        r=evidence.analyze(data,allow_network=True,fetcher=fixture,as_of='2026-10-23')
        self.assertEqual(r['claims'][0]['excerpt_check'],'found')
        self.assertIn('published_older_than_freshness_window',r['claims'][0]['issues'])
        self.assertIn('shared_reported_origin_check_independence',r['claims'][1]['issues'])
        self.assertFalse(r['automated_verification_of_truth'])

class ModelTests(unittest.TestCase):
    def test_profile_weights_distinct_and_sum(self):
        self.assertEqual(len(profiles.PROFILES),6)
        for value in profiles.PROFILES.values():self.assertEqual(sum(value['weights'].values()),100)
    def test_model_pilot_gates_explicit(self):
        d=sample();d['project']['business_model']='marketplace'
        errors,warnings=scorer.validate(d)
        self.assertFalse(errors,errors)
        result=scorer.score(d,warnings)
        self.assertIn('supply_commitments',result['missing_pilot_gates'])
        self.assertEqual(result['business_model_profile'],'marketplace')

class SourceGateTests(unittest.TestCase):
    def test_v2_missing_source_report_blocks_pilot(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);receipt=root/'receipt.txt';receipt.write_text('Synthetic fixture')
            event=attest(root/'experiment-ledger.jsonl','paid_test','A','H',artifact='receipt.txt',
                                attester='Human test',pillars=list(scorer.CORE))
            data=sample();data['execution']['customer_validation_performed']=True
            data['claims']=[{'id':'C1','pillar':'market','classification':'fact','statement':'Test fact',
                             'source_url':'https://example.org/source','accessed_date':'2026-10-23'}]
            data['pillars']['market']['claim_ids']=['C1']
            for p in scorer.CORE:
                data['pillars'][p]['evidence']=3
                data['pillars'][p]['behaviors']=[{'kind':'paid_test','description':'Fixture', 'observed_at':'2026-10-23',
                                                 'source_or_artifact':str(receipt),'verified':True,'ledger_event_id':event['id']}]
            errors,warnings=scorer.validate(data,root)
            self.assertFalse(errors,errors)
            result=scorer.score(data,warnings)
            self.assertEqual(result['decision'],'VALIDATE_BEFORE_BUILD')
            self.assertFalse(result['source_review_gate_open'])

    def test_fake_pilot_gate_reference_rejected(self):
        data=sample();data['project']['business_model']='services'
        data['pilot_gates']={'paid_engagement':{'passed':True,'evidence_ids':['FAKE']}}
        errors,_=scorer.validate(data)
        self.assertTrue(any('pilot_gates.paid_engagement' in e for e in errors))

class RunTests(unittest.TestCase):
    def test_resume_reuses_valid_artifact_and_redteam_depends_on_eight(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);rid=gf_observe.new_run(root,'Test idea')
            gf_runs.plan(root,rid)
            with self.assertRaises(ValueError):gf_runs.claim(root,rid,'gf-redteam')
            gf_runs.claim(root,rid,'gf-problem')
            a=root/'problem.md';a.write_text('source notes')
            gf_runs.complete(root,rid,'gf-problem',str(a))
            res=gf_runs.resume(root,rid,72)
            item=next(t for t in res['tasks'] if t['role']=='gf-problem')
            self.assertEqual(item['action'],'reuse')
            a.write_text('altered')
            res=gf_runs.resume(root,rid,72)
            self.assertEqual(next(t for t in res['tasks'] if t['role']=='gf-problem')['action'],'redo')
    def test_explicit_rate_and_reported_tokens_display_cost(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);rid=gf_observe.new_run(root,'Test idea');gf_runs.plan(root,rid)
            self.assertEqual(gf_observe.current_state(root,rid)['stats']['estimated_cost_usd'],None)
            gf_runs.set_rate(root,rid,5.0)
            gf_observe.emit(root,rid,'token_usage',provider='codex-cli',tokens=1000000)
            state=gf_observe.current_state(root,rid)
            self.assertEqual(state['stats']['estimated_cost_usd'],5)
            self.assertEqual(gf_runs.status(root,rid)['estimated_cost_usd'],5)
    def test_coverage_derived_from_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);rid=gf_observe.new_run(root,'Test idea');gf_runs.plan(root,rid)
            d=sample();d['claims']=[{'id':'C1','pillar':'market','source_url':'https://example.org','classification':'fact'}]
            e=root/'evaluation.json';e.write_text(json.dumps(d))
            r=root/'report.json';r.write_text(json.dumps({'claims':[{'claim_id':'C1','fetch_status':'fetched','excerpt_check':'found'}]}))
            out=gf_runs.coverage(root,rid,str(e),str(r))
            self.assertEqual(out['market']['sourced_claims'],1)
            self.assertEqual(out['market']['excerpt_located'],1)

FIXTURES=ROOT/'tests/fixtures'
BUDGET={'cash_budget_usd':10000,'engineering_weeks':12}

def portfolio_item(root,name,fixture='validate-before-build',decision='honest',edit=None):
    """Copy a real fixture evaluation into root; decision is 'honest' (what score_project writes), a dict, raw text, or None (no key)."""
    data=json.loads((FIXTURES/f'{fixture}.json').read_text())
    if edit:edit(data)
    e=root/f'{name}.evaluation.json';e.write_text(json.dumps(data))
    item={'name':name,'evaluation':e.name,'founder_fit_0_to_5':4,'founder_fit_rationale':'Domain experience',
          'build':{'cash_usd':2500,'engineering_weeks':3},'experiment':{'test':'Sell pilot','decision_threshold':'2 paid buyers',
          'cash_usd':100,'weeks':1,'expected_learning_0_to_5':4},'forecast':{'base':{'buyers':5,'revenue_per_buyer_12m':1000,
          'variable_cost_per_buyer_12m':200,'fixed_cost_12m':2000}}}
    if decision is not None:
        if decision=='honest':decision=gf_portfolio.score_file(e)[0]
        d=root/f'{name}.decision.json';d.write_text(decision if isinstance(decision,str) else json.dumps(decision))
        item['decision']=d.name
    return item

class PortfolioTests(unittest.TestCase):
    def test_ranking_excludes_veto_and_forecast_exact(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            good=portfolio_item(root,'Good')
            veto=portfolio_item(root,'Veto','no-go')
            out=gf_portfolio.evaluate_portfolio({'constraints':BUDGET,'opportunities':[veto,good]},root)
            self.assertEqual(out['opportunities'][0]['name'],'Good')
            self.assertEqual(out['opportunities'][0]['rank'],1)
            self.assertEqual(out['opportunities'][0]['decision'],'VALIDATE_BEFORE_BUILD')
            v=next(v for v in out['opportunities'] if v['name']=='Veto')
            self.assertIsNone(v['rank']);self.assertEqual(v['decision'],'NO_GO');self.assertFalse(v['decision_mismatch'])
            self.assertEqual(out['opportunities'][0]['forecast']['base']['contribution_after_fixed_12m'],2000)
    def test_root_given_through_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            real=Path(temp)/'real';real.mkdir()
            link=Path(temp)/'link';link.symlink_to(real,target_is_directory=True)
            good=portfolio_item(real,'Good')
            veto=portfolio_item(real,'Veto','no-go')
            out=gf_portfolio.evaluate_portfolio({'constraints':BUDGET,'opportunities':[veto,good]},link)
            self.assertEqual(out['opportunities'][0]['name'],'Good')
            self.assertEqual(out['opportunities'][0]['rank'],1)
    def test_incomplete_inputs_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);good=portfolio_item(root,'Good');good['founder_fit_0_to_5']=None
            with self.assertRaises(ValueError):gf_portfolio.evaluate_portfolio({'constraints':BUDGET,'opportunities':[good]},root)
    def test_decision_mismatch_unranked(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            honest=gf_portfolio.score_file(root/portfolio_item(root,'Stale',decision=None)['evaluation'])[0]
            stale={**honest,'weighted_quality_0_to_100':70.0}
            items=[portfolio_item(root,'Stale',decision=stale),portfolio_item(root,'Garbled',decision='{not json'),
                   portfolio_item(root,'Listed',decision='[]')]
            out=gf_portfolio.evaluate_portfolio({'constraints':BUDGET,'opportunities':items},root)
            for r in out['opportunities']:
                self.assertIsNone(r['rank'],r['name']);self.assertTrue(r['decision_mismatch'],r['name'])
                self.assertIn('re-run `greenfield score`',r['unranked_reason'])
            r=next(r for r in out['opportunities'] if r['name']=='Stale')
            self.assertEqual(r['stored_decision'],'VALIDATE_BEFORE_BUILD');self.assertEqual(r['decision'],'VALIDATE_BEFORE_BUILD')
            self.assertIn('Stale | Validate before build',gf_portfolio.to_markdown(out))
            self.assertIn('Stored decision disagrees with re-score |',gf_portfolio.to_markdown(out))
    def test_ranks_without_decision_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            a=portfolio_item(root,'A',decision=None);b=portfolio_item(root,'B',decision=None)
            b['evaluation']=a['evaluation']  # two opportunities sharing one evaluation are scored once
            out=gf_portfolio.evaluate_portfolio({'constraints':BUDGET,'opportunities':[a,b]},root)
            self.assertEqual([r['rank'] for r in out['opportunities']],[1,2])
            for r in out['opportunities']:
                self.assertIsNone(r['stored_decision']);self.assertFalse(r['decision_mismatch'])
                self.assertEqual(r['quality_0_to_100'],80.0);self.assertEqual(r['business_model'],'general')
    def test_invalid_evaluation_unranked_with_reason(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            bad=portfolio_item(root,'Bad',decision=None,edit=lambda d:d.update(as_of='soon'))
            out=gf_portfolio.evaluate_portfolio({'constraints':BUDGET,'opportunities':[bad]},root)
            r=out['opportunities'][0]
            self.assertIsNone(r['rank']);self.assertIsNone(r['decision'])
            self.assertEqual(r['unranked_reason'],'evaluation invalid: 1 error (first: as_of must be an ISO YYYY-MM-DD date)')
            self.assertEqual(r['validation_errors'],['as_of must be an ISO YYYY-MM-DD date'])
            self.assertTrue(out['recommendation'].startswith('No eligible build ranking'))

def cells(row):
    """Split a Markdown table row on unescaped pipes."""
    import re
    return re.split(r'(?<!\\)\|',row.strip().strip('|'))

class PortfolioOutputTests(unittest.TestCase):
    def test_md_cell(self):
        for raw,want in (('a|b','a\\|b'),('a\\b','a\\\\b'),('a\nb\r\tc','a b  c'),('`x`','\\`x\\`'),('[x](y)','\\[x\\](y)'),
                         ('<b>','\\<b\\>'),('*_#~','\\*\\_\\#\\~'),(None,'—'),('🚀','🚀'),('a\x1b\x00b','ab'),('plain name','plain name')):
            self.assertEqual(gf_portfolio.md_cell(raw),want,raw)
        long=gf_portfolio.md_cell('x'*500);self.assertEqual(len(long),120);self.assertTrue(long.endswith('…'))
    def test_hostile_name_keeps_table_shape(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);hostile='x | [click](javascript:alert(1)) <img src=x>'
            item=portfolio_item(root,'h',decision=None);item['name']=hostile;item['experiment']['test']='a\nb | c'
            md=gf_portfolio.to_markdown(gf_portfolio.evaluate_portfolio({'constraints':BUDGET,'opportunities':[item]},root))
            rows=[l for l in md.splitlines() if l.startswith('|')]
            self.assertEqual({len(cells(r)) for r in rows},{7})
            self.assertNotRegex(md,r'(?<!\\)[<\[]')
    def test_template_lists_placeholders(self):
        template=ROOT/'skill/assets/portfolio-template.json'
        r=subprocess.run([sys.executable,str(ROOT/'skill/scripts/gf_portfolio.py'),str(template),'--output','/dev/null'],capture_output=True,text=True)
        self.assertEqual(r.returncode,2);self.assertNotIn('Traceback',r.stderr);self.assertNotIn('does not exist',r.stderr)
        for path in ('opportunities[0].name','opportunities[0].founder_fit_rationale','opportunities[0].experiment.test',
                     'opportunities[0].experiment.decision_threshold','opportunities[0].evaluation','opportunities[0].founder_fit_0_to_5'):
            self.assertIn(path,r.stderr)
        self.assertNotIn('forecast',r.stderr)
        self.assertEqual(gf_portfolio.find_placeholders({'opportunities':[{'name':'Auto-REPLACE_parts'}]}),[])
    def test_labels_in_markdown_codes_in_json(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            items=[portfolio_item(root,'V',decision=None),portfolio_item(root,'N','no-go',decision=None),
                   portfolio_item(root,'R',decision=None,edit=lambda d:d['execution'].update(web_used=False)),
                   portfolio_item(root,'I',decision=None,edit=lambda d:d.update(as_of='soon'))]
            out=gf_portfolio.evaluate_portfolio({'constraints':BUDGET,'opportunities':items},root)
            md=gf_portfolio.to_markdown(out)
            for code in ('VALIDATE_BEFORE_BUILD','NO_GO','RESEARCH_INCOMPLETE'):
                self.assertNotIn(code,md);self.assertIn(code,[r['decision'] for r in out['opportunities']])
            for label in ('Validate before build','No go','Research incomplete',"Can't score"):self.assertIn(label,md)
            self.assertEqual({r['name']:r['verdict_label'] for r in out['opportunities']}['N'],'No go')

class PrivateOutputTests(unittest.TestCase):
    def test_outputs_and_ledger_are_private(self):
        old=os.umask(0o022);self.addCleanup(os.umask,old)
        mode=lambda p:stat.S_IMODE(os.stat(p).st_mode)
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);(d/'e.json').write_text('{}');(d/'m.json').write_text('{}')
            ledger.append(d/'led'/'x.jsonl','note','P','h')
            with mock.patch.object(evidence,'analyze',return_value={'summary':{}}):
                evidence.main([str(d/'e.json'),'--output',str(d/'ev'/'o.json')])
            with mock.patch.object(gf_portfolio,'evaluate_portfolio',return_value={'opportunities':[],'recommendation':''}),mock.patch.object(gf_portfolio,'to_markdown',return_value='x'):
                gf_portfolio.main([str(d/'m.json'),'--output',str(d/'po'/'o.json'),'--markdown',str(d/'pm'/'o.md')])
            sc=d/'sc.json';sc.write_text(json.dumps(sample()))
            subprocess.run([sys.executable,str(ROOT/'skill/scripts/score_project.py'),str(sc),'--output',str(d/'sd'/'o.json')],capture_output=True)
            for sub,f in (('led','x.jsonl'),('ev','o.json'),('po','o.json'),('pm','o.md'),('sd','o.json')):
                self.assertEqual(mode(d/sub/f),0o600,sub);self.assertEqual(mode(d/sub),0o700,sub)

if __name__=='__main__':unittest.main()
