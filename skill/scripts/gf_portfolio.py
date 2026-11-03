#!/usr/bin/env python3
"""Cross-idea prioritization, sensitivity and explicit scenario forecasting.

Heuristic priority indices are NOT probabilities, valuations or investment advice.
Missing inputs produce unranked opportunities; decision vetoes remain visible.
"""
from __future__ import annotations
import argparse
import csv
import json
from pathlib import Path
import re
import sys
from gf_common import old_entry, GFError, atomic_write, atomic_write_json, VERSION, finite_nonneg, load_json, resolve_inside
from score_project import VERDICTS, score_file

SCENARIOS={
 'balanced':{'quality':.30,'evidence':.20,'founder':.20,'learning':.20,'resources':.10},
 'capital_constrained':{'quality':.22,'evidence':.22,'founder':.18,'learning':.13,'resources':.25},
 'learning_first':{'quality':.22,'evidence':.14,'founder':.14,'learning':.40,'resources':.10},
}

TEMPLATE_PATHS={'relative/path/evaluation.json','relative/path/decision.json'}
NEEDS_NUMBER=('founder_fit_0_to_5','build.cash_usd','build.engineering_weeks','experiment.cash_usd','experiment.weeks','experiment.expected_learning_0_to_5')


def md_cell(value, limit=120):
    """One safe Markdown table cell: no line breaks, no live links or HTML, at most limit characters before escaping."""
    if value is None:return '—'
    text=re.sub(r'[\x00-\x1f\x7f-\x9f]','',re.sub(r'[\r\n\t]',' ',str(value)))
    if len(text)>limit:text=text[:limit-1].rstrip()+'…'
    return re.sub(r'([\\|*_`\[\]<>#~])',r'\\\1',text)


def find_placeholders(manifest):
    """JSON paths still holding template values: REPLACE_ strings, template paths, or null where a number is required."""
    found=[]
    def walk(node,path):
        if isinstance(node,dict):
            for k,v in node.items():
                if not str(k).startswith('_'):walk(v,f'{path}.{k}' if path else str(k))
        elif isinstance(node,list):
            for i,v in enumerate(node):walk(v,f'{path}[{i}]')
        elif (isinstance(node,str) and (node.startswith('REPLACE_') or node in TEMPLATE_PATHS)) or \
                (node is None and re.sub(r'^opportunities\[\d+\]\.','',path) in NEEDS_NUMBER):
            found.append(path)
    walk(manifest,'')
    return found


def numeric(value, where, limit=None):
    return finite_nonneg(value, where, limit)


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


def close(a, b, tol):
    if a is None or b is None:
        return a is None and b is None
    return type(a) in (int, float) and type(b) in (int, float) and abs(a - b) <= tol


def stored_mismatch(decision_path, result):
    """(stored decision or None, mismatch reason or None) comparing a decision.json with the recomputed result."""
    try:
        stored = load_json(decision_path)
    except GFError as exc:
        return None, f'stored decision file is unreadable ({exc}); re-run `greenfield score`'
    said = stored.get('decision')
    if result is None:
        return said, None  # invalid evaluation: reported as such, not as a mismatch
    if said != result['decision'] or not close(stored.get('weighted_quality_0_to_100'), result['weighted_quality_0_to_100'], .05) \
            or not close(stored.get('evidence_average_0_to_5'), result['evidence_average_0_to_5'], .005):
        return said, (f"stored {decision_path.name} says {said} (quality {stored.get('weighted_quality_0_to_100')}) but the evaluation "
                      f"scores {result['decision']} (quality {result['weighted_quality_0_to_100']}) today; re-run `greenfield score`")
    return said, None


def evaluate_portfolio(manifest, root):
    root=Path(root).resolve()
    todo=find_placeholders(manifest)
    if todo:raise GFError(f"portfolio manifest still has {len(todo)} placeholder{'s'*(len(todo)!=1)} to fill: {', '.join(todo)}. See the _help notes in the template.")
    items=manifest.get('opportunities',[])
    if not isinstance(items,list) or not items:raise ValueError('Need one or more opportunities')
    constraints=manifest.get('constraints',{})
    cash=numeric(constraints.get('cash_budget_usd',0),'cash_budget_usd')
    weeks=numeric(constraints.get('engineering_weeks',0),'engineering_weeks')
    if cash==0 or weeks==0:raise ValueError('Supply a positive portfolio cash budget and engineering-weeks budget')
    results=[];names=set();scored={}
    for item in items:
        name=item.get('name','')
        if not name or name in names:raise ValueError('Each opportunity needs a unique name')
        names.add(name)
        eval_path=resolve_inside(root,item['evaluation'],must_exist=True)
        if eval_path not in scored:scored[eval_path]=score_file(eval_path)  # rankings come from evidence, never decision.json
        result,errors,_=scored[eval_path]
        stored,mismatch=stored_mismatch(resolve_inside(root,item['decision'],must_exist=True),result) if item.get('decision') else (None,None)
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
        result=result or {}
        q=result.get('weighted_quality_0_to_100')
        e=result.get('evidence_average_0_to_5')
        valid=q is not None and e is not None
        dimension={'quality':q/100 if valid else None,'evidence':e/5 if valid else None,'founder':fit/5,'learning':learn/5,'resources':resource_score}
        sensitivity={k:round(sum(w*dimension[key] for key,w in weights.items())*100,1) if valid else None for k,weights in SCENARIOS.items()}
        veto=result.get('decision') not in ('VALIDATE_BEFORE_BUILD','PROCEED_TO_BOUNDED_PILOT')
        reason=(f"evaluation invalid: {len(errors)} error{'s'*(len(errors)!=1)} (first: {errors[0]})" if errors else mismatch
                or ('Decision requires pivot/rejection or research is incomplete' if veto else 'Missing quality/evidence' if not valid else None))
        code=result.get('decision') or 'INVALID'
        results.append({'name':name,'decision':result.get('decision'),'verdict_label':VERDICTS.get(code,{}).get('label','Unknown verdict'),'stored_decision':stored,'decision_mismatch':bool(mismatch),
                        'validation_errors':errors[:5],'business_model':result.get('business_model_profile'),
                        'founder_fit_0_to_5':fit,'founder_fit_rationale':item['founder_fit_rationale'],
                        'quality_0_to_100':q,'evidence_0_to_5':e,'sensitivity_scores':sensitivity,
                        'score_range': [min(sensitivity.values()),max(sensitivity.values())] if valid else None,
                        'resource_feasibility_0_to_1':round(resource_score,3),
                        'cash_needed_for_experiment':spent,'weeks_needed_for_experiment':duration,
                        'learning_per_1000_usd':round(learn/(spent/1000),2) if spent>0 else None,
                        'learning_per_week':round(learn/duration,2) if duration>0 else None,
                        'next_test':item['experiment']['test'],'pass_threshold':item['experiment']['decision_threshold'],
                        'forecast':forecast(item.get('forecast')),'eligible_for_next_experiment':reason is None,
                        'unranked_reason':reason})
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
    lines=['# Greenfield opportunity portfolio','',result['assumptions'],'', '| Rank | Opportunity | Decision | Balanced | Sensitivity range | Next validation | Why unranked |', '|---:|---|---|---:|---|---|---|']
    for r in result['opportunities']:
        sc=r['sensitivity_scores']['balanced'];rr=r['score_range']
        label=VERDICTS.get(r['decision'] or 'INVALID',{}).get('label','Unknown verdict')
        why='Stored decision disagrees with re-score' if r.get('decision_mismatch') else r['unranked_reason'] or ''
        cells=[r['rank'] or '—',r['name'],label,sc if sc is not None else 'N/A',rr or 'N/A',r['next_test'],why]
        lines.append('| '+' | '.join(md_cell(c) for c in cells)+' |')
    lines.extend(['','**Recommendation:** '+md_cell(result['recommendation'],1000),'','Scores are comparative design heuristics, not calibrated predictive estimates. Prioritization excludes No go, Pivot and Research incomplete.'])
    return '\n'.join(lines)+'\n'


def run(manifest,output,markdown=None):
    """Rank the manifest's opportunities, write output (and markdown), return the one-line summary dict."""
    manifest,output=Path(manifest),Path(output)
    out=evaluate_portfolio(load_json(manifest),manifest.resolve().parent)
    output.parent.mkdir(mode=0o700,parents=True,exist_ok=True);atomic_write_json(output,out,mode=0o600)
    if markdown:markdown=Path(markdown);markdown.parent.mkdir(mode=0o700,parents=True,exist_ok=True);atomic_write(markdown,to_markdown(out),mode=0o600)
    return {'ranked':sum(r['rank'] is not None for r in out['opportunities']),'opportunities':len(out['opportunities']),'recommendation':out['recommendation']}
def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--version',action='version',version=f'%(prog)s {VERSION}');p.add_argument('manifest',type=Path);p.add_argument('--output',type=Path,required=True);p.add_argument('--markdown',type=Path)
    args=p.parse_args(argv)
    try:
        print(json.dumps(run(args.manifest,args.output,args.markdown),indent=2))
    except (OSError,ValueError,TypeError,KeyError) as exc:
        print('ERROR:',exc,file=sys.stderr);return 2
    return 0
if __name__=='__main__':raise SystemExit(old_entry(main,'gf_portfolio.py','greenfield portfolio'))
