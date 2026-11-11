#!/usr/bin/env python3
"""Local, read-only Greenfield Mission Control. Python 3.11+, standard library only.

Only metadata is recorded by default. No prompts, reasoning, raw tool I/O, environment,
network requests or agent responses are captured. Web server binds to loopback only.
"""
from __future__ import annotations
import argparse
import contextlib
import csv
import datetime as dt
import hashlib
import http.server
import ipaddress
import json
import os
import random
from pathlib import Path
from collections import Counter
import re
import shlex
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
        print("hint: .greenfield-observe/ is not in .gitignore; run `greenfield install --gitignore` to keep it out of commits", file=sys.stderr)


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


def real_run_exists(project, skip=None):
    for meta in (storage(project) / "runs").glob("*/meta.json"):
        if meta.parent.name != skip:
            with contextlib.suppress(OSError, ValueError, AttributeError):
                if not json.loads(meta.read_text(encoding="utf-8")).get("demo"):
                    return True
    return False


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


def new_run(project, idea, provider="both", demo=False, replace=False, research_dir=None, created_at=None):
    run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:6]
    meta_path, _ = file_paths(project, run_id)
    extra = {"research_dir": DEMO_RESEARCH if demo else research_rel(project, research_dir)} if demo or research_dir else {}
    with active_lock(project):  # check-then-write must be atomic across processes
        old = running_run(project)
        if old and not demo and not replace:
            raise ActiveRunError(old[0], old[1].get("idea", ""), old[1].get("created_at"))
        atomic_json(meta_path, {"run_id": run_id, "idea": safe_text(idea, 200), "provider": provider, "created_at": created_at or now(), "demo": bool(demo), **extra})
        if old and not demo:
            emit(project, old[0], "warning", summary=f"Superseded by run {run_id}")
        if not (demo and real_run_exists(project, run_id)):  # sample data never displaces a real run, running or finished
            atomic_json(storage(project) / "active.json", {"run_id": run_id})
    emit(project, run_id, "run_started", provider=provider, summary="Research run initialized", at=created_at)
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
    import gf_materials, gf_profiles
    if slug in gf_materials.RESERVED:  # before anything is created
        raise GFError(f"{slug} is reserved for the bundled demo", hint="greenfield start --idea '...' --slug my-idea")
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
    data["execution"].update(mode="not_started", depth=args.depth)
    data["evidence_ledger"], data["verification_report"] = "experiment-ledger.jsonl", "source-verification.json"
    data["evaluation_id"] = "eval-" + uuid4().hex[:8]
    data["pilot_gates"] = gf_profiles.describe(data["project"].get("business_model") or "general")["pilot_gates_skeleton"]
    gf_materials.setup_folders(folder)
    gf_materials.snapshot(folder, data)
    atomic_write_json(ev, data, mode=0o600)
    rid = new_run(project, args.idea, args.provider, replace=args.new, research_dir=folder)
    if not args.no_plan:
        import gf_runs
        gf_runs.plan(project, rid)
    rel = folder.relative_to(project).as_posix()
    ask = f"Evaluate this idea: {args.idea} (depth: {args.depth}; research folder: {rel})"
    return {"run_id": rid, "slug": slug, "research_dir": rel, "evaluation": f"{rel}/evaluation.json",
            "next": [f"Claude Code: /greenfield-business-evaluator {ask}", f"Codex: $greenfield-business-evaluator {ask}", "greenfield dashboard"]}


def emit(project, run_id, event, *, provider="manual", agent="orchestrator", agent_id="", session_id="", summary="", tool="", url="", tokens=0, at=None):
    if event not in VALID_EVENTS:
        raise ValueError("Unsupported event")
    meta_path, path = file_paths(project, run_id)
    if not meta_path.is_file():
        raise ValueError("Run not initialized")
    # at: only the demo backdates its sample events
    item = {"id": uuid4().hex, "timestamp": at or now(), "run_id": run_id, "event": event, "provider": safe_text(provider, 25), "agent": clean_agent(agent),
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


def reconcile(agent, task, run="running"):
    """One shown status from the hook status and the checkpoint status (W20 table): label, tone, note, warn."""
    s = agent["status"]
    d = lambda label, tone, note="", warn=False: {"label": label, "tone": tone, "note": note, "warn": warn}
    if s == "failed" or task == "failed":
        return d("Failed", "bad", f"Agent failed: {agent['activity']}" if s == "failed" else "Checkpoint failed", True)
    if s == "completed":
        return d("Done", "good", *{"completed": ("Checkpointed",), "queued": ("Not checkpointed", True), "running": ("Not checkpointed", True)}.get(task, ()))
    if s in ("running", "quiet") and run != "running":  # a finished run cannot leave an agent Running
        return d("Done" if run == "completed" else "Stopped", "good" if run == "completed" else "neutral", f"Run {run}; no agent_completed event")
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
            a.update(status="running", started_at=e.get("timestamp"), ended_at=None, activity="Starting")
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
            a["activity"] = "Found a source"
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
        a["display"] = reconcile(a, tasks.get(a["name"]), status)
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


def _command(result, rescore, demo):
    """The command for the first step: the bundled demo gets a read-only one, so it never shows a local path."""
    if demo:
        return "greenfield plan"
    route = result.get("route")
    return "greenfield plan --add-experiments" if route and any(s["new_experiment"] for s in route["steps"]) else rescore


def _steps(result, step, demo=False):
    """The founder's to-do list and {pillar: the step that tests it}: the planner's route while one is open, else the scorer's single next step.
    Written to procedure style: one action per step, goal first, no internal terms (pillar, receipt, gate ids)."""
    from score_project import names, plain
    route = result.get("route")
    if result["decision"] != "VALIDATE_BEFORE_BUILD" or not route or step != result["next_step"]:
        return [step], {}
    import gf_plan
    cat = {e["id"]: e for e in gf_plan.catalog()}
    new = any(s["new_experiment"] for s in route["steps"]) and not demo  # never write into the bundled demo
    out = ["Add the tests below to your project: run `greenfield plan --add-experiments`."] if new else []
    if result["source_review_pending"]:  # same order as docs/founder-journey.md: sources before experiments
        out.append("Check that the web pages your research cites say what it claims: run `greenfield sources check --allow-network`, "
                   "then `greenfield evidence status`, and confirm each claim with the command it shows.")
    seen, tests = set(), {}
    for s in route["steps"]:
        e = cat.get(s["entry"], {})
        goal = " and ".join(x for x in (s["pillars"] and f"shows {plain(s['pillars'])}", s["gate"] and f"closes gate {s['gate']}") if x)
        how = ("Repeat the test above with 300 different people, this time leading with what your product does for them."
               if s["title"] in seen and s["entry"] == "signups" else e.get("how", ""))
        seen.add(s["title"])
        out.append(f"**{s['title']}** ({goal}). {how}" + (f" It passes if {e['pass_hint']}." if e.get("pass_hint") else ""))
        for p in s["pillars"]:  # the checklist points each question at the first step that tests it
            tests.setdefault(p, {"n": len(out), "title": s["title"]})
    out.append("After each test, record whether it passed or failed. Judge it against the pass mark in its step, and do not change the mark afterwards. "
               "`greenfield plan` shows the exact commands, including how to remove emails first.")
    qs = result["quality_scores"]
    high = [p for p, q in route["quality_targets"].items() if qs.get(p) is not None and q < qs[p]]
    if high:
        them = "them" if len(high) > 1 else "it"
        out.append(f"Your research scored {names(high)} above 3 out of 5, which is more than the tests above can prove and blocks a Proceed verdict. "
                   f"After the tests, ask your assistant to re-assess {them}; this plan counts on 3.")
    covered = {s["gate"] for s in route["steps"]}
    out += [f"Close pilot gate {g} with a passing test." for g in result["missing_pilot_gates"] if g not in covered]
    out.append("When the results are in, run `greenfield score` to update this verdict.")
    return out, tests


# W59: every test is worked through the same rooms; a room is done when the founder or the assistant has written its file
ROOMS = (("who", "Who", "Who exactly are you testing with?", "audience.md"), ("say", "What to say", "What will you show or send them?", "messages.md"),
         ("find", "Find people", "Where do they come from?", "prospects.csv"), ("send", "Send and track", "Is it out, and what came back?", "log.csv"),
         ("record", "Record result", "Did it pass the mark you set?", None))
LOG_COLUMNS = ("id", "sent_on", "variant", "replied", "result")
# shown beside the message and sending rooms; every number is from the Google and Yahoo sender pages cited in docs/outreach.md
COLD_RULES = ("You read and approve every message before it goes.",
              "Send from your own mailbox, a few a day. Start low and raise it only while nobody complains.",
              "Set up SPF or DKIM on the domain you send from: Gmail and Yahoo require one of them from every sender.",
              "Give every message a plain way to say \"don't contact me again\", and honour it within 2 days.",
              "Stop if people complain. Gmail and Yahoo expect spam reports to stay under 0.3% of messages; at 300 messages one report is already over that.",
              "Check the law where you and your recipients are (CAN-SPAM in the US, GDPR in the EU and UK). This is not legal advice.")


def _rows(path, need):
    """(data rows, warning) of a small CSV the founder keeps. Missing, unreadable or wrongly headed files count as no rows, never a crash."""
    try:
        if path.stat().st_size > 2_000_000:
            return [], f"{path.name} is over 2 MB and was not read"
        with path.open(newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = [r for r in reader if any((v or "").strip() for v in r.values() if isinstance(v, str))]
            if not set(need) <= set(reader.fieldnames or ()):
                return [], f"{path.name} needs the columns {', '.join(need)}"
            return rows, None
    except FileNotFoundError:
        return [], None
    except (OSError, UnicodeDecodeError, csv.Error):
        return [], f"{path.name} could not be read"


def _rooms(folder, rel, step, files):
    """One test's rooms with done flags, counts and the pass meter. Sends counts only: no row of either file leaves the machine's disk."""
    e, exp = step["entry"], step["experiment_id"]
    title, target, where = e["title"], e.get("target"), f"{rel}/outreach/{exp}"
    record = {"key": "record", "name": "Record result", "ask": ROOMS[4][2], "done": False, "count": "",
              "help": f"When the test is over, judge it against the mark you set: it passes if {e['pass_hint']}. Do not change the mark afterwards. Bring: {e['bring']}.",
              "commands": [c for c in (step["redact"] if (step["redact"] or "").startswith("greenfield") else None, step["command"]) if c]}
    if not step["pillars"] or not exp or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", exp):  # a gate-only step has nobody to contact
        return [{"key": "prepare", "name": "Prepare", "ask": "What do you need to bring?", "done": False, "count": "", "help": f"{e['how']} Bring: {e['bring']}."}, record], None, []
    state, warnings = {}, []
    for name in ("audience.md", "messages.md", "prospects.csv", "log.csv"):
        with contextlib.suppress(GFError):
            files.append(resolve_inside(folder, f"outreach/{exp}/{name}"))
            state[name] = files[-1]
    has = lambda name: name in state and state[name].is_file() and state[name].stat().st_size > 0
    people, w1 = _rows(state["prospects.csv"], ("id",)) if "prospects.csv" in state else ([], None)
    log, w2 = _rows(state["log.csv"], LOG_COLUMNS) if "log.csv" in state else ([], None)
    warnings += [w for w in (w1, w2) if w]
    n = target["people"] if target else None
    prompts = {  # pasted to the assistant, which writes the room's file
        "who": f"Using the findings in this run, write a one-page audience card for the test '{title}' and save it as {where}/audience.md. "
               "Name one narrow group of people, where they can be reached, and what would rule someone out.",
        "say": f"Read {where}/audience.md, then draft three short variants of what I will send for the test '{title}' and save them as {where}/messages.md. "
               "Keep each under 90 words with one ask and a line that lets people opt out. Claim nothing about the product that the research does not support.",
        "find": f"Research {n or 'the'} people who fit {where}/audience.md from public pages and save them as {where}/prospects.csv with the columns "
                "id, name, role, company, source_url, contact. Record the page each row came from. Do not contact anyone.",
    }
    helps = {
        "who": "Ask your assistant for an audience card. Paste this:",
        "say": "Ask your assistant for drafts. You read and approve every message before it goes. Paste this:",
        "find": "Ask your assistant to research a list, or bring your own in the same columns. Your assistant reads this file to do the work, so the names in it reach your AI provider. Paste this:",
        "send": f"You send; this tool never does. Keep {where}/log.csv with the columns {', '.join(LOG_COLUMNS)}: one row per person, by id only, "
                "and write yes under result when they do what the test counts.",
    }
    count = {"find": f"{len(people)} of {n}" if n and people else str(len(people) or ""), "send": f"{len(log)} sent" if log else ""}
    done = {"who": has("audience.md"), "say": has("messages.md"), "find": bool(people), "send": bool(log)}
    rooms = [{"key": k, "name": name, "ask": ask, "done": done[k], "count": count.get(k, ""), "help": helps[k], "prompt": prompts.get(k)} for k, name, ask, _ in ROOMS[:4]] + [record]
    hits = sum((r.get("result") or "").strip().lower() == "yes" for r in log)
    meter = {"hits": hits, "contacted": len(log), **target} if target else None
    return rooms, meter, warnings


def _path(data, folder, rel, result, facts, demo, files):
    """The route as a map (W59): tests already recorded, each test still to run with its rooms, then the re-score. None when there is no route."""
    import gf_plan
    if result["decision"] != "VALIDATE_BEFORE_BUILD" or not result.get("route"):
        return None, []
    try:
        routes = gf_plan.plan(data, facts, top=3, warnings=result["warnings"], folder=folder, slug=Path(rel).name)["routes"]
    except (KeyError, TypeError, ValueError, AttributeError):  # same rule as gf_plan.choose: the planner never breaks the page
        routes = []
    if not routes:
        return None, []
    weeks = lambda r: max(1, round(r["days"] / 7))
    method = {x.get("id"): x.get("method") for x in data.get("experiments") or [] if isinstance(x, dict)}
    nodes = [{"kind": "sources", "title": "Check your sources", "state": "todo",
              "help": "Check that the web pages your research cites say what it claims, then confirm each claim with the command the second one shows.",
              "commands": ["greenfield sources check --allow-network", "greenfield evidence status"]}] if result["source_review_pending"] else []
    for e in facts["counted"]:
        if e.get("result") in ("pass", "fail") and e.get("experiment_id"):
            nodes.append({"kind": "result", "title": safe_text(method.get(e["experiment_id"]) or e["experiment_id"], 60), "state": "done" if e["result"] == "pass" else "failed",
                          "help": safe_text(e.get("outcome") or "", 200) if e["result"] == "pass" else
                          "This test failed. Change the plan and run the test again, or stop and reframe the idea as a new run. A failed result stays on the record."})
    warnings = []
    for i, s in enumerate(routes[0]["steps"]):
        locked = s["new_experiment"] and not demo  # the bundled demo is read-only, so its tests are never added
        rooms, meter, w = ([], None, []) if locked else _rooms(folder, rel, s, files)
        warnings += w
        nodes.append({"kind": "test", "title": s["entry"]["title"], "id": s["experiment_id"], "state": "todo", "locked": locked, "how": s["entry"]["how"],
                      "pass": s["entry"]["pass_hint"], "rooms": rooms, "meter": meter})
    first = next((n for n in nodes if n["kind"] == "test"), None)
    if first:
        first["state"] = "next"
    nodes.append({"kind": "score", "title": "Re-score", "state": "todo", "help": f"When the results are in, update the verdict. This route expects a score of {routes[0]['total']:g}.", "commands": ["greenfield score"]})
    others = [{"text": f"Start with {r['steps'][0]['entry']['title'][0].lower()}{r['steps'][0]['entry']['title'][1:]}: {len(r['steps'])} test{'' if len(r['steps']) == 1 else 's'}, about {weeks(r)} week{'' if weeks(r) == 1 else 's'}",
               "command": None if demo else f"greenfield plan --add-experiments --route {n}"} for n, r in enumerate(routes[1:], 2) if r["steps"]]
    add = None if demo or not any(s["new_experiment"] for s in routes[0]["steps"]) else "greenfield plan --add-experiments"
    return {"nodes": nodes, "others": others, "add": add, "warnings": warnings, "rules": COLD_RULES}, files


def _why(result):
    """One line on what Proceed still needs, in counts a founder can check."""
    if result["decision"] != "VALIDATE_BEFORE_BUILD":
        return ""
    from score_project import CORE
    have = len(CORE) - len(result["missing_core_behavior_evidence"])
    total = result["weighted_quality_0_to_100"]
    parts = [f"a passed customer test on each of the {len(CORE)} core questions ({have} done so far)"]
    if total is not None and total < 75:
        parts.append(f"a score of 75 ({total:g} now)")
    return "To reach a Proceed verdict you need " + " and ".join(parts) + "."


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
    cd = str(ASSETS / rd) if rd and meta.get("demo") else rd  # the bundled demo folder lives beside the skill, not in the user's project
    if state == "no_research_dir":
        found = sorted(project.glob("research/greenfield/*/evaluation.json"))
        guess = found[0].parent.relative_to(project).as_posix() if len(found) == 1 else "research/greenfield/<slug>"  # suggest, never guess
        step = {"text": "Link this run to its research folder", "command": f"greenfield link --research-dir {guess} --run {run_id}"}
    elif state == "invalid_path":
        step = {"text": "The linked folder is outside this project; link one inside it", "command": f"greenfield link --research-dir research/greenfield/<slug> --run {run_id}"}
    elif state == "no_evaluation":
        q = shlex.quote(str(cd))
        step = {"text": "Specialists still running, or write evaluation.json from the template", "command": f"mkdir -p {q} && cp {shlex.quote(str(ASSETS / 'evaluation-template.json'))} {q}/evaluation.json"}
    else:
        step = {"text": "Fix the listed errors, then re-run the scorer with --json", "command": f"greenfield score {shlex.quote(str(cd))}/evaluation.json --json"}
    return {"state": state, "research_dir": rd, "demo": bool(meta.get("demo")), "next_step": step, "errors": [], **fields}


def _decide(project, run_id, meta, base, folder, ev, dec):
    from score_project import ASK, CORE, VERDICTS, gap_text, recompute_decision, summarize_warnings, verdict_gap
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
    exp = result.get("next_experiment")
    bet = {"id": safe_text(exp["id"] or exp["entry"], 20), "text": safe_text(exp["hypothesis"], 200), "pillar": exp["pillar"] or exp["gate"]} if exp else None
    rq = shlex.quote(str(ASSETS / rd) if meta.get("demo") else rd)
    rescore = f"greenfield score {rq}/evaluation.json --json --output {rq}/decision.json"
    unassessed = [p for p, q in qs.items() if q is None]
    if stale or not stored["matches"]:
        step = "Re-run the scorer to refresh decision.json"
    elif d == "RESEARCH_INCOMPLETE" and unassessed:
        step = f"{len(unassessed)} of {len(qs)} pillars unassessed: {', '.join(unassessed)}"
    else:
        step = result["next_step"]
    warnings = summarize_warnings(result["warnings"])
    gap = verdict_gap(result)
    matrix = _matrix(data, folder, result)
    steps, tests = _steps(result, step, meta.get("demo"))
    facts = matrix.pop("facts")
    path, watched = (_path(data, folder, "research/greenfield/demo-research" if meta.get("demo") else rd, result, facts, meta.get("demo"), [])
                     if step == result["next_step"] else (None, []))
    extra += watched  # room state is read from these files, so they key the cache
    return {"state": "ok", "research_dir": rd, "demo": bool(meta.get("demo")), "project": safe_text(result["project"], 120),
            "verdict": {"decision": d, **VERDICTS[d], "headline": result["headline"], "reason": result["reason"]},
            "verdicts": VERDICTS,
            "scores": {"weighted_quality": result["weighted_quality_0_to_100"], "evidence_average": result["evidence_average_0_to_5"],
                       "profile": result["business_model_profile"], "fatal_blockers": len(result["confirmed_fatal_blockers"])},
            "pillars": [{"key": r.pillar, "name": r.display, "ask": ASK[r.pillar], "weight": result["pillar_weights"][r.pillar], "quality": qs[r.pillar],
                         "points": None if qs[r.pillar] is None else round(result["pillar_weights"][r.pillar] * min(qs[r.pillar], facts["rubric"][r.pillar]) / 5, 1),
                         "claimed": None if qs[r.pillar] is None else round(result["pillar_weights"][r.pillar] * qs[r.pillar] / 5, 1), "evidence": es[r.pillar], "core": r.pillar in CORE,
                         **matrix["pillars"][r.pillar]} for r in SPECIALISTS],
            "gates": matrix["gates"], "plan": matrix["plan"], "progress": matrix["progress"], "carried": matrix["carried"],
            "attention": {"confirmed_fatal": result["confirmed_fatal_blockers"], "plausible_fatal": result["unresolved_plausible_fatal_blockers"],
                          "missing_pilot_gates": result["missing_pilot_gates"], "source_review_open": result["source_review_pending"],
                          "warnings": [safe_text(w, 200) for w in warnings[:10]], "warning_count": len(result["warnings"])},
            "gap": gap, "gap_text": gap_text(gap), "next_bet": bet, "next_step": {"text": step, "command": _command(result, rescore, meta.get("demo"))},
            "steps": steps, "tests": tests, "path": path, "why": _why(result),
            "stored": stored, "stale": stale, "errors": []}, extra


def _matrix(data, folder, result):
    """W51: each pillar's receipts and rubric flag, one line per profile gate, and the planner's route line."""
    import gf_ledger, gf_materials
    from gf_profiles import BASE, GATE_HELP, PROFILES
    with gf_ledger.demo_scope(folder):
        facts = gf_materials.analyze(data, folder / gf_ledger.LEDGER_NAME, folder)
    t = lambda v, n=80: safe_text(v, n) if isinstance(v, str) else ""
    goal = {x.get("id"): x.get("success_threshold") for x in data.get("experiments") or [] if isinstance(x, dict)}  # older receipts did not sign it
    row = lambda e: {"id": t(e["id"], 20), "material": t(e.get("material") or e["kind"], 20), "kind": t(e["kind"], 20), "result": t(e.get("result"), 10),
                     "threshold": t(e.get("success_threshold") or goal.get(e.get("experiment_id"))), "outcome": t(e.get("outcome"), 120), "date": t(e.get("observed_at"), 10),
                     "reused_from": [t(x, 60) for x in e.get("reused_from") or []], "intact": e["id"] in facts["intact"]}
    over = {p: w for w in result["warnings"] for p in BASE if w.startswith(f"pillars.{p}: quality") and "above what evidence" in w}
    pillars = {p: {"receipts": [row(e) for e in facts["counted"] if p in e["pillar_ids"]], "over": t(over.get(p), 200) or None} for p in BASE}
    gates = []
    for g in PROFILES.get(result["business_model_profile"], PROFILES["general"])["pilot_gates"]:
        tried = [e for e in facts["counted"] if g in (e.get("gate_ids") or [])]
        last = tried[-1] if tried else None
        if g not in result["missing_pilot_gates"]:
            ids = (data.get("pilot_gates") or {}).get(g, {}).get("evidence_ids") or []
            gates.append({"gate": g, "closed": True, "text": f"{g} · {t(', '.join(map(str, ids)), 60)} pass"})
        elif last and last.get("result") == "fail":
            gates.append({"gate": g, "closed": False, "text": f"{g} · {t(last['id'], 20)} fail (cannot close)"})
        else:
            gates.append({"gate": g, "closed": False, "text": f"{g} · needs {' or '.join(sorted(GATE_HELP[g]['accepts']))}"})
    route = result.get("route")
    kinds = Counter(s["as"] for s in route["steps"]) if route else {}
    each = ", ".join(k + (f" ×{n}" if n > 1 else "") for k, n in kinds.items())
    plan = {"text": f"To {route['total']:g} with {route['receipts']} receipts: {each}", "command": "greenfield plan"} if route else None
    done = Counter(e.get("result") for e in facts["counted"])
    # the route is re-planned after every receipt, so the whole run is the tests already passed plus the ones still on it
    progress = {"next": done["pass"] + 1, "total": done["pass"] + len(route["steps"]), "passed": done["pass"], "failed": done["fail"], "days_left": route["days"]} if route and route["steps"] else None
    return {"facts": facts, "pillars": pillars, "gates": gates, "plan": plan, "progress": progress, "carried": "receipts carried across an idea change" in result["warnings"]}


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
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            if self.command != "HEAD":
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


DEMO_URLS = ["https://www.census.gov/", "https://www.bls.gov/", "https://www.sba.gov/", "https://coinlaundry.org/",
             "https://www.reddit.com/r/laundromat/", "https://www.g2.com/", "https://www.capterra.com/", "https://www.statista.com/"]
DEMO_SPAN = [38, 44, 48, 45, 46, 70, 66, 64]  # seconds per specialist: five finish before DEMO_CUT, three after
DEMO_CUT = 60  # the instant demo is a snapshot at this second; --replay plays the whole script


def demo_script():
    """Sample run as (second, event, agent, tool, url, summary), seeded so every demo is the same."""
    r, out = random.Random(7), [(0.3, "note", "orchestrator", "", "", "DEMO DATA ONLY — no real agents executed")]
    for i, name in enumerate(AGENTS[:-1]):
        start = 1 + i * 2.5
        out.append((start, "agent_started", name, "", "", "Sample agent started"))
        t, k = start + 1 + r.random() * 2, 0
        while t < start + DEMO_SPAN[i] - 2:
            tool = ("WebSearch", "WebFetch", "WebSearch", "Read")[k % 4]
            out.append((t, "tool_started", name, tool, "", "Sample " + tool))
            if name == "gf-competition" and k == 3:
                out.append((t + 0.5, "tool_failed", name, tool, "", "Sample fetch timed out"))
            elif tool == "WebFetch":
                out.append((t + 0.7, "source_seen", name, "", r.choice(DEMO_URLS), "Sample public source"))
            t, k = t + 3 + r.random() * 3, k + 1
        out.append((start + DEMO_SPAN[i], "agent_completed", name, "", "", "Sample task completed"))
    red = 2 + max(1 + i * 2.5 + d for i, d in enumerate(DEMO_SPAN))
    out.append((red, "agent_started", AGENTS[-1], "", "", "Sample agent started"))
    for k in range(5):
        tool = ("WebSearch", "WebFetch")[k % 2]
        out.append((red + 1.5 + k * 2.6, "tool_started", AGENTS[-1], tool, "", "Sample " + tool))
        if tool == "WebFetch":
            out.append((red + 2.2 + k * 2.6, "source_seen", AGENTS[-1], "", DEMO_URLS[k], "Sample public source"))
    out += [(red + 16, "agent_completed", AGENTS[-1], "", "", "Sample task completed"), (red + 17, "run_completed", "orchestrator", "", "", "Sample run finished")]
    return sorted(out)


def demo_run(project, replay=False, sleep=time.sleep):
    """Create a labelled sample run; it never displaces a real running run.

    Instantly, it is a snapshot DEMO_CUT seconds into the script with backdated timestamps. With replay, the whole
    script is written in real time (about 100 seconds) so the dashboard can be watched; Ctrl-C leaves a valid run."""
    idea = "Route planning for independent commercial laundries"
    script = demo_script()
    if not replay:
        base = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=DEMO_CUT)
        at = lambda t: (base + dt.timedelta(seconds=t)).isoformat(timespec="milliseconds")
        rid = new_run(project, idea, "demo", True, created_at=at(0))
        for t, event, agent, tool, url, summary in (x for x in script if x[0] <= DEMO_CUT):
            emit(project, rid, event, agent=agent, provider="demo", tool=tool, url=url, summary=summary, at=at(t))
        return rid
    rid = new_run(project, idea, "demo", True)
    t0 = time.monotonic()
    for t, event, agent, tool, url, summary in script:
        sleep(max(0.0, t - (time.monotonic() - t0)))
        emit(project, rid, event, agent=agent, provider="demo", tool=tool, url=url, summary=summary)
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
    p.add_argument("--replay", action="store_true")
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
        try:
            rid = demo_run(project, args.replay)
        except KeyboardInterrupt:
            return 130
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
