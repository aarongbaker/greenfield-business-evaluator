#!/usr/bin/env python3
"""Append-only, locally hash-chained greenfield experiment ledger (stdlib).

A hash chain detects accidental edits. It is NOT a cryptographic signature or
independent proof of behavior. Human-attested receipts are required for strong
first-party behavior evidence; no AI should forge an attestation.
"""
from __future__ import annotations
import argparse
import datetime as dt
import fcntl
import hashlib
import json
from pathlib import Path
import sys
import uuid

from gf_common import VERSION

ALLOWED = {"hypothesis", "customer_interview", "customer_action", "paid_test", "signed_commitment", "repeat_purchase", "feasibility_proof", "experiment_result", "decision_revision", "failure", "note", "source_review"}
BEHAVIOR = {"customer_action", "paid_test", "signed_commitment", "repeat_purchase", "feasibility_proof"}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def read_ledger(path):
    path = Path(path)
    records = []
    if not path.exists():
        return records
    with path.open(encoding='utf-8') as handle:
        for n, line in enumerate(handle, 1):
            if not line.strip():
                raise ValueError(f'Empty record at line {n}')
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f'Invalid record at line {n}') from exc
            actual_hash = event.pop('hash', None)
            expected_prev = records[-1]['hash'] if records else 'GENESIS'
            if event.get('seq') != n or event.get('previous_hash') != expected_prev or actual_hash != digest(event):
                raise ValueError(f'Ledger integrity failure at line {n}')
            event['hash'] = actual_hash
            records.append(event)
    return records


def artifact_digest(path):
    if not path:
        return None
    p = Path(path).expanduser().resolve(strict=True)
    if not p.is_file() or p.stat().st_size > 50 * 1024 * 1024:
        raise ValueError('Artifact must be a regular file <= 50 MB')
    hash_obj = hashlib.sha256()
    with p.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            hash_obj.update(chunk)
    return {'path': str(p), 'sha256': hash_obj.hexdigest(), 'bytes': p.stat().st_size}


def append(path, kind, project, hypothesis, outcome='', artifact=None, attester='', observed_at='', notes='', pillars=None, claim_id='', experiment_id=''):
    if kind not in ALLOWED:
        raise ValueError('Invalid kind')
    if not project.strip() or not hypothesis.strip():
        raise ValueError('Project and hypothesis/subject required')
    if (kind in BEHAVIOR or kind == 'source_review') and (not attester.strip() or not artifact):
        raise ValueError('Behavior event requires a named HUMAN attester and actual local evidence artifact')
    if observed_at:
        dt.date.fromisoformat(observed_at)
    if kind == 'source_review' and (not claim_id or outcome not in ('supported', 'contradicted', 'unclear')):
        raise ValueError('Source review needs claim ID and outcome supported|contradicted|unclear')
    doc = artifact_digest(artifact)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive OS-level advisory lock across processes; file remains append only.
    with path.open('a+', encoding='utf-8') as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            existing = read_ledger(path)
            data = {'seq': len(existing)+1, 'id': 'EV-'+uuid.uuid4().hex[:12], 'recorded_at': dt.datetime.now(dt.timezone.utc).isoformat(),
                    'observed_at': observed_at or dt.date.today().isoformat(), 'kind':kind, 'project':project.strip(),
                    'hypothesis':hypothesis.strip(), 'outcome':outcome.strip(), 'notes':notes.strip(),
                    'attester':attester.strip() if kind in BEHAVIOR or kind == 'source_review' else '', 'human_attested': bool((kind in BEHAVIOR or kind == 'source_review') and attester),
                    'artifact':doc, 'pillar_ids': sorted(set(pillars or [])), 'claim_id':claim_id,
                    'experiment_id':experiment_id, 'previous_hash':existing[-1]['hash'] if existing else 'GENESIS'}
            data['hash'] = digest(data)
            f.write(canonical(data)+'\n')
            f.flush()
            import os
            os.fsync(f.fileno())
            return data
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def verified_behavior(path, event_id, pillar=None):
    try:
        events = read_ledger(path)
    except (OSError, ValueError):
        return False, 'ledger unavailable or hash chain invalid'
    event = next((e for e in events if e['id'] == event_id), None)
    if not event:
        return False, 'event not found'
    if event['kind'] not in BEHAVIOR or not event['human_attested'] or not event.get('artifact'):
        return False, 'event is not a human-attested behavioral observation'
    if pillar and pillar not in event['pillar_ids']:
        return False, 'event not linked to this pillar'
    meta = event['artifact']
    try:
        current = artifact_digest(meta['path'])
    except (OSError, ValueError):
        return False, 'artifact missing or unreadable'
    if current['sha256'] != meta['sha256']:
        return False, 'artifact has changed since attestation'
    return True, 'local attestation and receipt hash intact (not independent proof)'


def reviewed_claims(ledger_path, report_path):
    """Most recent human review of each claim against the same immutable report digest."""
    report = artifact_digest(report_path)
    records = read_ledger(ledger_path)
    report_ids = {c.get('claim_id') for c in json.loads(Path(report_path).read_text(encoding='utf-8')).get('claims',[])}
    return {e['claim_id']: e['outcome'] for e in records if e['kind'] == 'source_review' and e['human_attested']
            and e.get('artifact') and e['artifact']['sha256'] == report['sha256'] and e['claim_id'] in report_ids}


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--version',action='version',version=f'%(prog)s {VERSION}')
    sub=ap.add_subparsers(dest='command', required=True)
    p=sub.add_parser('record')
    p.add_argument('--ledger',required=True)
    p.add_argument('--kind',required=True,choices=sorted(ALLOWED))
    p.add_argument('--project',required=True)
    p.add_argument('--hypothesis',required=True)
    p.add_argument('--outcome',default='')
    p.add_argument('--artifact')
    p.add_argument('--attester',default='')
    p.add_argument('--observed-at',default='')
    p.add_argument('--notes',default='')
    p.add_argument('--pillar',action='append',default=[])
    p.add_argument('--claim-id',default='')
    p.add_argument('--experiment-id',default='')
    v=sub.add_parser('verify');v.add_argument('--ledger',required=True)
    s=sub.add_parser('summary');s.add_argument('--ledger',required=True)
    args=ap.parse_args(argv)
    try:
        if args.command=='record':
            value=append(args.ledger,args.kind,args.project,args.hypothesis,args.outcome,args.artifact,args.attester,args.observed_at,args.notes,args.pillar,args.claim_id,args.experiment_id)
        else:
            events=read_ledger(args.ledger)
            value={'valid':True,'events':len(events),'last_hash':events[-1]['hash'] if events else 'GENESIS'}
            if args.command=='summary':
                from collections import Counter
                value['by_type']=dict(Counter(e['kind'] for e in events))
                value['behavior_receipts']=[{'id':e['id'],'kind':e['kind'],'pillar_ids':e['pillar_ids'],'integrity':verified_behavior(args.ledger,e['id'])[0]} for e in events if e['kind'] in BEHAVIOR]
        print(json.dumps(value,indent=2))
    except (OSError, ValueError, KeyError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr);return 2
    return 0

if __name__=='__main__':
    raise SystemExit(main())
