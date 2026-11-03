#!/usr/bin/env python3
"""Cross-idea prioritization, sensitivity and explicit scenario forecasting.

Heuristic priority indices are NOT probabilities, valuations or investment advice.
Missing inputs produce unranked opportunities; decision vetoes remain visible.
"""
from __future__ import annotations
import argparse
import csv
import json
import math
from pathlib import Path
import sys

SCENARIOS={
 'balanced':{'quality':.30,'evidence':.20,'founder':.20,'learning':.20,'resources':.10},
 'capital_constrained':{'quality':.22,'evidence':.22,'founder':.18,'learning':.13,'resources':.25},
 'learning_first':{'quality':.22,'evidence':.14,'founder':.14,'learning':.40,'resources':.10},
}

def numeric(value, where, limit=None):
    if type(value) not in (int,float) or not math.isfinite(value) or value<0 or (limit is not None and value>limit):
        raise ValueError(f'{where} requires a finite nonnegative number'+(f' <= {limit}' if limit else ''))
    return float(value)


def forecast(options):
    if not options:return None
    result={}
    for name in ('low','base','high'):
        data=options.get(name)
        if not data or any(key not in data for key in ('buyers','revenue_per_buyer_12m','variable_cost_per_buyer_12m','fixed_cost_12m')):
            result[name]=None;continue
        vals={k:numeric(v,f'{name}.{k}') for k,v in data.items() if k in ('buyers','revenue_per_buyer_12m','variable_cost_per_buyer_12m','fixed_cost_12m')}
        result[name]={'revenue_12m':round(vals['buyers']*vals['revenue_per_buyer_12m'],2),
                      'contribution_after_fixed_12m':round(vals['buyers']*(vals['revenue_per_buyer_12m']-vals['variable_cost_per_buyer_12m'])-vals['fixed_cost_12m'],2)}
    return result


def evaluate_portfolio(manifest, root):
    items=manifest.get('opportunities',[])
    if not isinstance(items,list) or not items:raise ValueError('Need one or more opportunities')
    constraints=manifest.get('constraints',{})
    cash=numeric(constraints.get('cash_budget_usd',0),'cash_budget_usd')
    weeks=numeric(constraints.get('engineering_weeks',0),'engineering_weeks')
    if cash==0 or weeks==0:raise ValueError('Supply a positive portfolio cash budget and engineering-weeks budget')
    results=[];names=set()
    for item in items:
        name=item.get('name','')
        if not name or name in names:raise ValueError('Each opportunity needs a unique name')
        names.add(name)
        eval_path=(root/item['evaluation']).resolve()
        decision_path=(root/item['decision']).resolve()
        if not eval_path.is_relative_to(root) or not decision_path.is_relative_to(root):raise ValueError('Evaluation and decision paths must remain inside manifest folder')
        evaluation=json.loads(eval_path.read_text());decision=json.loads(decision_path.read_text())
        fit=numeric(item['founder_fit_0_to_5'],name+'.founder_fit',5)
        if not item.get('founder_fit_rationale'):
            raise ValueError(name+': must supply founder fit rationale')
        learn=numeric(item['experiment']['expected_learning_0_to_5'],name+'.learning',5)
        spent=numeric(item['experiment']['cash_usd'],name+'.experiment_cash')
        duration=numeric(item['experiment']['weeks'],name+'.experiment_weeks')
        if not item['experiment'].get('test') or not item['experiment'].get('decision_threshold'):
            raise ValueError(name+': must give falsifiable test and threshold')
        project_cash=numeric(item['build']['cash_usd'],name+'.build_cash')
        project_weeks=numeric(item['build']['engineering_weeks'],name+'.build_weeks')
        # Relative resource feasibility, lower time/cash is favorable.
        resource_score=max(0,1-(.5*min(1,project_cash/cash)+.5*min(1,project_weeks/weeks)))
        q=decision.get('weighted_quality_0_to_100')
        e=decision.get('evidence_average_0_to_5')
        valid=q is not None and type(q) in (int,float) and e is not None and type(e) in (int,float)
        if valid:
            numeric(q,'quality',100);numeric(e,'evidence',5)
        dimension={'quality':q/100 if valid else None,'evidence':e/5 if valid else None,'founder':fit/5,'learning':learn/5,'resources':resource_score}
        sensitivity={k:round(sum(w*dimension[key] for key,w in weights.items())*100,1) if valid else None for k,weights in SCENARIOS.items()}
        veto=decision.get('decision') not in ('VALIDATE_BEFORE_BUILD','PROCEED_TO_BOUNDED_PILOT')
        results.append({'name':name,'decision':decision.get('decision'),'business_model':decision.get('business_model_profile','general'),
                        'founder_fit_0_to_5':fit,'founder_fit_rationale':item['founder_fit_rationale'],
                        'quality_0_to_100':q,'evidence_0_to_5':e,'sensitivity_scores':sensitivity,
                        'score_range': [min(sensitivity.values()),max(sensitivity.values())] if valid else None,
                        'resource_feasibility_0_to_1':round(resource_score,3),
                        'cash_needed_for_experiment':spent,'weeks_needed_for_experiment':duration,
                        'learning_per_1000_usd':round(learn/(spent/1000),2) if spent>0 else None,
                        'learning_per_week':round(learn/duration,2) if duration>0 else None,
                        'next_test':item['experiment']['test'],'pass_threshold':item['experiment']['decision_threshold'],
                        'forecast':forecast(item.get('forecast')),'eligible_for_next_experiment':bool(valid and not veto),
                        'unranked_reason':'Decision requires pivot/rejection or research is incomplete' if veto else 'Missing quality/evidence' if not valid else None})
    eligible=sorted((r for r in results if r['eligible_for_next_experiment']),key=lambda x:x['sensitivity_scores']['balanced'],reverse=True)
    for n,item in enumerate(eligible,1):item['rank']=n
    for r in results:
        if 'rank' not in r:r['rank']=None
    results.sort(key=lambda r:(r['rank'] is None,r['rank'] if r['rank'] is not None else 999,r['name']))
    return {'schema_version':'2.0','score_description':'Heuristic priority index; NOT success probability or dollar valuation',
            'scenarios':SCENARIOS,'constraints':constraints,'opportunities':results,
            'assumptions':'Forecasts are deterministic calculations from user-supplied scenario inputs, not predictions; no invented costs, sales or conversion.',
            'recommendation':f'Prioritize validation of {eligible[0]["name"]} next; passing experiments is necessary before increasing build commitment.' if eligible else 'No eligible build ranking; resolve incomplete research or blockers first.'}


def to_markdown(result):
    lines=['# Greenfield opportunity portfolio','',result['assumptions'],'', '| Rank | Opportunity | Decision | Balanced | Sensitivity range | Next validation |', '|---:|---|---|---:|---|---|']
    for r in result['opportunities']:
        sc=r['sensitivity_scores']['balanced'];rr=r['score_range']
        lines.append(f"| {r['rank'] or '—'} | {r['name']} | {r['decision']} | {str(sc) if sc is not None else 'N/A'} | {str(rr) if rr else 'N/A'} | {r['next_test'].replace('|','/')} |")
    lines.extend(['','**Recommendation:** '+result['recommendation'],'','Scores are comparative design heuristics, not calibrated predictive estimates. Prioritization excludes NO_GO, PIVOT and RESEARCH_INCOMPLETE.'])
    return '\n'.join(lines)+'\n'


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('manifest',type=Path);p.add_argument('--output',type=Path,required=True);p.add_argument('--markdown',type=Path)
    args=p.parse_args(argv)
    try:
        root=args.manifest.resolve().parent
        out=evaluate_portfolio(json.loads(args.manifest.read_text(encoding='utf-8')),root)
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(out,indent=2)+'\n')
        if args.markdown:args.markdown.parent.mkdir(parents=True,exist_ok=True);args.markdown.write_text(to_markdown(out))
        print(json.dumps({'ranked':sum(r['rank'] is not None for r in out['opportunities']),'opportunities':len(out['opportunities']),'recommendation':out['recommendation']},indent=2))
    except (OSError,ValueError,TypeError,KeyError) as exc:
        print('ERROR:',exc,file=sys.stderr);return 2
    return 0
if __name__=='__main__':raise SystemExit(main())
