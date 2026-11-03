#!/usr/bin/env python3
"""Checkpoint/resume real multi-agent research tasks. DOES NOT launch agents.

Host agent delegates tasks; this is a durable task ledger and artifact validator.
Completed research is reused only when its file checksum is still valid and
user-selected freshness horizon is met. Every resume is explicit.
"""
from __future__ import annotations
import argparse
import datetime as dt
import fcntl
import hashlib
import json
from pathlib import Path
import sys
from gf_common import VERSION, finite_nonneg, resolve_inside
from gf_profiles import BASE
from gf_observe import AGENTS,active_run,emit,atomic_json,current_state,file_paths

ROLES=AGENTS

def digest(path):
    result=hashlib.sha256()
    with Path(path).open('rb') as file:
        for b in iter(lambda:file.read(1024*1024),b''):result.update(b)
    return result.hexdigest()

def manifest_path(project,run_id):
    return file_paths(project,run_id)[0].parent/'task-manifest.json'  # file_paths validates run_id

def load(project,run_id):
    p=manifest_path(project,run_id)
    if not p.exists():raise ValueError('Plan not initialized for this run')
    return json.loads(p.read_text(encoding='utf-8'))

def transact(project,run_id,callback):
    p=manifest_path(project,run_id)
    p.parent.mkdir(parents=True,exist_ok=True)
    lock=p.with_suffix('.lock')
    lock.touch(mode=0o600)
    with lock.open('a+') as lf:
        fcntl.flock(lf,fcntl.LOCK_EX)
        try:
            plan=json.loads(p.read_text(encoding='utf-8')) if p.exists() else None
            outcome=callback(plan)
            if isinstance(outcome,tuple):plan,result=outcome
            else:plan,result=outcome,None
            atomic_json(p,plan)
            return plan,result
        finally:fcntl.flock(lf,fcntl.LOCK_UN)

def plan(project,run_id):
    def create(doc):
        if doc is not None:raise ValueError('Plan already exists; use status or resume')
        return {'version':'2.0','run_id':run_id,'tasks':{r:{'status':'queued','attempts':0,'artifact':None,'sha256':None,'completed_at':None,'claimed_at':None,'note':''} for r in ROLES},'coverage':{},'cost_rate_usd_per_million_tokens':None},None
    doc,_=transact(project,run_id,create)
    for role in ROLES:emit(project,run_id,'task_planned',agent=role,summary='Research task planned')
    return doc

def claim(project,run_id,role):
    if role not in ROLES:raise ValueError('Unknown role')
    def update(doc):
        if doc is None:raise ValueError('No plan')
        task=doc['tasks'][role]
        if role=='gf-redteam' and any(doc['tasks'][r]['status']!='completed' for r in ROLES if r!=role):
            raise ValueError('Red team must wait for all eight completed specialists')
        if task['status'] not in ('queued','failed'):
            raise ValueError('Task not claimable: '+task['status'])
        task.update(status='running',attempts=task['attempts']+1,claimed_at=dt.datetime.now(dt.timezone.utc).isoformat())
        return doc,None
    doc,_=transact(project,run_id,update)
    emit(project,run_id,'task_started',agent=role,summary='Task claimed by orchestrator')
    return doc['tasks'][role]

def complete(project,run_id,role,artifact):
    if role not in ROLES:raise ValueError('Unknown role')
    project=Path(project).resolve()
    try:art=resolve_inside(project,artifact,must_exist=True)
    except ValueError as exc:raise ValueError(f'Completed artifact: {exc}') from None
    if not art.is_file():raise ValueError('Completed artifact must be an existing file inside project')
    hash_=digest(art)
    def update(doc):
        task=doc['tasks'][role]
        if task['status']!='running':raise ValueError('Task must be claimed before completion')
        task.update(status='completed',artifact=str(art.relative_to(project)),sha256=hash_,completed_at=dt.datetime.now(dt.timezone.utc).isoformat())
        return doc,None
    doc,_=transact(project,run_id,update)
    emit(project,run_id,'task_completed',agent=role,summary='Checkpoint saved and checksum verified')
    emit(project,run_id,'artifact_created',agent=role,summary='Task artifact recorded')
    return doc['tasks'][role]

def fail(project,run_id,role,reason):
    if role not in ROLES:raise ValueError('Unknown role')
    def update(doc):
        task=doc['tasks'][role]
        if task['status'] not in ('running','queued'):raise ValueError('Task cannot be failed from current state')
        task.update(status='failed',note=str(reason)[:150])
        return doc,None
    doc,_=transact(project,run_id,update)
    emit(project,run_id,'task_failed',agent=role,summary='Task failed: '+str(reason)[:90])
    return doc['tasks'][role]

def resume(project,run_id,freshness_hours=72):
    if freshness_hours<0:raise ValueError('freshness_hours must be nonnegative')
    project=Path(project).resolve()
    now=dt.datetime.now(dt.timezone.utc)
    def update(doc):
        if doc is None:raise ValueError('No plan')
        decisions=[]
        for role,task in doc['tasks'].items():
            if task['status']=='completed':
                try:
                    art=resolve_inside(project,task.get('artifact') or '',must_exist=True)
                    date=dt.datetime.fromisoformat(task['completed_at'])
                    good=art.is_file() and digest(art)==task['sha256']
                    fresh=(now-date).total_seconds()<=freshness_hours*3600
                except (ValueError,OSError,TypeError):good=fresh=False
                if good and fresh:
                    decisions.append({'role':role,'action':'reuse','reason':'artifact checksum and age valid'})
                    continue
                task.update(status='queued',artifact=None,sha256=None)
                decisions.append({'role':role,'action':'redo','reason':'missing, changed, or stale checkpoint'})
            elif task['status']=='running':
                task['status']='queued'
                decisions.append({'role':role,'action':'redo','reason':'interrupted task; no completion checkpoint'})
            else:decisions.append({'role':role,'action':'redo','reason':task['status']})
        # Red-team conclusions must be rechecked when any underlying specialist changes.
        if any(x['action']=='redo' and x['role']!='gf-redteam' for x in decisions):
            red=doc['tasks']['gf-redteam']
            if red['status']=='completed':
                red.update(status='queued',artifact=None,sha256=None)
                decisions=[x if x['role']!='gf-redteam' else {'role':'gf-redteam','action':'redo','reason':'upstream specialist requires new research'} for x in decisions]
        return doc,decisions
    doc,result=transact(project,run_id,update)
    emit(project,run_id,'run_resumed',summary=f'Resume planned: {sum(x["action"]=="reuse" for x in result)} reusable')
    return {'run_id':run_id,'tasks':result, 'caution':'Resume generates a safe plan, not background agent execution.'}

def set_rate(project,run_id,rate):
    rate=finite_nonneg(rate,'rate')
    def update(doc):
        if doc is None:raise ValueError('No plan')
        doc['cost_rate_usd_per_million_tokens']=rate
        return doc,None
    doc,_=transact(project,run_id,update)
    emit(project,run_id,'note',summary='User configured illustrative blended token rate')
    return {'usd_per_million_reported_tokens':rate,'warning':'Approximate only; unavailable provider usage is not counted.'}


def coverage(project,run_id,evaluation,report=None):
    data=json.loads(Path(evaluation).read_text(encoding='utf-8'))
    claims=data.get('claims',[])
    pillar_data={p:{'claims':sum(c.get('pillar')==p for c in claims),
                    'sourced_claims':sum(c.get('pillar')==p and bool(c.get('source_url')) for c in claims),
                    'quality_assessed': isinstance(data.get('pillars',{}).get(p,{}).get('quality'),int)} for p in BASE}
    audited=set()
    if report:
        verified=json.loads(Path(report).read_text(encoding='utf-8'))
        audited={r.get('claim_id') for r in verified.get('claims',[]) if r.get('fetch_status')=='fetched' and r.get('excerpt_check')=='found'}
    for p in pillar_data:
        pillar_data[p]['excerpt_located']=sum(c.get('pillar')==p and c.get('id') in audited for c in claims)
    def update(doc):
        if doc is None:raise ValueError('No plan')
        doc['coverage']=pillar_data
        return doc,None
    transact(project,run_id,update)
    emit(project,run_id,'note',summary='Claim coverage updated from evaluation files')
    return pillar_data


def status(project,run_id,rate=None):
    doc=load(project,run_id)
    state=current_state(project,run_id)
    tokens=state['stats']['reported_tokens']
    usd_rate=rate if rate is not None else doc.get('cost_rate_usd_per_million_tokens')
    cost=round(tokens/1_000_000*usd_rate,6) if usd_rate is not None and tokens>0 else None
    return {'run_id':run_id,'tasks':{r:t['status'] for r,t in doc['tasks'].items()},
            'task_completion':sum(t['status']=='completed' for t in doc['tasks'].values()),
            'coverage':doc.get('coverage',{}),'reported_tokens':tokens,'estimated_cost_usd':cost,
            'cost_note':'User-supplied BLENDED token rate and reported tokens only; not a provider invoice. Unknown if usage unreported.',
            'telemetry_events':state['stats']['tool_calls']}

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--version',action='version',version=f'%(prog)s {VERSION}')
    p.add_argument('--project',default='.')
    p.add_argument('--run')
    sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('plan')
    c=sub.add_parser('claim');c.add_argument('--role',required=True)
    c=sub.add_parser('complete');c.add_argument('--role',required=True);c.add_argument('--artifact',required=True)
    c=sub.add_parser('fail');c.add_argument('--role',required=True);c.add_argument('--reason',required=True)
    c=sub.add_parser('resume');c.add_argument('--freshness-hours',type=float,default=72)
    c=sub.add_parser('status');c.add_argument('--usd-per-million-tokens',type=float)
    c=sub.add_parser('coverage');c.add_argument('--evaluation',required=True);c.add_argument('--verification-report')
    c=sub.add_parser('set-rate');c.add_argument('--usd-per-million-tokens',type=float,required=True)
    args=p.parse_args(argv)
    try:
        rid=args.run or active_run(args.project)
        if not rid:raise ValueError('No run: initialize with gf_observe.py start first')
        if args.command=='plan':out=plan(args.project,rid)
        elif args.command=='claim':out=claim(args.project,rid,args.role)
        elif args.command=='complete':out=complete(args.project,rid,args.role,args.artifact)
        elif args.command=='fail':out=fail(args.project,rid,args.role,args.reason)
        elif args.command=='resume':out=resume(args.project,rid,args.freshness_hours)
        elif args.command=='coverage':out=coverage(args.project,rid,args.evaluation,args.verification_report)
        elif args.command=='set-rate':out=set_rate(args.project,rid,args.usd_per_million_tokens)
        else:
            if args.usd_per_million_tokens is not None and args.usd_per_million_tokens<0:raise ValueError('rate must be >= 0')
            out=status(args.project,rid,args.usd_per_million_tokens)
        print(json.dumps(out,indent=2))
    except (OSError,ValueError,KeyError,TypeError) as exc:
        print('ERROR:',exc,file=sys.stderr);return 2
    return 0

if __name__=='__main__':raise SystemExit(main())
