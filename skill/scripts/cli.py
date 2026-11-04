#!/usr/bin/env python3
"""greenfield: one command for the Greenfield Business Evaluator. Python 3.11+, standard library only.

Exit codes: 0 success, 1 a negative result you asked about, 2 bad input or usage,
3 environment problem, 130 interrupted.
"""
from __future__ import annotations
import argparse
import contextlib
import difflib
import io
import json
import os
from pathlib import Path
import re
import sys

# The scripts import each other by plain name, so the package folder goes on sys.path once, here.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from gf_common import GFError, VERSION, report  # noqa: E402
import gf_observe  # noqa: E402
import gf_guard  # noqa: E402
from gf_ledger import ALLOWED as LEDGER_KINDS  # noqa: E402
import gf_profiles  # noqa: E402
from gf_profiles import PROFILES  # noqa: E402

PLATFORMS = ("claude", "codex", "both")
ERROR_CODES = {1: "negative_result", 2: "invalid_input", 3: "environment"}
# W26: commands that take file locks. They refuse on native Windows (no fcntl); every other command runs there.
LOCKING_COMMANDS = {"start", "demo", "task", "event emit", "ledger record", "ledger reattest", "hook", "ingest-codex"}


def _locking_name(args):
    """'task', 'event emit', 'start' ... when the parsed command takes file locks, else None."""
    sub = getattr(args, f"{args.command}_command", None)
    name = args.command if args.command == "task" or sub is None else f"{args.command} {sub}"
    if args.command == "hook" and getattr(args, "mode", None):
        return None  # the guard takes no locks
    return name if name in LOCKING_COMMANDS else None


class Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse only suggests close matches from Python 3.14 on.
        m = re.search(r"invalid choice: '([^']*)'", message)
        names = [n for a in self._actions if isinstance(a, argparse._SubParsersAction) for n in a.choices]
        close = suggest(m.group(1), names) if m else None
        super().error(message + (f"\nDid you mean '{close}'?" if close else ""))


def _global_options():
    g = argparse.ArgumentParser(add_help=False)
    o = g.add_argument_group("global options")
    # SUPPRESS keeps a subcommand's parser from resetting a value given before the subcommand.
    o.add_argument("--project", metavar="DIR", default=argparse.SUPPRESS, help="project folder (default: current folder)")
    o.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="print JSON (default when stdout is not a terminal)")
    o.add_argument("-q", "--quiet", action="store_true", default=argparse.SUPPRESS, help="no progress or hint messages on stderr")
    o.add_argument("--no-color", action="store_true", default=argparse.SUPPRESS, help="no colour (also off with NO_COLOR or TERM=dumb)")
    o.add_argument("--version", action="version", version=f"greenfield {VERSION}", help="print the version and exit")
    return g


GLOBAL = _global_options()


def _cmd(sub, name, help, examples, func=None, text=None, hidden=False, auto_json=True):
    """Add one command with the global options, a description and an examples epilog."""
    p = sub.add_parser(name, **({} if hidden else {"help": help}), description=help, parents=[GLOBAL],
                       epilog="examples:\n" + "\n".join("  " + e for e in examples),
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    p.set_defaults(func=func, text=text, auto_json=auto_json)
    return p


def _group(sub, name, help, examples):
    p = _cmd(sub, name, help, examples)
    return p.add_subparsers(dest=name + "_command", metavar="<command>", required=True, parser_class=Parser)


def _run_arg(p):
    p.add_argument("--run", metavar="ID", help="run id (default: the active run)")


def _role_arg(p):
    p.add_argument("--role", required=True, choices=gf_observe.AGENTS, help="research role")


# ---- handlers: return JSON-ready data and never print to stdout ----

def _rid(args):
    if args.run is not None:
        gf_observe.file_paths(args.project, args.run)  # validates; raises "Invalid run ID"
        return args.run
    rid = gf_observe.active_run(args.project)
    if not rid:
        raise GFError("No active run", path=args.project, hint="greenfield start --idea '...', or pass --run ID")
    return rid


def h_install(args):
    import gf_install
    base, targets = gf_install.plan(args.platform, args.scope, args.project, args.no_agents)
    acts = gf_install.plan_install(targets, args.force, args.overwrite_modified)
    if args.dry_run:
        return {"dry_run": True, "plan": acts}
    import gf_platform
    if not gf_platform.HAS_FCNTL:  # W26: the skill installs anywhere; research runs need WSL here
        print("note: research runs need WSL on native Windows (file locking); the skill still installs.", file=sys.stderr)
    done = gf_install.install(targets, args.force, args.scope, args.overwrite_modified)
    if args.scope == "project":
        gf_install.offer_gitignore(base, add=args.gitignore, never=args.no_gitignore, out=sys.stderr)
    return {"installed": [str(p) for p in done], "plan": acts, "next": ["Claude: /greenfield-business-evaluator <idea>", "Codex:  $greenfield-business-evaluator <idea>"]}


def h_uninstall(args):
    import gf_install
    base, acts = gf_install.plan_uninstall(args.platform, args.scope, args.project, args.keep_hooks, args.purge_telemetry)
    todo = any(a["op"] == "remove" for a in acts)
    if todo and not args.dry_run and not args.yes:
        if not sys.stdin.isatty():
            raise GFError("refusing to delete without confirmation", hint="greenfield uninstall --yes")
        for a in acts:
            print(f"{a['op']:7} {a['path']}  ({a['reason']})", file=sys.stderr)
        if input("Remove these? [y/N] ").strip().lower() not in ("y", "yes"):
            raise GFError("cancelled, nothing removed", code=1)
    if todo and not args.dry_run:
        if gf_install.apply_uninstall(base, acts, args.platform, args.scope):
            args.exit_code = 1  # some removals failed; each was reported on stderr
    return {"dry_run": args.dry_run, "plan": acts, "note": ".gitignore lines and research/greenfield/ are left in place"}


def h_hooks(args):
    import gf_hooks
    result = gf_hooks.configure(args.hooks_command, args.project, args.platform, guard=True,
                                observe=not getattr(args, "guard_only", False))
    if args.hooks_command == "install":
        print(gf_hooks.INSTALL_NOTE, file=sys.stderr)
    return {"settings": [{"path": str(path), "changed": changed} for changed, path in result]}


def h_start(args):
    gf_observe.tighten(args.project)
    out = gf_observe.scaffold(args.project, args)
    gf_observe.git_ignore_hint(args.project)
    return out


def t_start(data, args):
    return f"Started run {data['run_id']}\nResearch folder: {data['research_dir']}\nNext:\n" + "".join(f"  {n}\n" for n in data["next"])


def _ctx(args):
    import gf_context
    return gf_context.run_context(args.project, getattr(args, "run", None))


def h_link(args):
    return {"run_id": (rid := _rid(args)), "research_dir": gf_observe.link_research(args.project, rid, args.research_dir)}


def h_status(args):
    import gf_runs
    rid = _rid(args)
    out = {"run_id": rid, "stats": gf_observe.current_state(args.project, rid)["stats"], "tasks": None}
    with contextlib.suppress(ValueError):  # no task plan yet
        out["tasks"] = gf_runs.status(args.project, rid, args.usd_per_million_tokens)
    view = gf_observe.decision_view(args.project, rid)
    out["decision"] = {k: v for k, v in view.items() if k != "etag"}
    out["research_dir"], out["scored"] = view.get("research_dir"), view.get("state") == "ok"
    return out


def h_task(args):
    import gf_runs
    rid, c, p = _rid(args), args.task_command, args.project
    if c == "plan": return gf_runs.plan(p, rid)
    if c == "claim": return gf_runs.claim(p, rid, args.role)
    if c == "complete": return gf_runs.complete(p, rid, args.role, args.artifact)
    if c == "fail": return gf_runs.fail(p, rid, args.role, args.reason)
    if c == "resume": return gf_runs.resume(p, rid, args.freshness_hours)
    if c == "coverage": return gf_runs.coverage(p, rid, args.evaluation, args.verification_report)
    return gf_runs.set_rate(p, rid, args.usd_per_million_tokens)


def h_dashboard(args):
    if not 0 <= args.port <= 65535:
        raise GFError(f"port {args.port} is not 0-65535", hint="greenfield dashboard --port 8765")
    try:
        server = gf_observe.make_server(args.project, args.port, args.allow_host)
    except OSError as e:
        raise GFError(f"cannot listen on port {args.port}: {e.strerror or e}", hint=f"greenfield dashboard --port {args.port + 1}", code=3) from None
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        if args.allow_host:
            print(f"WARNING: also answering Host names {', '.join(args.allow_host)}; only use on networks you trust.", file=sys.stderr)
        print(json.dumps({"url": url}) if args.json else f"Mission Control: {url}  (local machine only)", flush=True)
        if args.open:
            import webbrowser
            webbrowser.open(url)
        server.serve_forever(poll_interval=0.3)
    finally:
        server.server_close()


def h_demo(args):
    old = None if args.new else gf_observe.running_run(args.project)
    if old:
        raise gf_observe.ActiveRunError(old[0], old[1].get("idea", ""), old[1].get("created_at"))
    rid = gf_observe.demo_run(args.project)
    return {"run_id": rid, "activated": gf_observe.active_run(args.project) == rid}


def h_emit(args):
    return {"id": gf_observe.emit(args.project, _rid(args), args.event, provider=args.provider, agent=args.agent,
                                  summary=args.message, tool=args.tool, url=args.url)["id"]}


def h_hook(args):
    if args.mode == "guard":  # fails open: a broken guard must not stop the user's work
        with contextlib.suppress(Exception):
            if (deny := gf_guard.guard_response(json.load(sys.stdin), args.project)):
                print(json.dumps(deny))
        return
    with contextlib.suppress(Exception):  # observability never gates a tool call
        gf_observe.hook_event(args.project, args.provider, json.load(sys.stdin))


def h_ingest(args):
    return {"captured": gf_observe.ingest_codex(args.project, _rid(args), sys.stdin)}


def h_sources(args):
    import gf_evidence
    if args.evaluation is None or args.output is None:
        ctx = _ctx(args)
        args.evaluation, args.output = args.evaluation or ctx["evaluation"], args.output or ctx["verification"]
    return gf_evidence.check(args.evaluation, args.output, args.allow_network, args.stale_days)


def h_ledger(args):
    import gf_ledger
    args.ledger = args.ledger or _ctx(args)["ledger"]
    try:
        return gf_ledger.handle(argparse.Namespace(**{**vars(args), "command": args.ledger_command, "project": getattr(args, "project_name", "")}))
    except ValueError as e:
        if args.ledger_command in ("verify", "summary") and not isinstance(e, GFError):
            raise GFError(str(e), path=args.ledger, code=1) from None  # the chain itself is broken
        raise


def h_score(args):
    import score_project
    if args.evaluation is None:
        ctx = _ctx(args)
        args.evaluation, args.output = ctx["evaluation"], args.output or ctx["decision"]
    try:
        result, errors, _ = score_project.score_file(args.evaluation)
    except Exception as exc:  # never a verdict after an unexpected error
        raise GFError(f"internal validator error ({type(exc).__name__}: {str(exc)[:120]}). No decision was written.",
                      hint="report this with your evaluation.json") from None
    if errors:
        raise GFError(errors[0] if len(errors) == 1 else f"{len(errors)} problems:\n  " + "\n  ".join(errors),
                      path=args.evaluation, hint=f"fix the field(s) above and re-run `greenfield score {args.evaluation}`")
    if args.output:
        try:
            args.output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            score_project.atomic_write(args.output, json.dumps(result, indent=2, ensure_ascii=False) + "\n", mode=0o600)
        except OSError as exc:
            raise GFError(f"cannot write decision: {exc.strerror or exc}", path=args.output, hint="choose a writable --output path") from None
    if args.json:
        for warning in result["warnings"]:
            print("WARNING: " + warning, file=sys.stderr)
    return result


def t_score(result, args):
    import score_project
    try:
        "●█░·•—…".encode(sys.stdout.encoding or "ascii")
        glyphs = "unicode"
    except (UnicodeEncodeError, LookupError):
        glyphs = "ascii"
    text = score_project.render_text(result, color=_color(args), glyphs=glyphs, all_warnings=args.all_warnings)
    return text + (f"Saved decision.json to {args.output}\n" if args.output else "")


def h_portfolio(args):
    import gf_portfolio
    return gf_portfolio.run(args.manifest, args.output, args.markdown)


def h_completion(args):
    import completion
    return completion.script(build_parser(), args.shell)


def _color(args):
    return sys.stdout.isatty() and not args.no_color and not os.environ.get("NO_COLOR") and os.environ.get("TERM") != "dumb"


def _field(key):
    return lambda data, args: str(data[key]) + "\n"


# ---- parser ----

def build_parser():
    root = Parser(prog="greenfield", parents=[GLOBAL], formatter_class=argparse.RawDescriptionHelpFormatter,
                  description="Evaluate a business idea before building it: research runs, evidence, scoring and ranking.",
                  epilog="examples:\n  greenfield install --platform both\n  greenfield score research/greenfield/my-idea/evaluation.json\n\n"
                         "Run `greenfield <command> --help` for a command's options and examples.")
    sub = root.add_subparsers(dest="command", metavar="<command>", required=True, parser_class=Parser)

    p = _cmd(sub, "install", "install the skill and research roles into Claude Code and/or Codex", [
        "greenfield install --platform both", "greenfield install --scope user --platform claude --force"], h_install)
    p.add_argument("--platform", choices=PLATFORMS, default="both", help="which agent host (default: both)")
    p.add_argument("--scope", choices=("project", "user"), default="project", help="install into --project or your home folder")
    p.add_argument("--no-agents", action="store_true", help="install the skill only, not the nine research roles")
    p.add_argument("--force", action="store_true", help="replace files this tool installed before")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--gitignore", action="store_true", help="add private research folders to .gitignore without asking")
    g.add_argument("--no-gitignore", action="store_true", help="never offer to edit .gitignore")
    p.add_argument("--overwrite-modified", action="store_true", help="with --force, also replace role files you edited")
    p.add_argument("--dry-run", action="store_true", help="show what would change and write nothing")
    p = _cmd(sub, "uninstall", "remove what install placed (edited files, research and other hooks are kept)", [
        "greenfield uninstall --dry-run", "greenfield uninstall --scope user --yes"], h_uninstall)
    p.add_argument("--platform", choices=PLATFORMS, default="both", help="which agent host (default: both)")
    p.add_argument("--scope", choices=("project", "user", "all"), default="project", help="uninstall from --project, your home folder, or both")
    p.add_argument("--dry-run", action="store_true", help="show what would be removed and remove nothing")
    p.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    p.add_argument("--keep-hooks", action="store_true", help="leave Mission Control hooks in place")
    p.add_argument("--purge-telemetry", action="store_true", help="also delete .greenfield-observe/")

    hooks = _group(sub, "hooks", "add or remove the opt-in Mission Control hooks", [
        "greenfield hooks install --platform claude", "greenfield hooks remove"])
    for name, help in (("install", "add the Mission Control hooks and the self-attestation guard"), ("remove", "remove this tool's hooks, keep all others")):
        p = _cmd(hooks, name, help, [f"greenfield hooks {name}", f"greenfield hooks {name} --platform codex --project ~/code/app"], h_hooks)
        p.add_argument("--platform", choices=PLATFORMS, default="both", help="which agent host (default: both)")
        if name == "install":
            p.add_argument("--guard-only", action="store_true", help="install only the self-attestation guard, not the Mission Control hooks")

    p = _cmd(sub, "start", "start a research run for an idea (refuses while another run is active)", [
        "greenfield start --idea 'AI bookkeeping for dentists'", "greenfield start --idea 'Laundry routing' --provider claude --new"],
        h_start, t_start)
    p.add_argument("--idea", required=True, help="the business idea, in one line")
    p.add_argument("--provider", default="both", choices=PLATFORMS, help="agent host doing the research")
    p.add_argument("--new", action="store_true", help="replace the active run if it is still running")
    p.add_argument("--research-dir", metavar="DIR", help="research folder this run produces, inside the project")
    p.add_argument("--slug", help="folder name under research/greenfield/ (default: made from the idea)")
    p.add_argument("--model", choices=sorted(PROFILES), default="general", help="business-model profile (default: general)")
    p.add_argument("--customer", help="initial customer, if known")
    p.add_argument("--geography", help="where the customer is, if known")
    p.add_argument("--depth", choices=("quick", "standard", "deep"), default="standard", help="research depth (default: standard)")
    p.add_argument("--as-of", metavar="YYYY-MM-DD", help="evaluation date (default: today, local time)")
    p.add_argument("--no-plan", action="store_true", help="do not create the nine-task plan")

    p = _cmd(sub, "link", "point a run at its research folder", [
        "greenfield link --research-dir research/greenfield/my-idea", "greenfield link --run 20261103T120000Z-ab12cd --research-dir research/x"],
        h_link, _field("research_dir"))
    _run_arg(p)
    p.add_argument("--research-dir", metavar="DIR", required=True, help="research folder, inside the project")

    p = _cmd(sub, "status", "show a run: activity, tasks and the decision if scored", [
        "greenfield status", "greenfield --json status --run 20261103T120000Z-ab12cd"], h_status)
    _run_arg(p)
    p.add_argument("--usd-per-million-tokens", type=float, metavar="USD", help="blended token rate for the cost estimate")

    task = _group(sub, "task", "plan, claim and finish the research tasks of a run", [
        "greenfield task plan", "greenfield task claim --role gf-market"])
    for name, help, ex in (
            ("plan", "create the nine-task plan for the run", "greenfield task plan"),
            ("claim", "mark a role's task as running", "greenfield task claim --role gf-market"),
            ("complete", "mark a role's task done with its artifact", "greenfield task complete --role gf-market --artifact research/greenfield/x/specialists/market.md"),
            ("fail", "mark a role's task failed", "greenfield task fail --role gf-market --reason 'no web access'"),
            ("resume", "list tasks to rerun after an interruption", "greenfield task resume --freshness-hours 24"),
            ("coverage", "record pillar coverage from an evaluation", "greenfield task coverage --evaluation research/greenfield/x/evaluation.json"),
            ("set-rate", "store a blended token rate for cost estimates", "greenfield task set-rate --usd-per-million-tokens 5")):
        p = _cmd(task, name, help, [ex, ex.replace("greenfield task", "greenfield --json task", 1)], h_task)
        _run_arg(p)
        if name in ("claim", "complete", "fail"):
            _role_arg(p)
        if name == "complete":
            p.add_argument("--artifact", required=True, help="file the role produced, inside the project")
        if name == "fail":
            p.add_argument("--reason", required=True, help="why the task failed")
        if name == "resume":
            p.add_argument("--freshness-hours", type=float, default=72, help="completed work older than this is rerun (default 72)")
        if name == "coverage":
            p.add_argument("--evaluation", required=True, help="the run's evaluation.json")
            p.add_argument("--verification-report", help="source-verification.json from `sources check`")
        if name == "set-rate":
            p.add_argument("--usd-per-million-tokens", type=float, required=True, metavar="USD", help="blended rate in US dollars")

    p = _cmd(sub, "dashboard", "serve Mission Control on this machine (Ctrl-C stops it)", [
        "greenfield dashboard --open", "greenfield dashboard --port 8766"], h_dashboard)
    p.add_argument("--port", type=int, default=8765, help="port on 127.0.0.1 (default 8765; 0 picks a free one)")
    p.add_argument("--allow-host", action="append", default=[], metavar="NAME", help="extra Host name to accept (port forwarding, tunnels)")
    p.add_argument("--open", action="store_true", help="open the dashboard in your browser")

    p = _cmd(sub, "demo", "create a labelled sample run to try the dashboard", [
        "greenfield demo", "greenfield demo --new && greenfield dashboard --open"], h_demo, _field("run_id"))
    p.add_argument("--new", action="store_true", help="create it even while a real run is active (it will not replace it)")

    event = _group(sub, "event", "record run events", [
        "greenfield event emit --event note --message 'Scoring next'", "greenfield event emit --event source_seen --url https://www.census.gov/"])
    p = _cmd(event, "emit", "record one event on a run", [
        "greenfield event emit --event note --message 'Scoring next'", "greenfield event emit --event agent_started --agent gf-market"], h_emit, _field("id"))
    _run_arg(p)
    p.add_argument("--event", required=True, choices=sorted(gf_observe.VALID_EVENTS), help="event type")
    p.add_argument("--agent", default="orchestrator", help="who did it (default orchestrator)")
    p.add_argument("--message", default="", help="short summary (no secrets, no prompts)")
    p.add_argument("--tool", default="", help="tool name, for tool events")
    p.add_argument("--url", default="", help="public source URL, for source_seen")
    p.add_argument("--provider", default="manual", help="label for where the event came from")

    p = _cmd(sub, "hook", "agent host hook (reads hook JSON on stdin)", ["greenfield hook --provider claude < event.json", "greenfield hook --provider codex < event.json"], h_hook, hidden=True)
    p.add_argument("mode", nargs="?", choices=("guard",), help="guard: refuse agent attempts to record human attestations")
    p.add_argument("--provider", required=True, choices=("claude", "codex"), help="agent host")
    p = _cmd(sub, "ingest-codex", "read a Codex JSON event stream on stdin", ["greenfield ingest-codex --run ID < events.jsonl", "codex exec --json ... | greenfield ingest-codex"], h_ingest, hidden=True)
    _run_arg(p)

    sources = _group(sub, "sources", "check the sources cited in an evaluation", [
        "greenfield sources check evaluation.json --output source-verification.json", "greenfield sources check evaluation.json --output out.json --allow-network"])
    p = _cmd(sources, "check", "check citations offline (or fetch public pages with --allow-network)", [
        "greenfield sources check evaluation.json --output source-verification.json", "greenfield sources check evaluation.json --output out.json --allow-network"], h_sources)
    p.add_argument("evaluation", type=Path, nargs="?", help="evaluation.json (default: the active run's)")
    _run_arg(p)
    p.add_argument("--output", type=Path, help="where to write the full report (default: source-verification.json beside the run's evaluation)")
    p.add_argument("--allow-network", action="store_true", help="fetch PUBLIC pages; off by default")
    p.add_argument("--stale-days", type=int, default=730, help="sources older than this are flagged (default 730)")

    ledger = _group(sub, "ledger", "record and verify the hash-chained experiment ledger", [
        "greenfield ledger verify --ledger experiment-ledger.jsonl", "greenfield ledger summary --ledger experiment-ledger.jsonl"])
    p = _cmd(ledger, "record", "append one event (receipts need a person at a terminal)", [
        "greenfield ledger record --ledger experiment-ledger.jsonl --kind hypothesis --project-name 'Laundry routing' --hypothesis 'Owners pay for routing'",
        "greenfield ledger record --ledger experiment-ledger.jsonl --kind note --project-name X --hypothesis H --notes 'call booked'"], h_ledger)
    p.add_argument("--ledger", help="the .jsonl ledger file (default: the active run's)")
    _run_arg(p)
    p.add_argument("--kind", required=True, choices=sorted(LEDGER_KINDS), help="event kind")
    p.add_argument("--project-name", required=True, help="the idea or project this event belongs to")
    p.add_argument("--hypothesis", required=True, help="the hypothesis tested")
    p.add_argument("--outcome", default="", help="what happened")
    p.add_argument("--artifact", help="evidence file inside the ledger's folder")
    p.add_argument("--attester", default="", help="the person confirming a receipt")
    p.add_argument("--observed-at", default="", metavar="DATE", help="when it was observed (default today)")
    p.add_argument("--notes", default="", help="free-text notes")
    p.add_argument("--pillar", action="append", default=[], help="pillar this evidence supports (repeatable)")
    p.add_argument("--claim-id", default="", help="claim id, for source reviews")
    p.add_argument("--experiment-id", default="", help="experiment id")
    for name, help in (("verify", "check the hash chain (exit 1 if broken)"), ("summary", "count events and check behavior receipts"),
                       ("reattest", "interactively re-confirm unsigned attested events")):
        p = _cmd(ledger, name, help, [f"greenfield ledger {name} --ledger experiment-ledger.jsonl",
                                      f"greenfield --json ledger {name} --ledger research/greenfield/x/experiment-ledger.jsonl"], h_ledger)
        p.add_argument("--ledger", help="the .jsonl ledger file (default: the active run's)")
        _run_arg(p)

    p = _cmd(sub, "score", "validate and score an evaluation (text on a terminal, JSON when piped)", [
        "greenfield score research/greenfield/my-idea/evaluation.json", "greenfield --json score evaluation.json --output decision.json"], h_score, t_score)
    p.add_argument("evaluation", type=Path, nargs="?", help="evaluation.json (default: the active run's)")
    _run_arg(p)
    p.add_argument("--output", type=Path, help="also write the decision JSON here (default with no path: decision.json beside the run's evaluation)")
    p.add_argument("--all-warnings", action="store_true", help="text mode: list every warning instead of the top 5 groups")

    p = _cmd(sub, "portfolio", "rank several scored ideas against each other", [
        "greenfield portfolio portfolio.json --output ranking.json", "greenfield portfolio portfolio.json --output ranking.json --markdown ranking.md"], h_portfolio)
    p.add_argument("manifest", type=Path, help="portfolio manifest JSON")
    p.add_argument("--output", type=Path, required=True, help="where to write the ranking JSON")
    p.add_argument("--markdown", type=Path, help="also write a Markdown table here")

    import gf_doctor, gf_report
    gf_doctor.register(sub, _cmd)
    gf_report.register(sub, _cmd)
    gf_profiles.register(sub, _cmd)

    p = _cmd(sub, "completion", "print a shell completion script", [
        "greenfield completion bash > ~/.local/share/bash-completion/completions/greenfield",
        "greenfield completion fish > ~/.config/fish/completions/greenfield.fish"], h_completion, lambda s, a: s, auto_json=False)
    p.add_argument("shell", choices=("bash", "zsh", "fish"), help="your shell")
    return root


# ---- output ----

def render(result, args):
    if result is None:
        return
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.text:
        sys.stdout.write(args.text(result, args))
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False))


def fail(err, args):
    """Print err (what, path, next) to stderr, as JSON with --json; return its exit code."""
    code = getattr(err, "code", 2)
    if getattr(args, "json", False):
        path = getattr(err, "path", None)
        print(json.dumps({"error": {"code": getattr(err, "json_code", None) or ERROR_CODES.get(code, "error"), "message": str(err),
                                    "path": None if path is None else str(path), "next": getattr(err, "hint", None)}}), file=sys.stderr)
        return code
    return report(err)


def suggest(name, names):
    """Closest command name, or None."""
    close = difflib.get_close_matches(name, names, n=1)
    return close[0] if close else None


def main(argv=None):
    args = None
    try:
        args = build_parser().parse_args(argv)
        for key, default in (("json", False), ("quiet", False), ("no_color", False), ("project", ".")):
            if not hasattr(args, key):
                setattr(args, key, default)
        args.json = args.json or (args.auto_json and not sys.stdout.isatty())
        project = Path(args.project).expanduser()
        if not project.is_dir():
            raise GFError("--project is not an existing folder", path=project, hint="pass the project folder, or run from inside it")
        args.project = project.resolve()
        # W26: refuse locking commands on platforms without fcntl here, before any handler runs.
        if locking := _locking_name(args):
            import gf_platform
            gf_platform.require_locking(f"greenfield {locking}")
        with contextlib.redirect_stderr(io.StringIO()) if args.quiet else contextlib.nullcontext():
            result = args.func(args)
        render(result, args)
        sys.stdout.flush()
        return getattr(args, "exit_code", 0)  # doctor sets 1 or 3 after printing its report
    except KeyboardInterrupt:
        print(file=sys.stderr)
        return 130
    except BrokenPipeError:
        # The reader (e.g. `| head`) went away; silence the flush at exit.
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 0
    except (GFError, OSError, ValueError, KeyError, TypeError) as err:
        if not isinstance(err, GFError):
            err = GFError(str(err) or type(err).__name__, path=getattr(err, "filename", None))
        return fail(err, args)


if __name__ == "__main__":
    raise SystemExit(main())
