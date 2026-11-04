#!/usr/bin/env python3
"""Local, read-only Greenfield Mission Control. Python 3.11+, standard library only.

Only metadata is recorded by default. No prompts, reasoning, raw tool I/O, environment,
network requests or agent responses are captured. Web server binds to loopback only.
"""
from __future__ import annotations
import argparse
import contextlib
import datetime as dt
import hashlib
import http.server
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import sys
import threading
import time
import unicodedata
from urllib.parse import urlsplit, urlunsplit, parse_qs
from uuid import uuid4
from gf_common import old_entry, VERSION, GFError, atomic_write_json, gitignore_missing, load_json, report, resolve_inside
from gf_platform import lock_exclusive, unlock
from gf_roles import ROLES as _ROLES, REDTEAM, SPECIALISTS, normalize

AGENTS = [r.claude_id for r in _ROLES]
VALID_EVENTS = {"run_started", "run_completed", "run_failed", "agent_started", "agent_completed", "agent_failed", "tool_started", "tool_completed", "tool_failed", "source_seen", "artifact_created", "note", "token_usage", "warning", "task_planned", "task_started", "task_completed", "task_failed", "run_resumed"}
VALID_RUN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
DEFAULT_PATH = ".greenfield-observe"
ASSETS = Path(__file__).resolve().parent.parent / "assets"
DEMO_RESEARCH = "demo-research"  # bundled sample folder under ASSETS, labelled as sample data
PROVIDER_NAMES = {"claude": "Claude Code", "codex": "Codex", "both": "Claude Code + Codex"}  # demo/manual stay hidden


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")


def safe_text(value, limit=150):
    # Only short labels: never capture raw prompts, tool inputs or tool responses.
    return re.sub(r"[\x00-\x1f\x7f]", " ", str(value or ""))[:limit]


def clean_agent(name):
    r = normalize(safe_text(name, 90))
    return r.claude_id if r else "orchestrator"


def safe_url(value):
    if not isinstance(value, str) or len(value) > 1600:
        return ""
    try:
        u = urlsplit(value)
        host = u.hostname or ""
        if u.scheme not in ("http", "https") or not host or u.username or u.password:
            return ""
        if host.lower() in ("localhost", "localhost.localdomain") or host.endswith(".local"):
            return ""
        try:
            address = ipaddress.ip_address(host)
            if not address.is_global:
                return ""
        except ValueError:
            pass
        if not re.fullmatch(r"[A-Za-z0-9.-]{1,253}", host):
            return ""
        # No query params/fragments: could contain sensitive information.
        return urlunsplit((u.scheme, u.netloc, u.path[:500], "", ""))
    except Exception:
        return ""


def storage(project):
    return Path(project).expanduser().resolve() / DEFAULT_PATH


def private_dir(path):
    """Create path; folders at or below .greenfield-observe are made 0700 whatever the umask."""
    for d in reversed([path, *path.parents]):
        if DEFAULT_PATH in d.parts and not d.exists():
            d.mkdir(mode=0o700, exist_ok=True)  # another thread may win the race
            d.chmod(0o700)
    path.mkdir(parents=True, exist_ok=True)


def atomic_json(path, payload):
    private_dir(path.parent)
    atomic_write_json(path, payload, mode=0o600)


def tighten(project):
    """chmod a loose .greenfield-observe tree (older versions) to 0700/0600; note it once on stderr."""
    root, changed = storage(project), 0
    if not root.is_dir():
        return
    for p in [root, *root.rglob("*")]:
        try:
            st = p.lstat()
            if stat.S_ISLNK(st.st_mode) or not stat.S_IMODE(st.st_mode) & 0o077:
                continue
            p.chmod(0o700 if stat.S_ISDIR(st.st_mode) else 0o600)
            changed += 1
        except OSError:
            pass  # chmod-less filesystems: best effort
    if changed:
        print(f"Tightened permissions on {changed} item(s) in {root}", file=sys.stderr)


def git_ignore_hint(project):
    if (Path(project) / ".git").exists() and gitignore_missing(project, (".greenfield-observe/",)):
        print("hint: .greenfield-observe/ is not in .gitignore; run install.py --gitignore to keep it out of commits", file=sys.stderr)


def active_run(project):
    try:
        data = json.loads((storage(project) / "active.json").read_text())
        name = data.get("run_id", "")
        return name if VALID_RUN.fullmatch(name) else None
    except (OSError, ValueError, TypeError):
        return None


def file_paths(project, run_id):
    if not VALID_RUN.fullmatch(run_id):
        raise ValueError("Invalid run ID")
    base = storage(project) / "runs" / run_id
    return base / "meta.json", base / "events.jsonl"


class ActiveRunError(GFError):
    def __init__(self, run_id, idea, created_at):
        try:
            since = dt.datetime.fromisoformat(created_at).astimezone(dt.timezone.utc).strftime("%H:%M UTC")
        except (TypeError, ValueError):
            since = "an earlier time"
        super().__init__(f"Run {run_id} ({idea!r}) has been active since {since}.", hint="Keep using it, or run `start --new` to replace it.")
        self.run_id, self.idea, self.created_at = run_id, idea, created_at


@contextlib.contextmanager
def active_lock(project):
    root = storage(project)
    private_dir(root)
    fd = os.open(root / ".active.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        lock_exclusive(fd, "greenfield start")
        yield
    finally:
        os.close(fd)  # closing releases the flock


def running_run(project):
    """(run_id, meta) of the active real run if it is still running, else None. Demo and stale runs never block."""
    rid = active_run(project)
    if not rid:
        return None
    try:
        state = current_state(project, rid)
    except (OSError, ValueError):
        print(f"note: active run {rid} is missing or unreadable; ignoring it", file=sys.stderr)
        return None
    meta = state["meta"]
    return (rid, meta) if state["status"] == "running" and not meta.get("demo") else None


def research_rel(project, path):
    """research_dir as stored in meta.json: relative to the project root; GFError if it escapes."""
    root = Path(project).expanduser().resolve()
    return resolve_inside(root, path).relative_to(root).as_posix()


def research_base(project, meta):
    """Demo runs read the bundled sample folder; real runs read inside the project."""
    return ASSETS if meta.get("demo") else Path(project).expanduser().resolve()


def link_research(project, run_id, path):
    meta_path, _ = file_paths(project, run_id)
    meta = load_json(meta_path)
    if meta.get("demo"):
        raise GFError("demo runs always read the bundled sample folder", hint="start a real run to link your research")
    meta["research_dir"] = research_rel(project, path)
    atomic_json(meta_path, meta)
    return meta["research_dir"]


def new_run(project, idea, provider="both", demo=False, replace=False, research_dir=None):
    run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:6]
    meta_path, _ = file_paths(project, run_id)
    extra = {"research_dir": DEMO_RESEARCH if demo else research_rel(project, research_dir)} if demo or research_dir else {}
    with active_lock(project):  # check-then-write must be atomic across processes
        old = running_run(project)
        if old and not demo and not replace:
            raise ActiveRunError(old[0], old[1].get("idea", ""), old[1].get("created_at"))
        atomic_json(meta_path, {"run_id": run_id, "idea": safe_text(idea, 200), "provider": provider, "created_at": now(), "demo": bool(demo), **extra})
        if old and not demo:
            emit(project, old[0], "warning", summary=f"Superseded by run {run_id}")
        if not (old and demo):  # sample data never displaces a real run
            atomic_json(storage(project) / "active.json", {"run_id": run_id})
    emit(project, run_id, "run_started", provider=provider, summary="Research run initialized")
    return run_id


SLUG_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,47}\Z")


def slugify(idea, fallback_date):
    """ASCII slug of at most 48 characters, cut on a word boundary; idea-YYYYMMDD when nothing usable remains."""
    s = re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", idea).encode("ascii", "ignore").decode().lower()).strip("-")
    if len(s) > 48:
        s = (s[:48].rsplit("-", 1)[0] if s[48] != "-" and "-" in s[:48] else s[:48]).strip("-")
    return s or "idea-" + fallback_date.replace("-", "")


def scaffold(project, args):
    """greenfield start: guard, research folder, dated evaluation.json, run record, task plan (W24)."""
    project = Path(project).expanduser().resolve()
    as_of = args.as_of or dt.date.today().isoformat()  # local date
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", as_of) or dt.date.fromisoformat(as_of).isoformat() != as_of:
        raise GFError(f"--as-of {as_of!r} is not a YYYY-MM-DD date", hint="greenfield start --idea '...' --as-of 2026-11-03")
    old = None if args.new else running_run(project)
    if old:
        raise ActiveRunError(old[0], old[1].get("idea", ""), old[1].get("created_at"))
    slug = args.slug or slugify(args.idea, as_of)
    if not SLUG_RE.match(slug):
        raise GFError(f"slug {slug!r} must match [a-z0-9][a-z0-9-]{{0,47}}", hint="greenfield start --idea '...' --slug my-idea")
    folder = resolve_inside(project, args.research_dir or f"research/greenfield/{slug}")
    ev = folder / "evaluation.json"
    if ev.exists():
        raise GFError("evaluation.json already exists; not overwriting", path=ev, hint="pass --slug NAME, or run `greenfield status`")
    (folder / "specialists").mkdir(parents=True, exist_ok=True)
    folder = resolve_inside(project, folder)  # re-check after mkdir: a symlink must not have redirected it
    data = load_json(ASSETS / "evaluation-template.json")
    data["as_of"] = as_of
    data["project"].update(name=safe_text(args.idea, 80), idea=safe_text(args.idea, 200), business_model=args.model)
    for key, value in (("initial_customer", args.customer), ("geography", args.geography)):
        if value:
            data["project"][key] = value
    data["execution"]["mode"] = "not_started"
    data["evidence_ledger"], data["verification_report"] = "experiment-ledger.jsonl", "source-verification.json"
    atomic_write_json(ev, data, mode=0o600)
    rid = new_run(project, args.idea, args.provider, replace=args.new, research_dir=folder)
    if not args.no_plan:
        import gf_runs
        gf_runs.plan(project, rid)
    rel = folder.relative_to(project).as_posix()
    prompt = f"Evaluate this idea with the greenfield-business-evaluator skill: {args.idea} (depth: {args.depth}; research folder: {rel})"
    return {"run_id": rid, "slug": slug, "research_dir": rel, "evaluation": f"{rel}/evaluation.json",
            "next": [f"Claude Code: /greenfield-business-evaluator {args.idea}", f"Codex: {prompt}", "greenfield dashboard"]}


def emit(project, run_id, event, *, provider="manual", agent="orchestrator", agent_id="", session_id="", summary="", tool="", url="", tokens=0):
    if event not in VALID_EVENTS:
        raise ValueError("Unsupported event")
    meta_path, path = file_paths(project, run_id)
    if not meta_path.is_file():
        raise ValueError("Run not initialized")
    item = {"id": uuid4().hex, "timestamp": now(), "run_id": run_id, "event": event, "provider": safe_text(provider, 25), "agent": clean_agent(agent),
            "agent_id": safe_text(agent_id, 80), "session_id": safe_text(session_id, 80), "summary": safe_text(summary, 160),
            "tool": safe_text(tool, 64), "url": safe_url(url), "tokens": max(0, int(tokens or 0))}
    private_dir(path.parent)
    # O_APPEND single-line append provides good cross-process safety for small records.
    # The JSON payload stays <4 KB; reader skips a torn trailing line if interrupted.
    blob = (json.dumps(item, ensure_ascii=True, separators=(",", ":")) + "\n").encode()
    fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600)
    try:
        os.write(fd, blob)
    finally:
        os.close(fd)
    return item


def parse_events(project, run_id):
    _, path = file_paths(project, run_id)
    items = []  # whole log is read on purpose: status and counts need the newest events
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                try:
                    item = json.loads(line)
                    if isinstance(item, dict):
                        items.append(item)
                except ValueError:
                    continue
    except FileNotFoundError:
        pass
    return items


def reconcile(agent, task):
    """One shown status from the hook status and the checkpoint status (W20 table): label, tone, note, warn."""
    s = agent["status"]
    d = lambda label, tone, note="", warn=False: {"label": label, "tone": tone, "note": note, "warn": warn}
    if s == "failed" or task == "failed":
        return d("Failed", "bad", f"Agent failed: {agent['activity']}" if s == "failed" else "Checkpoint failed", True)
    if s == "completed":
        return d("Done", "good", *{"completed": ("Checkpointed",), "queued": ("Not checkpointed", True), "running": ("Not checkpointed", True)}.get(task, ()))
    if s == "running":
        return d("Running", "accent", agent["activity"])
    if s == "quiet":
        return d("Quiet", "neutral", "No activity for 5 min; not a failure")
    if task == "running":
        return d("Claimed", "accent", "Claimed in checkpoints, no hook events yet")
    if task == "completed":
        return d("Done", "good", "From checkpoint (reused or hooks off)")
    return d("Queued", "neutral", "Waits for all 8 specialists" if agent["name"] == REDTEAM.claude_id else "")


def current_state(project, run_id, since=None):
    meta_path, _ = file_paths(project, run_id)
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    events = parse_events(project, run_id)
    agents = {name: {"name": name, "status": "queued", "started_at": None, "ended_at": None, "last_at": None, "tools": 0, "sources": 0, "errors": 0, "activity": "Awaiting dispatch", "provider": None} for name in AGENTS}
    total_tokens = 0
    started = set()
    for e in events:
        name, kind = e.get("agent"), e.get("event")
        total_tokens += max(0, int(e.get("tokens") or 0))
        if name not in agents:
            continue
        a = agents[name]
        a["last_at"] = e.get("timestamp")
        if e.get("provider"):
            a["provider"] = e["provider"]
        if kind == "agent_started":
            a.update(status="running", started_at=e.get("timestamp"), ended_at=None, activity="Agent started")
            started.add(name)
        elif kind == "agent_completed":
            a.update(status="completed", ended_at=e.get("timestamp"), activity="Finished research")
        elif kind == "agent_failed":
            a.update(status="failed", ended_at=e.get("timestamp"), activity=e.get("summary") or "Agent failed")
            a["errors"] += 1
        elif kind == "tool_started":
            a["tools"] += 1
            a["activity"] = "Using " + (e.get("tool") or "tool")
        elif kind == "source_seen":
            a["sources"] += 1
            a["activity"] = "Source recorded"
        elif kind in ("tool_failed", "warning"):
            a["errors"] += 1
            a["activity"] = e.get("summary") or "Tool warning"
        elif kind == "artifact_created":
            a["activity"] = e.get("summary") or "Artifact created"
    for a in agents.values():
        if a["status"] == "running" and a["last_at"]:
            try:
                last = dt.datetime.fromisoformat(a["last_at"])
                if (dt.datetime.now(dt.timezone.utc) - last).total_seconds() > 300:
                    a["status"] = "quiet"  # No heartbeat is not a confirmed failure.
            except ValueError:
                pass
    status = "running"
    if any(e["event"] == "run_completed" for e in events):
        status = "completed"
    if any(e["event"] == "run_failed" for e in events):
        status = "failed"
    task_info = {}
    estimated_cost_usd = None
    try:
        task_doc = json.loads((storage(project) / 'runs' / run_id / 'task-manifest.json').read_text(encoding='utf-8'))
        rate = task_doc.get('cost_rate_usd_per_million_tokens')
        if type(rate) in (int,float) and rate>=0 and total_tokens>0:
            estimated_cost_usd = round(total_tokens * rate / 1_000_000, 4)
        task_info = {'tasks': {role: info.get('status') for role,info in task_doc['tasks'].items()},
                     'coverage': task_doc.get('coverage',{}),
                     'attempts': {role: info.get('attempts', 0) for role, info in task_doc['tasks'].items()},
                     'completed': sum(info.get('status')=='completed' for info in task_doc['tasks'].values())}
        task_info['mtime_ns'] = (storage(project) / 'runs' / run_id / 'task-manifest.json').stat().st_mtime_ns
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    tasks = task_info.get("tasks", {})
    for a in agents.values():
        a["display"] = reconcile(a, tasks.get(a["name"]))
    hooked = any(e.get("provider") in ("claude", "codex", "codex-cli") and e.get("agent") in agents for e in events)
    ends = [e.get("timestamp") for e in events if e.get("event") in ("run_completed", "run_failed")]
    try:
        decision_etag = decision_view(project, run_id)["etag"]
    except Exception:  # the decision panel reports its own errors; state must still load
        decision_etag = None
    rev = hashlib.sha256(repr((len(events), events[-1].get("id") if events else None, task_info.get("mtime_ns"), decision_etag,
                               tuple(a["status"] == "quiet" for a in agents.values()))).encode()).hexdigest()[:16]
    feed = {"events": events[-300:][::-1]}
    if since is not None:
        at = next((i for i in range(len(events) - 1, -1, -1) if events[i].get("id") == since), None)
        feed = {"events_delta": events[-300:][::-1] if at is None else events[at + 1:][-300:][::-1], "reset": at is None}
    return {"meta": meta, "status": status, "agents": list(agents.values()), **feed, "event_count": len(events), "checkpoints": task_info,
            "rev": rev, "decision_etag": decision_etag, "provider_name": PROVIDER_NAMES.get(meta.get("provider"), ""),
            "hooks_off": not hooked and any(v in ("running", "completed") for v in tasks.values()),
            "run_window": {"start": meta.get("created_at"), "end": ends[-1] if ends else None},
            "roles": [{"id": r.claude_id, "name": r.display, "pillar": r.pillar} for r in _ROLES],
            "stats": {"started_agents": len(started), "finished_agents": sum(a["status"] == "completed" for a in agents.values()),
                      "active_agents": sum(a["status"] in ("running", "quiet") for a in agents.values()),
                      "tool_calls": sum(e["event"] == "tool_started" for e in events),
                      "source_events": sum(e["event"] == "source_seen" for e in events), "reported_tokens": total_tokens, "estimated_cost_usd": estimated_cost_usd,
                      "warnings": sum(e["event"] in ("warning", "tool_failed", "agent_failed") for e in events)}}


_decision_cache = {}  # (project, run) -> (key, view, extra input paths)


def _stat(path):
    try:
        st = path.stat()
        return st.st_mtime_ns, st.st_size
    except (OSError, ValueError):
        return None


def _research(project, run_id):
    """(meta, base, research folder) or a non-ok state name in place of the folder."""
    meta = load_json(file_paths(project, run_id)[0])
    rd, base = meta.get("research_dir"), research_base(project, meta)
    if not isinstance(rd, str) or not rd:
        return meta, base, "no_research_dir"
    try:
        folder = resolve_inside(base, rd)
        resolve_inside(base, folder / "evaluation.json")  # a symlinked evaluation must not leave the project either
    except GFError:
        return meta, base, "invalid_path"
    return meta, base, folder


def decision_view(project, run_id):
    """Verdict recomputed from evaluation.json (never read from decision.json), cached on input mtimes and sizes."""
    project = Path(project).expanduser().resolve()
    meta, base, folder = _research(project, run_id)
    if isinstance(folder, str):
        view = _decision_state(project, run_id, meta, folder)
        view["etag"] = hashlib.sha256(repr((folder, meta.get("research_dir"), view["next_step"])).encode()).hexdigest()[:16]
        return view
    ev, dec = folder / "evaluation.json", folder / "decision.json"
    hit = _decision_cache.get((project, run_id))
    pre = (str(folder), _stat(ev), _stat(dec))
    if hit and hit[0] == pre + tuple(_stat(p) for p in hit[2]):
        return hit[1]
    view, extra = _decide(project, run_id, meta, base, folder, ev, dec)
    key = pre + tuple(_stat(p) for p in extra)
    view["etag"] = hashlib.sha256(repr(key).encode()).hexdigest()[:16]
    _decision_cache[(project, run_id)] = (key, view, extra)
    return view


def _decision_state(project, run_id, meta, state, **fields):
    rd = meta.get("research_dir") if isinstance(meta.get("research_dir"), str) else None
    if state == "no_research_dir":
        found = sorted(project.glob("research/greenfield/*/evaluation.json"))
        guess = found[0].parent.relative_to(project).as_posix() if len(found) == 1 else "research/greenfield/<slug>"  # suggest, never guess
        step = {"text": "Link this run to its research folder", "command": f"gf_observe.py link --research-dir {guess} --run {run_id}"}
    elif state == "invalid_path":
        step = {"text": "The linked folder is outside this project; link one inside it", "command": f"gf_observe.py link --research-dir research/greenfield/<slug> --run {run_id}"}
    elif state == "no_evaluation":
        step = {"text": "Specialists still running, or write evaluation.json from the template", "command": f"cp assets/evaluation-template.json {rd}/evaluation.json"}
    else:
        step = {"text": "Fix the listed errors, then re-run the scorer with --json", "command": f"score_project.py {rd}/evaluation.json --json"}
    return {"state": state, "research_dir": rd, "demo": bool(meta.get("demo")), "next_step": step, "errors": [], **fields}


def _decide(project, run_id, meta, base, folder, ev, dec):
    from score_project import VERDICTS, gap_text, recompute_decision, summarize_warnings, verdict_gap
    from gf_portfolio import stored_mismatch
    if not ev.is_file():
        return _decision_state(project, run_id, meta, "no_evaluation"), ()
    try:
        data = load_json(ev)
    except GFError:
        data = {}
    extra = []
    for key in ("evidence_ledger", "verification_report"):  # the validator reads these, so they key the cache and staleness
        with contextlib.suppress(GFError, TypeError):
            if isinstance(data.get(key), str) and data[key]:
                extra.append(resolve_inside(folder, data[key]))
    result, errors, _ = recompute_decision(ev, base)
    if errors:
        return _decision_state(project, run_id, meta, "invalid", errors=[safe_text(e, 300) for e in errors[:10]], error_count=len(errors)), extra
    rd = meta["research_dir"]
    stored = {"present": dec.exists(), "decision": None, "matches": True}
    stale = False
    if stored["present"]:
        try:
            said, why = stored_mismatch(resolve_inside(base, dec), result)
        except GFError:
            said, why = None, "decision.json is outside the project"
        stored.update(decision=said if isinstance(said, str) and said in VERDICTS else None, matches=why is None)
        newest = max((s[0] for s in map(_stat, [ev, *extra]) if s), default=0)
        stale = (_stat(dec) or (0,))[0] < newest
    qs, es, d = result["quality_scores"], result["evidence_scores"], result["decision"]
    exp = next((x for x in data.get("experiments") or [] if isinstance(x, dict)), None) if isinstance(data.get("experiments"), list) else None
    bet = {"id": safe_text(exp.get("id"), 20), "text": safe_text(exp.get("hypothesis"), 200)} if exp and exp.get("hypothesis") else None
    rescore = f"score_project.py {rd}/evaluation.json --json --output {rd}/decision.json"
    unassessed = [p for p, q in qs.items() if q is None]
    if stale or not stored["matches"]:
        step = "Re-run the scorer to refresh decision.json"
    elif d == "RESEARCH_INCOMPLETE" and unassessed:
        step = f"{len(unassessed)} of {len(qs)} pillars unassessed: {', '.join(unassessed)}"
    elif result["missing_pilot_gates"] and d != "NO_GO":
        step = f"Close pilot gate {result['missing_pilot_gates'][0]}, then re-score"
    elif bet and d == "VALIDATE_BEFORE_BUILD":
        step = f"Run {bet['id'] or 'the first experiment'} and record the result in the ledger, then re-score"
    else:
        step = result["next_step"]
    warnings = summarize_warnings(result["warnings"])
    gap = verdict_gap(result)
    return {"state": "ok", "research_dir": rd, "demo": bool(meta.get("demo")), "project": safe_text(result["project"], 120),
            "verdict": {"decision": d, **VERDICTS[d], "headline": result["headline"], "reason": result["reason"]},
            "verdicts": VERDICTS,
            "scores": {"weighted_quality": result["weighted_quality_0_to_100"], "evidence_average": result["evidence_average_0_to_5"],
                       "profile": result["business_model_profile"], "fatal_blockers": len(result["confirmed_fatal_blockers"])},
            "pillars": [{"key": r.pillar, "name": r.display, "weight": result["pillar_weights"][r.pillar], "quality": qs[r.pillar], "evidence": es[r.pillar]} for r in SPECIALISTS],
            "attention": {"confirmed_fatal": result["confirmed_fatal_blockers"], "plausible_fatal": result["unresolved_plausible_fatal_blockers"],
                          "missing_pilot_gates": result["missing_pilot_gates"], "source_review_open": result["source_review_pending"],
                          "warnings": [safe_text(w, 200) for w in warnings[:10]], "warning_count": len(result["warnings"])},
            "gap": gap, "gap_text": gap_text(gap), "next_bet": bet, "next_step": {"text": step, "command": rescore},
            "stored": stored, "stale": stale, "errors": []}, extra


def evidence_view(project, run_id, pillar):
    """Claims behind one pillar: ids, short text, vetted URL, dates and check results only, never page content."""
    from gf_profiles import BASE
    if pillar not in BASE:
        return {"state": "invalid", "errors": ["unknown pillar"]}
    project = Path(project).expanduser().resolve()
    meta, _, folder = _research(project, run_id)
    if isinstance(folder, str):
        return {"state": folder}
    if not (folder / "evaluation.json").is_file():
        return {"state": "no_evaluation"}
    try:
        data = load_json(folder / "evaluation.json")
    except GFError as e:
        return {"state": "invalid", "errors": [safe_text(e, 300)]}
    checks, report = {}, data.get("verification_report")
    with contextlib.suppress(GFError, TypeError):
        if isinstance(report, str) and report:
            rows = load_json(resolve_inside(folder, report)).get("claims")
            checks = {r["claim_id"]: r for r in rows if isinstance(r, dict) and isinstance(r.get("claim_id"), str)} if isinstance(rows, list) else {}
    item = (data.get("pillars") or {}).get(pillar) if isinstance(data.get("pillars"), dict) else None
    item = item if isinstance(item, dict) else {}
    linked = {c for c in item.get("claim_ids") or [] if isinstance(c, str)} if isinstance(item.get("claim_ids"), list) else set()
    claims = [c for c in data.get("claims") or [] if isinstance(c, dict) and (c.get("pillar") == pillar or c.get("id") in linked)] if isinstance(data.get("claims"), list) else []
    status = lambda v: safe_text(v, 30) if isinstance(v, str) else None
    out = [{"id": safe_text(c.get("id"), 40), "text": safe_text(c.get("statement"), 160), "url": safe_url(c.get("source_url")),
            "published": status(c.get("published_date")), "fetch_status": status(checks.get(c.get("id"), {}).get("fetch_status")),
            "excerpt_check": status(checks.get(c.get("id"), {}).get("excerpt_check"))} for c in claims[:100]]
    behaviors = item.get("behaviors") if isinstance(item.get("behaviors"), list) else []
    receipts = [safe_text(b["ledger_event_id"], 40) for b in behaviors if isinstance(b, dict) and isinstance(b.get("ledger_event_id"), str)]
    return {"state": "ok", "pillar": pillar, "claims": out, "receipts": receipts, "report": bool(checks)}


def hook_event(project, provider, raw):
    """Consume documented Claude/Codex hook JSON; never alter or block tool behavior."""
    run_id = active_run(project)
    if not run_id or not isinstance(raw, dict):
        return
    kind = raw.get("hook_event_name", "")
    name = clean_agent(raw.get("agent_type", ""))
    # Intentionally ignore unrelated subagents and all orchestrator tool hooks.
    if name == "orchestrator":
        return
    base = dict(provider=provider, agent=name, agent_id=raw.get("agent_id", ""), session_id=raw.get("session_id", ""))
    if kind == "SubagentStart":
        emit(project, run_id, "agent_started", summary="Native subagent started", **base)
    elif kind == "SubagentStop":
        emit(project, run_id, "agent_completed", summary="Native subagent returned", **base)
    elif kind == "PreToolUse":
        emit(project, run_id, "tool_started", tool=raw.get("tool_name", "tool"), **base)
    elif kind == "PostToolUseFailure":
        emit(project, run_id, "tool_failed", summary="Tool error (details omitted)", tool=raw.get("tool_name", "tool"), **base)


def ingest_codex(project, run_id, source):
    """Ingest codex exec --json events without exposing commands, prompts or reasoning."""
    count = 0
    session = ""
    for line in source:
        try:
            data = json.loads(line)
        except ValueError:
            continue
        event = data.get("type", "")
        if event == "thread.started":
            session = safe_text(data.get("thread_id", ""), 80)
            emit(project, run_id, "note", provider="codex-cli", summary="Codex CLI thread started", session_id=session)
            count += 1
        elif event in ("item.started", "item.completed", "item.failed"):
            item = data.get("item") or {}
            t = item.get("type") or item.get("item_type") or "item"
            if t in ("reasoning", "agent_message", "assistant_message"):
                continue
            name = clean_agent(item.get("agent_type", ""))
            if t in ("agent", "subagent", "agent_call") and item.get("agent_type") and name != "orchestrator":
                mapped = "agent_started" if event == "item.started" else "agent_completed" if event == "item.completed" else "agent_failed"
            else:
                mapped = "tool_started" if event == "item.started" else "tool_completed" if event == "item.completed" else "tool_failed"
            emit(project, run_id, mapped, provider="codex-cli", agent=name, session_id=session, tool=t, summary="Codex " + safe_text(t, 50) + " " + event.rsplit(".", 1)[-1])
            count += 1
        elif event == "turn.completed":
            usage = data.get("usage") or {}
            tokens = int(usage.get("input_tokens", 0) or 0) + int(usage.get("output_tokens", 0) or 0)
            emit(project, run_id, "token_usage", provider="codex-cli", session_id=session, tokens=tokens, summary="Turn usage reported by Codex")
            count += 1
        elif event in ("turn.failed", "error"):
            emit(project, run_id, "warning", provider="codex-cli", session_id=session, summary="Codex reported an error (details omitted)")
            count += 1
    return count


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "GreenfieldMissionControl/2"
    def _guard(self, path):
        """Refuse DNS-rebinding and cross-site reads; True means the request may proceed."""
        port = self.server.server_address[1]
        names = {"127.0.0.1", "localhost"} | {h.lower() for h in getattr(self.server, "allow_hosts", ())}
        hosts = {f"{n}:{port}" for n in names} | (names if port == 80 else set())
        if (self.headers.get("Host") or "").lower() not in hosts:
            self._refuse(421, "Misdirected Request")
            return False
        if path.startswith("/api/"):
            origin = self.headers.get("Origin")
            site = self.headers.get("Sec-Fetch-Site")
            if (origin is not None and origin.lower() not in {f"http://{h}" for h in hosts}) or (site is not None and site not in ("same-origin", "none")):
                self._refuse(403, "Forbidden")
                return False
        return True
    def _refuse(self, code, text):
        body = (text + "\n").encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)
    def end_headers(self):
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()
    def do_HEAD(self):
        self.do_GET()
    def do_GET(self):
        path = urlsplit(self.path)
        if not self._guard(path.path):
            return
        if path.path == "/":
            try:
                html = (Path(__file__).resolve().parent.parent / "assets" / "mission-control.html").read_bytes()
            except OSError:
                return self.send_error(404)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(html)
            return
        if path.path == "/api/runs":
            items = []
            for p in sorted((storage(self.server.project) / "runs").glob("*/meta.json"), reverse=True)[:100]:
                try:
                    obj = json.loads(p.read_text())
                    if VALID_RUN.fullmatch(obj.get("run_id", "")):
                        items.append(obj)
                except (ValueError, OSError):
                    pass
            return self._json({"runs": items, "active": active_run(self.server.project)})
        q = parse_qs(path.query)
        if path.path in ("/api/state", "/api/decision", "/api/evidence"):
            run_id = q.get("run", [active_run(self.server.project)])[0]
            if not run_id or not VALID_RUN.fullmatch(run_id):
                return self._json({"empty": True})
            try:
                if path.path == "/api/state":
                    since = q.get("since", [None])[0]
                    state = current_state(self.server.project, run_id, since=since[:64] if since else None)
                    return self._json(state, etag=state["rev"])
                view = decision_view(self.server.project, run_id) if path.path == "/api/decision" else \
                    evidence_view(self.server.project, run_id, q.get("pillar", [""])[0])
                return self._json(view, etag=view.get("etag"))
            except (ValueError, OSError):
                return self.send_error(404)
            except Exception as e:  # never a 500 or a traceback: bad inputs are reported as a state
                return self._json({"state": "invalid", "errors": [f"internal error ({type(e).__name__})"]})
        self.send_error(404)
    def _json(self, data, etag=None):
        body = None
        if etag is None:
            body = json.dumps(data, separators=(",", ":")).encode()
            etag = hashlib.sha256(body).hexdigest()[:16]
        tag = f'"{etag}"'
        if tag in [t.strip() for t in (self.headers.get("If-None-Match") or "").split(",")]:
            self.send_response(304)
            self.send_header("ETag", tag)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return
        body = body or json.dumps(data, separators=(",", ":")).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("ETag", tag)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)
    def log_message(self, *_args):
        return


def make_server(project, port, allow_hosts=()):
    """Loopback-only Mission Control server for project (not yet serving)."""
    tighten(project)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.project = project
    server.allow_hosts = list(allow_hosts)
    return server


def demo_run(project):
    """Create a labelled sample run; it never displaces a real running run."""
    rid = new_run(project, "Route planning for independent commercial laundries", "demo", True)
    for i, name in enumerate(AGENTS[:-1]):
        emit(project, rid, "agent_started", agent=name, provider="demo", summary="Sample agent started")
        emit(project, rid, "tool_started", agent=name, provider="demo", tool="WebSearch", summary="Sample search")
        if i % 2 == 0:
            emit(project, rid, "source_seen", agent=name, provider="demo", url="https://www.census.gov/", summary="Sample public source")
        if i < 5:
            emit(project, rid, "agent_completed", agent=name, provider="demo", summary="Sample task completed")
    emit(project, rid, "note", summary="DEMO DATA ONLY — no real agents executed", provider="demo")
    return rid


def add_cli(sub, name, *, project=True, run=False):
    p = sub.add_parser(name)
    if project: p.add_argument("--project", default=".")
    if run: p.add_argument("--run")
    return p


def main(argv=None):
    parser = argparse.ArgumentParser(description="Greenfield Mission Control · local metadata observability (not an agent runner)")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    sub = parser.add_subparsers(dest="command", required=True)
    p = add_cli(sub, "start")
    p.add_argument("--idea", required=True)
    p.add_argument("--provider", default="both", choices=("both", "claude", "codex"))
    p.add_argument("--new", action="store_true", help="replace the active run if it is still running")
    p.add_argument("--research-dir", help="research folder this run produces, inside the project")
    p = add_cli(sub, "link", run=True)
    p.add_argument("--research-dir", required=True, help="research folder this run produces, inside the project")
    p = add_cli(sub, "serve")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--allow-host", action="append", default=[], help="extra Host name to accept (port forwarding, tunnels)")
    p = add_cli(sub, "emit", run=True)
    p.add_argument("--event", required=True, choices=sorted(VALID_EVENTS))
    p.add_argument("--agent", default="orchestrator")
    p.add_argument("--message", default="")
    p.add_argument("--tool", default="")
    p.add_argument("--url", default="")
    p.add_argument("--provider", default="manual")
    p = add_cli(sub, "hook")
    p.add_argument("--provider", required=True, choices=("claude", "codex"))
    p = add_cli(sub, "ingest-codex", run=True)
    p = add_cli(sub, "demo")
    p = add_cli(sub, "status", run=True)
    args = parser.parse_args(argv)
    project = Path(args.project).expanduser().resolve()
    if args.command == "start":
        tighten(project)
        try:
            rid = new_run(project, args.idea, args.provider, replace=args.new, research_dir=args.research_dir)
        except GFError as e:
            return report(e, stream=sys.stderr)
        git_ignore_hint(project)
        print(rid)
    elif args.command == "link":
        rid = args.run or active_run(project)
        if not rid: parser.error("No active run; use 'start' first")
        try:
            print(link_research(project, rid, args.research_dir))
        except ValueError as e:  # GFError, or a malformed run id
            return report(e, stream=sys.stderr)
    elif args.command == "serve":
        if args.port < 1 or args.port > 65535:
            parser.error("Port must be 1–65535")
        server = make_server(project, args.port, args.allow_host)
        if args.allow_host:
            print(f"WARNING: also answering Host names {', '.join(args.allow_host)}; only use on networks you trust.", flush=True)
        print(f"Mission Control: http://127.0.0.1:{args.port}  (local machine only)", flush=True)
        try:
            server.serve_forever(poll_interval=0.3)
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
    elif args.command == "emit":
        rid = args.run or active_run(project)
        if not rid: parser.error("No active run; use 'start' first")
        print(emit(project, rid, args.event, provider=args.provider, agent=args.agent, summary=args.message, tool=args.tool, url=args.url)["id"])
    elif args.command == "hook":
        try:
            raw = json.load(sys.stdin)
            hook_event(project, args.provider, raw)
        except Exception:
            # Observability is never a business-critical tool gate.
            pass
    elif args.command == "ingest-codex":
        rid = args.run or active_run(project)
        if not rid: parser.error("No active run; use 'start' first")
        count = ingest_codex(project, rid, sys.stdin)
        print(f"Captured {count} sanitized Codex events", file=sys.stderr)
    elif args.command == "demo":
        rid = demo_run(project)
        if active_run(project) != rid:
            print("Demo run created but not activated; open it from the run picker", file=sys.stderr)
        print(rid)
    elif args.command == "status":
        rid = args.run or active_run(project)
        if not rid: parser.error("No active run")
        print(json.dumps(current_state(project, rid)["stats"], indent=2))
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    # hook runs inside the agent host on every tool call: no hint there
    raise SystemExit(old_entry(main, "gf_observe.py", None if cmd == "hook" else "greenfield " + {"serve": "dashboard", "emit": "event emit"}.get(cmd, cmd).strip()))
