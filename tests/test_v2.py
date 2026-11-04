import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'skill/scripts'))
import gf_ledger as ledger
import gf_evidence as evidence
import gf_profiles as profiles
import gf_runs
import gf_observe
import gf_portfolio
from test_skill import sample,scorer

class LedgerTests(unittest.TestCase):
    def test_behavior_requires_human_and_receipt(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'events.jsonl';receipt=Path(d)/'receipt.txt';receipt.write_text('sample')
            with self.assertRaises(ValueError):ledger.append(p,'paid_test','X','H',artifact=str(receipt))
            event=ledger.append(p,'paid_test','X','H',artifact=str(receipt),attester='Test human',pillars=['problem'])
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
            ledger.append(p,'source_review','X','Claim C1',outcome='supported',artifact=str(report),attester='Human',claim_id='C1')
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
            event=ledger.append(root/'experiment-ledger.jsonl','paid_test','A','H',artifact=receipt,
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

class PortfolioTests(unittest.TestCase):
    def make_item(self,root,name,decision,quality=80,ev=3):
        d=root/f'{name}.decision.json';d.write_text(json.dumps({'decision':decision,'weighted_quality_0_to_100':quality,'evidence_average_0_to_5':ev}))
        e=root/f'{name}.evaluation.json';e.write_text(json.dumps({'project':{'name':name}}))
        return {'name':name,'evaluation':e.name,'decision':d.name,'founder_fit_0_to_5':4,'founder_fit_rationale':'Domain experience',
                'build':{'cash_usd':2500,'engineering_weeks':3},'experiment':{'test':'Sell pilot','decision_threshold':'2 paid buyers',
                'cash_usd':100,'weeks':1,'expected_learning_0_to_5':4},'forecast':{'base':{'buyers':5,'revenue_per_buyer_12m':1000,
                'variable_cost_per_buyer_12m':200,'fixed_cost_12m':2000}}}
    def test_ranking_excludes_veto_and_forecast_exact(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            good=self.make_item(root,'Good','VALIDATE_BEFORE_BUILD')
            veto=self.make_item(root,'Veto','NO_GO',100,5)
            p={'constraints':{'cash_budget_usd':10000,'engineering_weeks':12},'opportunities':[veto,good]}
            out=gf_portfolio.evaluate_portfolio(p,root)
            self.assertEqual(out['opportunities'][0]['name'],'Good')
            self.assertIsNone(next(v for v in out['opportunities'] if v['name']=='Veto')['rank'])
            self.assertEqual(out['opportunities'][0]['forecast']['base']['contribution_after_fixed_12m'],2000)
    def test_root_given_through_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            real=Path(temp)/'real';real.mkdir()
            link=Path(temp)/'link';link.symlink_to(real,target_is_directory=True)
            good=self.make_item(real,'Good','VALIDATE_BEFORE_BUILD')
            veto=self.make_item(real,'Veto','NO_GO',100,5)
            p={'constraints':{'cash_budget_usd':10000,'engineering_weeks':12},'opportunities':[veto,good]}
            out=gf_portfolio.evaluate_portfolio(p,link)
            self.assertEqual(out['opportunities'][0]['name'],'Good')
    def test_incomplete_inputs_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);good=self.make_item(root,'Good','VALIDATE_BEFORE_BUILD');good['founder_fit_0_to_5']=None
            with self.assertRaises(ValueError):gf_portfolio.evaluate_portfolio({'constraints':{'cash_budget_usd':10000,'engineering_weeks':12},'opportunities':[good]},root)

if __name__=='__main__':unittest.main()
