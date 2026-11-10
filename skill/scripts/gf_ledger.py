#!/usr/bin/env python3
"""Append-only, locally hash-chained greenfield experiment ledger (stdlib).

A hash chain detects accidental edits. Attested events (behavior receipts and
source reviews) also need a person typing a one-time code at a terminal, and are
HMAC-signed with a local key kept outside the project. That raises the cost of
forgery; it is not independent proof of behavior.
"""
from __future__ import annotations
import argparse
import contextlib
import contextvars
import datetime as dt
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sys
import uuid

from gf_common import old_entry, GFError, VERSION, atomic_write, load_json, resolve_inside
from gf_platform import lock_exclusive, require_locking, unlock
from gf_profiles import BASE

ALLOWED = {"hypothesis", "customer_interview", "customer_action", "paid_test", "signed_commitment", "repeat_purchase", "feasibility_proof", "experiment_result", "decision_revision", "failure", "note", "source_review"}
LEDGER_NAME = 'experiment-ledger.jsonl'
BEHAVIOR = {"customer_action", "paid_test", "signed_commitment", "repeat_purchase", "feasibility_proof"}
ATTESTED = BEHAVIOR | {"source_review"}
NO_TTY = "Attested events need a person at a terminal. Run this command yourself, not through an agent."
# Reasons that mean "not confirmed on this machine yet" rather than "forged"; the scorer downgrades instead of failing.
# Signed intake fields a re-attestation copies unchanged, so nothing is lost or re-bound on a new machine.
CARRIED = ('material', 'gate_ids', 'result', 'consent', 'pii', 'row_hashes', 'evaluation_id', 'run_slug', 'idea_sha', 'idea_text', 'claim_digest')
UNCONFIRMED = ("receipt is unsigned", "signed with a different key", "no attestation key")
# W52: the bundled worked example is signed with a public DEMO key that verifies only in its own folder, unedited.
DEMO_DIR = Path(__file__).resolve().parents[1] / 'assets' / 'demo-proceed'
DEMO_KEY_ID = 'e1536591'
DEMO_PINNED = {"evaluation.json": "a5ea2d7196c5b00c92d7142c3efb142a821eb9ff86f5d20a81b988070dc0383b",
               "experiment-ledger.jsonl": "98febf8f033051f53bbd5959b86d74c98a96d76817120720bd1e96343d6420d1"}  # tools/make_demo_proceed.py prints these
DEMO_KEY_PROBLEM = 'signed with the bundled DEMO key, which counts only in the unedited demo folder'
_in_demo = contextvars.ContextVar('gf_in_demo', default=False)


def pinned_demo(folder):
    try:
        return Path(folder).resolve() == DEMO_DIR.resolve() and bool(DEMO_PINNED) and all(
            hashlib.sha256((DEMO_DIR / f).read_bytes()).hexdigest() == h for f, h in DEMO_PINNED.items())
    except OSError:
        return False


@contextlib.contextmanager
def demo_scope(folder):
    """Inside the pinned demo folder only, the DEMO key is the key; yields whether it applied."""
    token = _in_demo.set(pinned_demo(folder))
    try:
        yield _in_demo.get()
    finally:
        _in_demo.reset(token)


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
            if not isinstance(event, dict):
                raise ValueError(f'Invalid record at line {n}')
            actual_hash = event.pop('hash', None)
            expected_prev = records[-1]['hash'] if records else 'GENESIS'
            if event.get('seq') != n or event.get('previous_hash') != expected_prev or actual_hash != digest(event):
                raise ValueError(f'Ledger integrity failure at line {n}')
            event['hash'] = actual_hash
            records.append(event)
    return records


def artifact_digest(path, base):
    """Hash a file that must sit inside base (the ledger's folder); store its path relative to base."""
    if not path:
        return None
    root = Path(base).resolve(strict=True)
    try:
        p = resolve_inside(root, path)
    except GFError as exc:
        raise GFError(f'artifact {exc}', path=exc.path) from None
    if not p.exists():
        raise FileNotFoundError(f'artifact not found: {path}')
    if not p.is_file() or p.stat().st_size > 50 * 1024 * 1024:
        raise ValueError('Artifact must be a regular file <= 50 MB')
    hash_obj = hashlib.sha256()
    with p.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            hash_obj.update(chunk)
    return {'path': p.relative_to(root).as_posix(), 'sha256': hash_obj.hexdigest(), 'bytes': p.stat().st_size}


def config_dir():
    """Where the signing key lives by default; the agent guard protects this same folder."""
    return Path(os.environ.get('GF_CONFIG_DIR') or Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'greenfield')


def key_path():
    if os.environ.get('GF_ATTEST_KEY_FILE'):
        return Path(os.environ['GF_ATTEST_KEY_FILE']).expanduser()
    return config_dir() / 'attest.key'


def load_key():
    if _in_demo.get():
        return (DEMO_DIR / 'demo-attest.key').read_bytes()
    try:
        return key_path().read_bytes() or None
    except FileNotFoundError:
        return None


def ensure_key():
    """Create the signing key (0600, folder 0700) if missing; return (path, created)."""
    p = key_path()
    if load_key():
        return p, False
    p.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(p.parent, 0o700)
    atomic_write(p, secrets.token_bytes(32), mode=0o600)
    return p, True


def key_id(key):
    return hashlib.sha256(key).hexdigest()[:8]


def sign(key, event):
    body = {k: v for k, v in event.items() if k not in ('hash', 'sig')}
    return 'v1:' + hmac.new(key, canonical(body).encode('utf-8'), hashlib.sha256).hexdigest()


def signature_problem(event, key):
    """None when event carries a valid signature under key, else the reason."""
    if not event.get('sig'):
        return 'receipt is unsigned (recorded before v2.1)'
    if event.get('key_id') == DEMO_KEY_ID and not _in_demo.get():
        return DEMO_KEY_PROBLEM
    if not key:
        return 'no attestation key on this machine'
    if event.get('key_id') != key_id(key):
        return f"signed with a different key (key {event.get('key_id')})"
    if not hmac.compare_digest(str(event['sig']), sign(key, event)):
        return 'signature does not match: the event was edited'
    return None


def tty_confirm(summary):
    """Show summary on /dev/tty and require the person to type back a random code; raise GFError otherwise."""
    try:
        tty = open('/dev/tty', 'rb+', buffering=0)  # unbuffered: a terminal is not seekable
    except OSError:
        raise GFError(NO_TTY) from None
    with tty:
        say = lambda text: tty.write(text.encode('utf-8'))
        code = ''.join(secrets.choice('ABCDEFGHJKMNPQRSTUVWXYZ23456789') for _ in range(6))
        say('\nAbout to record a human-attested event:\n' + ''.join(f'  {k}: {v}\n' for k, v in summary.items()))
        say(f'Confirmation code: {code}\nType the code to confirm: ')
        if not hmac.compare_digest(tty.readline(64).decode('utf-8', 'replace').strip().upper(), code):
            raise GFError('Confirmation code did not match; nothing was recorded')
        p, created = ensure_key()
        if created:
            say(f'Created attestation key at {p}. Back it up: receipts verify only where this key is.\n')


def summary_of(fields):
    art = fields.get('artifact') or {}
    return {'kind': fields['kind'], 'hypothesis': fields['hypothesis'], 'outcome': fields['outcome'], 'attester': fields['attester'],
            'artifact': art.get('path'), 'sha256': (art.get('sha256') or '')[:12]}


def _write(path, fields, key=None):
    """Append one event under an exclusive lock; sign it when key is given."""
    path = Path(path)
    require_locking('greenfield ledger record')  # before the file is created, on platforms without fcntl
    # Exclusive OS-level advisory lock across processes; file remains append only.
    with open(path, 'a+', encoding='utf-8', opener=lambda p, fl: os.open(p, fl, 0o600)) as f:
        lock_exclusive(f.fileno(), 'greenfield ledger record')
        try:
            existing = read_ledger(path)
            data = {'seq': len(existing)+1, 'id': 'EV-'+uuid.uuid4().hex[:12], 'recorded_at': dt.datetime.now(dt.timezone.utc).isoformat(),
                    **fields, 'previous_hash': existing[-1]['hash'] if existing else 'GENESIS'}
            if key:
                data['key_id'] = key_id(key)
                data['sig'] = sign(key, data)
            data['hash'] = digest(data)
            f.write(canonical(data)+'\n')
            f.flush()
            os.fsync(f.fileno())
            return data
        finally:
            unlock(f.fileno())


def append(path, kind, project, hypothesis, outcome='', artifact=None, attester='', observed_at='', notes='', pillars=None, claim_id='', experiment_id='', confirm=None, extra=None, preview=None):
    confirm = confirm or tty_confirm  # looked up per call, so confirm_via reads the live tty_confirm
    if kind not in ALLOWED:
        raise ValueError('Invalid kind')
    if not project.strip() or not hypothesis.strip():
        raise ValueError('Project and hypothesis/subject required')
    attested = kind in ATTESTED
    if attested and (not attester.strip() or not artifact):
        raise ValueError('Behavior event requires a named HUMAN attester and actual local evidence artifact')
    if observed_at:
        if dt.date.fromisoformat(observed_at) > dt.date.today():
            raise ValueError('observed_at is in the future')
    if kind == 'source_review' and (not claim_id or outcome not in ('supported', 'contradicted', 'unclear')):
        raise ValueError('Source review needs claim ID and outcome supported|contradicted|unclear')
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fields = {'observed_at': observed_at or dt.date.today().isoformat(), 'kind':kind, 'project':project.strip(),
              'hypothesis':hypothesis.strip(), 'outcome':outcome.strip(), 'notes':notes.strip(),
              'attester':attester.strip() if attested else '', 'human_attested': attested,
              'artifact':artifact_digest(artifact, path.parent), 'pillar_ids': sorted(set(pillars or [])), 'claim_id':claim_id,
              'experiment_id':experiment_id, **(extra or {})}
    if not attested:
        return _write(path, fields)
    confirm({**summary_of(fields), **(preview or {})})  # before the lock, so a slow human never blocks other writers
    fields['confirm_via'] = via(confirm)
    key = load_key()
    if not key:
        raise GFError('no attestation key on this machine', path=key_path())
    return _write(path, fields, key)


def trusted_artifact(events, event, key):
    """(artifact meta, None) when event is signed or has a valid signed re-attestation; else (None, reason)."""
    problem = signature_problem(event, key)
    if not problem:
        return event['artifact'], None
    if problem == DEMO_KEY_PROBLEM:  # no reattestation rescues a DEMO-signed event
        return None, problem
    for r in reversed(events):
        if r['kind'] == 'reattestation' and r.get('reattests') == event['id'] and not signature_problem(r, key) \
                and r.get('artifact') and r['artifact']['sha256'] == event['artifact']['sha256']:
            return r['artifact'], None
    return None, problem


def via(confirm):
    """Self-reported: catches an injected confirm, not a script written to lie (W49)."""
    return 'tty' if confirm is tty_confirm else 'injected'


def tty_adopt(event):
    """Ask at the terminal for a legacy receipt's --as type and --result; blank leaves them out (evidence only)."""
    from gf_materials import MATERIALS, RESULTS
    try:
        tty = open('/dev/tty', 'rb+', buffering=0)
    except OSError:
        raise GFError(NO_TTY) from None
    with tty:
        def ask(q):
            tty.write(q.encode('utf-8'))
            return tty.readline(64).decode('utf-8', 'replace').strip()
        fits = [m for m, row in MATERIALS.items() if row[0] == event['kind']]
        material = ask(f"--as type for {event['id']} ({', '.join(fits)}; blank for none): ")
        result = ask('--result (pass, mixed, fail; blank for none): ')
    if (material and material not in fits) or (result and result not in RESULTS):
        raise GFError(f'--as must be one of {", ".join(fits)} and --result one of {", ".join(RESULTS)}; nothing was recorded')
    return material or None, result or None


def legacy_run(folder):
    """evidence init marked this run legacy, and its history starts there (start always writes the first line)."""
    try:
        data = load_json(folder / 'evaluation.json')
    except (OSError, ValueError):
        return False
    import gf_history
    lines = gf_history.read(folder)
    first = next((x for x in lines if 'snapshot' in x), None)
    return data.get('legacy') is True and (first is None or first.get('origin') == 'legacy')


def reattest(path, confirm=None, adopt=None):
    """Re-confirm this evaluation's unsigned or other-key attested events, and adopt pre-wave events in a legacy run."""
    confirm, adopt = confirm or tty_confirm, adopt or tty_adopt
    path = Path(path)
    folder = path.parent.resolve()
    events = read_ledger(path)
    key = load_key()
    anchor = next((e['evaluation_id'] for e in events if e.get('sig') and e.get('evaluation_id')), None)
    first_signed = next((i for i, e in enumerate(events) if e.get('sig')), len(events))
    legacy = legacy_run(folder)
    adopted = {r.get('reattests') for r in events if r['kind'] == 'reattestation' and r.get('evaluation_id') and not signature_problem(r, key)}
    out = []
    for i, e in enumerate(events):
        if e['kind'] not in ATTESTED or not e.get('human_attested') or not e.get('artifact'):
            continue
        if e.get('key_id') == DEMO_KEY_ID:
            out.append({'id': e['id'], 'action': 'refused', 'reason': DEMO_KEY_PROBLEM})
            continue
        adopting = not e.get('evaluation_id')
        if adopting:
            if e['id'] in adopted:
                continue
            if not legacy:
                out.append({'id': e['id'], 'action': 'refused', 'reason': 'has no evaluation binding; only a run marked legacy by evidence init adopts it: re-record it with greenfield evidence add'})
                continue
        else:
            meta, problem = trusted_artifact(events, e, key)
            if e['evaluation_id'] != anchor or meta or not problem.startswith(UNCONFIRMED):
                continue
        if not e.get('sig') and not (legacy and i < first_signed):
            out.append({'id': e['id'], 'action': 'refused', 'reason': 'never signed, and recorded after the first signed event'})
            continue
        try:
            doc = artifact_digest(e['artifact']['path'], folder)
        except (OSError, ValueError) as exc:  # GFError (outside the run folder) is a ValueError
            out.append({'id': e['id'], 'action': 'skipped', 'reason': str(exc)})
            continue
        if doc['sha256'] != e['artifact']['sha256']:
            out.append({'id': e['id'], 'action': 'skipped', 'reason': 'artifact has changed since attestation'})
            continue
        fields = {'observed_at': e.get('observed_at', ''), 'kind': 'reattestation', 'reattests': e['id'], 'project': e.get('project', ''),
                  'hypothesis': e.get('hypothesis', ''), 'outcome': e.get('outcome', ''), 'notes': f"re-attests {e['kind']} {e['id']}",
                  'attester': e.get('attester', ''), 'human_attested': True, 'artifact': doc, 'pillar_ids': e.get('pillar_ids', []),
                  'claim_id': e.get('claim_id', ''), 'experiment_id': e.get('experiment_id', ''),
                  **{k: e[k] for k in CARRIED if k in e}}
        preview = {'re-confirming': f"{e['kind']} {e['id']} recorded {e.get('recorded_at', '')}"}
        if not e.get('sig'):
            preview['note'] = 'This event was never signed on this machine; attest only if you recorded it yourself.'
        if adopting:
            import gf_materials
            data = load_json(folder / 'evaluation.json')
            preview['current idea'] = gf_materials.idea_text(data['project'])
            fields.update(gf_materials.binding(data, folder), legacy=True)
            if e['kind'] in BEHAVIOR:
                material, result = adopt(e)
                fields.update({k: v for k, v in (('material', material), ('result', result)) if v})
        confirm({**preview, **summary_of({**fields, 'kind': e['kind']})})
        fields['confirm_via'] = via(confirm)
        key = load_key()
        if not key:
            raise GFError('no attestation key on this machine', path=key_path())
        out.append({'id': e['id'], 'action': 'adopted' if adopting else 'reattested', 'event': _write(path, fields, key)['id']})
    return out


def verified_behavior(path, event_id, pillar=None):
    try:
        events = read_ledger(path)
    except (OSError, ValueError):
        return False, 'ledger unavailable or hash chain invalid'
    try:
        return _verify(path, events, event_id, pillar)
    except (KeyError, TypeError, AttributeError):  # a hand-written event with missing or wrong-typed fields
        return False, 'malformed ledger event'


def _verify(path, events, event_id, pillar):
    event = next((e for e in events if e['id'] == event_id), None)
    if not event:
        return False, 'event not found'
    if event['kind'] not in BEHAVIOR or not event['human_attested'] or not event.get('artifact'):
        return False, 'event is not a human-attested behavioral observation'
    if pillar and pillar not in event['pillar_ids']:
        return False, 'event not linked to this pillar'
    meta, problem = trusted_artifact(events, event, load_key())
    if problem:
        return False, problem
    try:
        current = artifact_digest(meta['path'], Path(path).parent)
    except GFError:
        return False, 'artifact outside evaluation folder'
    except (OSError, ValueError):
        return False, 'artifact missing or unreadable'
    if current['sha256'] != meta['sha256']:
        return False, 'artifact has changed since attestation'
    # shortcut: legacy absolute paths still verify (inside the folder) for one release, then become a failure.
    note = '; receipt stores an absolute path; re-attest to make it portable' if Path(meta['path']).is_absolute() else ''
    return True, 'local attestation and receipt hash intact (not independent proof)' + note


def reviewed_claims(ledger_path, report_path):
    """Most recent human review of each claim against the same immutable report digest."""
    base = Path(ledger_path).parent
    report_file = resolve_inside(base, report_path, must_exist=True)
    report = artifact_digest(report_file, base)
    records = read_ledger(ledger_path)
    key = load_key()
    entries = {c.get('claim_id'): c for c in load_json(report_file).get('claims',[])}
    try:
        claims = {c.get('id'): c for c in load_json(base / 'evaluation.json').get('claims', []) if isinstance(c, dict)}
    except (OSError, ValueError, AttributeError):
        claims = {}
    anchor = next((e['evaluation_id'] for e in records if e.get('sig') and e.get('evaluation_id')), None)
    out = {}
    import gf_evidence
    for e in records:
        if e['kind'] == 'source_review' and e['human_attested'] and e.get('artifact') and e['claim_id'] in entries:
            if e.get('evaluation_id') and (e['evaluation_id'] != anchor or e.get('run_slug') != base.resolve().name):
                continue
            meta, _ = trusted_artifact(records, e, key)
            if not meta:
                continue
            entry, claim = entries[e['claim_id']], claims.get(e['claim_id'], {})
            # Bound to its own entry, so re-checks and other claims' edits leave it valid; older reviews bind to the whole report.
            bound = (e['entry_digest'] == gf_evidence.entry_digest(entry, claim) and not gf_evidence.entry_problem(entry, claim, key)) if e.get('entry_digest') else meta['sha256'] == report['sha256']
            if bound:
                out[e['claim_id']] = e['outcome']
    return out


def _review_binding(args):
    """Sign the reviewed claim's digest and any gate into a source review, so a rewritten claim loses both (W43)."""
    if args.kind != 'source_review':
        return None
    import gf_materials
    try:
        data = load_json(Path(args.ledger).parent / 'evaluation.json')
    except (OSError, ValueError):
        data = {}
    claim = next((c for c in data.get('claims', []) if isinstance(c, dict) and c.get('id') == args.claim_id), None)
    gate = getattr(args, 'gate', None)
    out = {'gate_ids': [gate] if gate else []}
    if claim:
        import gf_evidence
        try:
            entry = next((c for c in load_json(args.artifact).get('claims', []) if c.get('claim_id') == args.claim_id), None)
        except (OSError, ValueError, TypeError, AttributeError):
            entry = None
        if not entry or gf_evidence.entry_problem(entry, claim, load_key()):
            raise GFError(f'{args.claim_id}: not produced by greenfield sources check', hint='greenfield sources check')
        out.update(claim_digest=gf_materials.claim_digest(claim), entry_digest=gf_evidence.entry_digest(entry, claim), **gf_materials.binding(data, Path(args.ledger).parent))
    return out


def _project_label(args):
    """--project-name is a label only: binding is the signed evaluation_id, run_slug and idea_sha."""
    if args.project:
        return args.project
    try:
        return load_json(Path(args.ledger).parent / 'evaluation.json')['project']['name'] or Path(args.ledger).resolve().parent.name
    except (OSError, ValueError, KeyError, TypeError):
        return Path(args.ledger).resolve().parent.name


def handle(args):
    """Run one parsed ledger command (record, verify, summary, reattest); return its JSON-ready result."""
    if args.command=='record':
        if args.kind in BEHAVIOR:
            raise GFError(f'{args.kind} is a receipt: use greenfield evidence add', hint='greenfield evidence types')
        # A typed --artifact is relative to the shell's folder; append() then requires it inside the ledger's folder.
        artifact=str(Path(args.artifact).absolute()) if args.artifact else None
        hypothesis=args.hypothesis or (f'source review {args.claim_id}' if args.kind=='source_review' else '')
        return append(args.ledger,args.kind,_project_label(args),hypothesis,args.outcome,artifact,args.attester,args.observed_at,args.notes,args.pillar,args.claim_id,args.experiment_id,extra=_review_binding(args))
    if args.command=='reattest':
        return reattest(args.ledger)
    if args.command=='reidea':
        import gf_materials
        return gf_materials.reidea(args.ledger)
    events=read_ledger(args.ledger)
    value={'valid':True,'events':len(events),'last_hash':events[-1]['hash'] if events else 'GENESIS'}
    if args.command=='summary':
        from collections import Counter
        value['by_type']=dict(Counter(e['kind'] for e in events))
        value['behavior_receipts']=[{'id':e['id'],'kind':e['kind'],'pillar_ids':e['pillar_ids'],'integrity':verified_behavior(args.ledger,e['id'])[0]} for e in events if e['kind'] in BEHAVIOR]
        first, key = next((e for e in events if e.get('sig') and e['kind'] != 'reattestation'), None), load_key()
        if first and key and first.get('key_id') != key_id(key):
            value['warnings'] = [f"this machine's attestation key ({key_id(key)}) is not the one that signed the first receipt ({first.get('key_id')})"]
    return value


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--version',action='version',version=f'%(prog)s {VERSION}')
    sub=ap.add_subparsers(dest='command', required=True)
    p=sub.add_parser('record')
    p.add_argument('--ledger',required=True)
    p.add_argument('--kind',required=True,choices=sorted(ALLOWED))
    p.add_argument('--project',default='')
    p.add_argument('--hypothesis',default='')
    p.add_argument('--outcome',default='')
    p.add_argument('--artifact')
    p.add_argument('--attester',default='')
    p.add_argument('--observed-at',default='')
    p.add_argument('--notes',default='')
    p.add_argument('--pillar',action='append',default=[],choices=sorted(BASE))
    p.add_argument('--claim-id',default='')
    p.add_argument('--experiment-id',default='')
    v=sub.add_parser('verify');v.add_argument('--ledger',required=True)
    s=sub.add_parser('summary');s.add_argument('--ledger',required=True)
    r=sub.add_parser('reattest',help='interactively re-confirm unsigned attested events');r.add_argument('--ledger',required=True)
    i=sub.add_parser('reidea',help='carry receipts across a typo-sized edit of the idea');i.add_argument('--ledger',required=True)
    args=ap.parse_args(argv)
    try:
        print(json.dumps(handle(args),indent=2))
    except (OSError, ValueError, KeyError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr);return 2
    return 0

if __name__=='__main__':
    raise SystemExit(old_entry(main,'gf_ledger.py','greenfield ledger'))
