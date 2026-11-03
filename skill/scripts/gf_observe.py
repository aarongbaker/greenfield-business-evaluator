#!/usr/bin/env python3
"""Local, read-only Greenfield Mission Control. Python 3.10+, standard library only.

Only metadata is recorded by default. No prompts, reasoning, raw tool I/O, environment,
network requests or agent responses are captured. Web server binds to loopback only.
"""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import http.server
import ipaddress
import json
import os
from pathlib import Path
import re
import sys
import threading
import time
from urllib.parse import urlsplit, urlunsplit, parse_qs
from uuid import uuid4

AGENTS = ["gf-problem", "gf-market", "gf-competition", "gf-economics", "gf-value", "gf-distribution", "gf-execution", "gf-timing", "gf-redteam"]
VALID_EVENTS = {"run_started", "run_completed", "run_failed", "agent_started", "agent_completed", "agent_failed", "tool_started", "tool_completed", "tool_failed", "source_seen", "artifact_created", "note", "token_usage", "warning", "task_planned", "task_started", "task_completed", "task_failed", "run_resumed"}
VALID_RUN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
EVENT_LIMIT = 10000
DEFAULT_PATH = ".greenfield-observe"


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")


def safe_text(value, limit=150):
    # Only short labels: never capture raw prompts, tool inputs or tool responses.
    return re.sub(r"[\x00-\x1f\x7f]", " ", str(value or ""))[:limit]


def clean_agent(name):
    name = safe_text(name, 90).lower().replace("_", "-")
    return name if name in AGENTS else "orchestrator"


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


def atomic_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp-" + uuid4().hex)
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


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


def new_run(project, idea, provider="both", demo=False):
    run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:6]
    meta_path, _ = file_paths(project, run_id)
    atomic_json(meta_path, {"run_id": run_id, "idea": safe_text(idea, 200), "provider": provider, "created_at": now(), "demo": bool(demo)})
    atomic_json(storage(project) / "active.json", {"run_id": run_id})
    emit(project, run_id, "run_started", provider=provider, summary="Research run initialized")
    return run_id


def emit(project, run_id, event, *, provider="manual", agent="orchestrator", agent_id="", session_id="", summary="", tool="", url="", tokens=0):
    if event not in VALID_EVENTS:
        raise ValueError("Unsupported event")
    meta_path, path = file_paths(project, run_id)
    if not meta_path.is_file():
        raise ValueError("Run not initialized")
    item = {"id": uuid4().hex, "timestamp": now(), "run_id": run_id, "event": event, "provider": safe_text(provider, 25), "agent": clean_agent(agent),
            "agent_id": safe_text(agent_id, 80), "session_id": safe_text(session_id, 80), "summary": safe_text(summary, 160),
            "tool": safe_text(tool, 64), "url": safe_url(url), "tokens": max(0, int(tokens or 0))}
    path.parent.mkdir(parents=True, exist_ok=True)
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
    items = []
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                if len(items) >= EVENT_LIMIT:
                    break
                try:
                    item = json.loads(line)
                    if isinstance(item, dict):
                        items.append(item)
                except ValueError:
                    continue
    except FileNotFoundError:
        pass
    return items


def current_state(project, run_id):
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
                     'completed': sum(info.get('status')=='completed' for info in task_doc['tasks'].values())}
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return {"meta": meta, "status": status, "agents": list(agents.values()), "events": events[-300:][::-1], "event_count": len(events), "checkpoints": task_info,
            "stats": {"started_agents": len(started), "finished_agents": sum(a["status"] == "completed" for a in agents.values()),
                      "active_agents": sum(a["status"] in ("running", "quiet") for a in agents.values()),
                      "tool_calls": sum(e["event"] == "tool_started" for e in events),
                      "source_events": sum(e["event"] == "source_seen" for e in events), "reported_tokens": total_tokens, "estimated_cost_usd": estimated_cost_usd,
                      "warnings": sum(e["event"] in ("warning", "tool_failed", "agent_failed") for e in events)}}


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
    elif kind == "PostToolUse":
        emit(project, run_id, "tool_completed", tool=raw.get("tool_name", "tool"), **base)
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
    def do_GET(self):
        path = urlsplit(self.path)
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
        if path.path == "/api/state":
            run_id = parse_qs(path.query).get("run", [active_run(self.server.project)])[0]
            if not run_id or not VALID_RUN.fullmatch(run_id):
                return self._json({"empty": True})
            try:
                return self._json(current_state(self.server.project, run_id))
            except (ValueError, OSError):
                return self.send_error(404)
        self.send_error(404)
    def _json(self, data):
        body = json.dumps(data, separators=(",", ":")).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *_args):
        return


def add_cli(sub, name, *, project=True, run=False):
    p = sub.add_parser(name)
    if project: p.add_argument("--project", default=".")
    if run: p.add_argument("--run")
    return p


def main(argv=None):
    parser = argparse.ArgumentParser(description="Greenfield Mission Control · local metadata observability (not an agent runner)")
    sub = parser.add_subparsers(dest="command", required=True)
    p = add_cli(sub, "start")
    p.add_argument("--idea", required=True)
    p.add_argument("--provider", default="both", choices=("both", "claude", "codex"))
    p = add_cli(sub, "serve")
    p.add_argument("--port", type=int, default=8765)
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
        print(new_run(project, args.idea, args.provider))
    elif args.command == "serve":
        if args.port < 1 or args.port > 65535:
            parser.error("Port must be 1–65535")
        server = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
        server.project = project
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
        rid = new_run(project, "DEMO · B2B compensation benchmarking AI", "demo", True)
        agents = AGENTS[:-1]
        for i, name in enumerate(agents):
            emit(project, rid, "agent_started", agent=name, provider="demo", summary="Sample agent started")
            emit(project, rid, "tool_started", agent=name, provider="demo", tool="WebSearch", summary="Sample search")
            if i % 2 == 0:
                emit(project, rid, "source_seen", agent=name, provider="demo", url="https://www.census.gov/", summary="Sample public source")
            if i < 5:
                emit(project, rid, "agent_completed", agent=name, provider="demo", summary="Sample task completed")
        emit(project, rid, "note", summary="DEMO DATA ONLY — no real agents executed", provider="demo")
        print(rid)
    elif args.command == "status":
        rid = args.run or active_run(project)
        if not rid: parser.error("No active run")
        print(json.dumps(current_state(project, rid)["stats"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
