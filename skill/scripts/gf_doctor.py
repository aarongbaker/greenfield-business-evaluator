"""`greenfield doctor` (W23): grouped health checks, one runnable fix per problem. Standard library only.

Every check returns {id, group, status: pass|warn|fail|info, detail, fix}. Read-only, and no sockets
unless --network. Only `--fix` writes, and only folder/file permissions and .gitignore lines.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import shlex
import shutil
import stat
import subprocess
import sys

import gf_hooks
import gf_install
import gf_ledger
import gf_observe
import gf_platform
from gf_common import GFError, VERSION, gitignore_missing
from gf_roles import ROLES

GROUPS = ("Environment", "Install", "Hooks", "Privacy", "Attestation", "Run", "Dashboard", "Network", "Agent")
MARK = {"pass": "[ ok ]", "warn": "[warn]", "fail": "[FAIL]", "info": "[info]"}


def _r(id, group, status, detail, fix=""):
    return {"id": id, "group": group, "status": status, "detail": detail, "fix": fix}


def _installs(project):
    """[(scope, platform, skill dir, agents dir)] for every skill copy that exists on disk."""
    out = []
    for scope, base in (("project", project), ("user", Path.home())):
        for plat, skills, agents in (("claude", ".claude", ".claude"), ("codex", ".agents", ".codex")):
            d = base / skills / "skills" / gf_install.SKILL_NAME
            if d.is_dir():
                out.append((scope, plat, d, base / agents / "agents"))
    return out


# ---- Environment ----

def c_python(ctx):
    ok = sys.version_info >= (3, 11)
    return [_r("environment.python", "Environment", "pass" if ok else "fail", f"Python {sys.version.split()[0]}", "" if ok else "Install Python 3.11 or newer")]


def c_platform(ctx):
    if gf_platform.HAS_FCNTL and not sys.platform.startswith("win"):
        return [_r("environment.platform", "Environment", "pass", sys.platform)]
    return [_r("environment.platform", "Environment", "fail", f"{sys.platform}: no POSIX file locking, so start, task, event and ledger record refuse to run",
               f"Use WSL ({gf_platform.WSL_URL}); score, ledger verify, portfolio and doctor work here")]


def c_which(ctx):
    exe = shutil.which("greenfield")
    if not exe:
        return [_r("environment.which", "Environment", "info", "no `greenfield` on PATH (running from a clone or by script path)")]
    try:
        seen = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        seen = ""
    if seen == f"greenfield {VERSION}":
        return [_r("environment.which", "Environment", "pass", f"{exe} is {VERSION}")]
    return [_r("environment.which", "Environment", "warn", f"{exe} reports {seen or 'no version'}, this copy is {VERSION}",
               "pipx upgrade greenfield-evaluator   (or: greenfield install --force)")]


# ---- Install ----

def c_install(ctx):
    found = ctx["installs"]
    if not found:
        return [_r("install.present", "Install", "fail", "the skill is not installed at project or user scope", "greenfield install --platform both")]
    out = [_r("install.present", "Install", "pass", ", ".join(f"{s}/{p}" for s, p, _, _ in found))]
    bad, unknown = [], []
    for scope, plat, skill, _ in found:
        man = gf_install.read_manifest(skill)
        if man is None:
            unknown.append(str(skill))
            continue
        have = {k: v for k, v in gf_install.tree_hashes(skill).items() if k != gf_install.MANIFEST}
        bad += [f"{skill}: {k}" for k in sorted(set(have) | set(man["skill_files"])) if have.get(k) != man["skill_files"].get(k)]
    if bad:
        out.append(_r("install.intact", "Install", "fail", f"{len(bad)} file(s) differ from the install manifest, first: {bad[0]}", "greenfield install --force"))
    elif unknown:
        out.append(_r("install.intact", "Install", "warn", f"no readable install manifest in {unknown[0]} (installed by an older version)", "greenfield install --force"))
    else:
        out.append(_r("install.intact", "Install", "pass", "files match the install manifest"))
    shadow = []
    for plat in ("claude", "codex"):
        v = {s: (d / ".greenfield-version").read_text().strip() if (d / ".greenfield-version").is_file() else "?"
             for s, p, d, _ in found if p == plat}
        if len(v) == 2 and v["project"] != v["user"]:
            shadow.append(f"{plat}: project {v['project']} vs user {v['user']}")
    if shadow:
        out.append(_r("install.shadowing", "Install", "warn", "same skill at both scopes with different versions (" + "; ".join(shadow) + "); the project copy wins in the host",
                      "greenfield uninstall --scope user   (or --scope project) to remove the one you do not want"))
    else:
        out.append(_r("install.shadowing", "Install", "pass", "no conflicting copies"))
    missing, stale = [], []
    for scope, plat, _, agents in found:
        ext = "md" if plat == "claude" else "toml"
        for role in ROLES:
            f = agents / f"gf-{role.key}.{ext}"
            src = gf_install.AGENT_SRC and gf_install.AGENT_SRC / plat / "agents" / f.name
            if not f.is_file():
                missing.append(str(f))
            elif src and src.is_file() and gf_install.sha(f) != gf_install.sha(src):
                stale.append(str(f))
    if missing or stale:
        out.append(_r("install.agents", "Install", "fail" if missing else "warn",
                      f"{len(missing)} of the role files missing" + (f" (first: {missing[0]})" if missing else "") + (f"; {len(stale)} differ from this package" if stale else ""),
                      "greenfield install --force"))
    else:
        out.append(_r("install.agents", "Install", "pass", f"{len(ROLES)} role files per host match this package"))
    return out


# ---- Hooks ----

def _hook_files(project):
    for plat in ("claude", "codex"):
        p = gf_hooks.path_for(project, plat)
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data.get("hooks") if isinstance(data, dict) else None, dict):
            yield plat, p, data["hooks"]


def _ours_commands(hooks):
    """[(event, command, is_guard)] for the Greenfield hooks in a hooks object."""
    out = []
    for event, groups in hooks.items():
        for g in groups if isinstance(groups, list) else []:
            for h in (g.get("hooks") if isinstance(g, dict) and isinstance(g.get("hooks"), list) else []):
                obs, grd = gf_hooks._ours(h)
                if obs or grd:
                    out.append((event, str(h["command"]), grd))
    return out


def c_hooks(ctx):
    mine = [(plat, p, c) for plat, p, hooks in _hook_files(ctx["project"]) for c in _ours_commands(hooks)]
    if not mine:
        return [_r("hooks.configured", "Hooks", "info", "no Greenfield hooks (optional)", "greenfield hooks install"),
                _r("hooks.guard", "Hooks", "warn", "self-attestation guard not installed", "greenfield hooks install --guard-only"),
                _r("hooks.codex_trust", "Hooks", "info", "Codex trust cannot be read from disk", "Open /hooks in Codex and approve the Greenfield hooks")]
    out = [_r("hooks.configured", "Hooks", "pass", f"{len(mine)} Greenfield hook entries")]
    broken = []
    for plat, p, (event, cmd, grd) in mine:
        try:
            script = shlex.split(cmd)[1]
        except (ValueError, IndexError):
            script = ""
        if not Path(script).is_file():
            broken.append(f"{p.name}: {script or cmd}")
    out.append(_r("hooks.script_path", "Hooks", "fail" if broken else "pass",
                  f"hook script missing: {broken[0]}" if broken else "every hook script exists", "greenfield hooks install" if broken else ""))
    guard = any(g for _, _, (_, _, g) in mine)
    out.append(_r("hooks.guard", "Hooks", "pass" if guard else "warn", "PreToolUse self-attestation guard present" if guard else "PreToolUse self-attestation guard missing",
                  "" if guard else "greenfield hooks install"))
    stale = [p.name for plat, p, hooks in _hook_files(ctx["project"]) if any(e == "PostToolUse" for e, _, _ in _ours_commands(hooks))]
    out.append(_r("hooks.stale_posttooluse", "Hooks", "warn" if stale else "pass",
                  f"leftover PostToolUse hook in {stale[0]} (spawns python3 on every tool call, nothing reads it)" if stale else "no leftover PostToolUse hook",
                  "greenfield hooks install   (removes the leftover entry)" if stale else ""))
    out.append(_r("hooks.codex_trust", "Hooks", "info", "Codex trust cannot be read from disk", "Open /hooks in Codex and approve the Greenfield hooks"))
    return out


# ---- Privacy ----

def _loose(project):
    root = gf_observe.storage(project)
    if not root.is_dir():
        return []
    out = []
    for p in [root, *root.rglob("*")]:
        try:
            st = p.lstat()
        except OSError:
            continue
        if not stat.S_ISLNK(st.st_mode) and stat.S_IMODE(st.st_mode) & 0o077:
            out.append(p)
    return out


def c_privacy(ctx):
    project = ctx["project"]
    loose = _loose(project)
    out = [_r("privacy.permissions", "Privacy", "fail", f"{len(loose)} item(s) in .greenfield-observe/ are readable by others, first: {loose[0]}", "greenfield doctor --fix")
           if loose else _r("privacy.permissions", "Privacy", "pass", ".greenfield-observe/ is private (0700/0600)")]
    missing = gitignore_missing(project)
    tracked = []
    if (project / ".git").exists() and shutil.which("git"):
        try:
            tracked = subprocess.run(["git", "-C", str(project), "ls-files", "--", ".greenfield-observe", "research/greenfield"],
                                     capture_output=True, text=True, timeout=5).stdout.split()
        except (OSError, subprocess.SubprocessError):
            pass
    if tracked:
        out.append(_r("privacy.ignored", "Privacy", "fail", f"{len(tracked)} private file(s) are tracked by git, first: {tracked[0]}",
                      "git rm -r --cached .greenfield-observe research/greenfield   (not run for you)"))
    elif missing:
        out.append(_r("privacy.ignored", "Privacy", "fail", "not in .gitignore: " + ", ".join(missing), "greenfield doctor --fix"))
    else:
        out.append(_r("privacy.ignored", "Privacy", "pass", "private folders are git-ignored"))
    return out


# ---- Attestation, Run ----

def _run_ctx(project):
    """(context | None, result | None): the active run's files, or a failed/info result saying why not."""
    import gf_context
    active = gf_observe.storage(project) / "active.json"
    if not active.exists():
        return None, _r("run.active", "Run", "info", "no active run", "greenfield start --idea '...'")
    try:
        ctx = gf_context.run_context(project)
        if not ctx["research_dir"].is_dir():
            raise GFError(f"research folder {ctx['research_dir']} is missing")
        return ctx, _r("run.active", "Run", "pass", f"run {ctx['run_id']}")
    except (GFError, OSError, ValueError, KeyError, TypeError) as e:
        return None, _r("run.active", "Run", "fail", f"active run is unusable: {e}", "greenfield start --new")


def c_attestation(ctx):
    legacy, run = 0, ctx["run"]
    if run and run["ledger"].is_file():
        try:
            with run["ledger"].open(encoding="utf-8") as f:  # streamed, one line at a time
                for line in f:
                    art = json.loads(line).get("artifact")
                    legacy += isinstance(art, dict) and isinstance(art.get("path"), str) and (Path(art["path"]).is_absolute() or art["path"][1:3] in (":\\", ":/"))
        except (OSError, ValueError, AttributeError):
            pass  # a broken ledger is reported by run.ledger
    out = [_r("attestation.legacy_receipts", "Attestation", "warn", f"{legacy} receipt(s) store an absolute artifact path and break if the folder moves",
              "Re-record those receipts with `greenfield ledger record`; they still resolve, with a warning, for one release")
           if legacy else _r("attestation.legacy_receipts", "Attestation", "pass", "no receipts with absolute paths")]
    kp = gf_ledger.key_path()
    if not gf_ledger.load_key():
        out.append(_r("attestation.hmac_key", "Attestation", "warn", f"no signing key at {kp}", "It is created on your first `greenfield ledger record`"))
    elif os.name == "posix" and stat.S_IMODE(kp.stat().st_mode) & 0o077:
        out.append(_r("attestation.hmac_key", "Attestation", "fail", f"{kp} is readable by others", f"chmod 600 {shlex.quote(str(kp))}"))
    else:
        out.append(_r("attestation.hmac_key", "Attestation", "pass", f"signing key {kp} is private"))
    return out


def c_run(ctx):
    run, res = ctx["run"], ctx["run_result"]
    out = [res]
    if not run:
        return out
    ev = run["evaluation"]
    if not ev.is_file():
        out.append(_r("run.readiness", "Run", "info", "no evaluation.json yet", "Write it from the evaluation template, then `greenfield score`"))
    else:
        import score_project
        _, errors, _ = score_project.score_file(ev)
        out.append(_r("run.readiness", "Run", "warn", f"{len(errors)} thing(s) missing before you can score; first: {errors[0]}", f"Fix it, then run `greenfield score {ev}`")
                   if errors else _r("run.readiness", "Run", "pass", "evaluation.json validates"))
    if run["ledger"].is_file():
        try:
            gf_ledger.read_ledger(run["ledger"])
            out.append(_r("run.ledger", "Run", "pass", "ledger hash chain intact"))
        except (OSError, ValueError) as e:
            out.append(_r("run.ledger", "Run", "fail", f"{e}", f"Restore {run['ledger']} from a backup or git; the first broken event is named above"))
    else:
        out.append(_r("run.ledger", "Run", "info", "no experiment ledger yet"))
    import gf_materials
    pii = gf_materials.inbox_warnings(ev.parent)
    if pii:
        out.append(_r("run.inbox_pii", "Run", "warn", f"{len(pii)} file(s) in materials/inbox/ hold personal data; first: {pii[0]}", "Run the greenfield evidence redact command it names"))
    return out


# ---- Dashboard, Network, Agent (sockets only with --network) ----

def c_network(ctx):
    if not ctx["network"]:
        return [_r("dashboard.port", "Dashboard", "info", "port check skipped: doctor opens no sockets without --network", "greenfield doctor --network"),
                _r("network.reachability", "Network", "info", "not checked: the tool never touches the network unless you pass --network", "greenfield doctor --network"),
                _r("agent.web_access", "Agent", "info", "web access cannot be detected from a CLI", "Enable browsing in your agent host before research")]
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        busy = s.connect_ex(("127.0.0.1", 8765)) == 0
    out = [_r("dashboard.port", "Dashboard", "warn" if busy else "pass", "port 8765 is in use" if busy else "port 8765 is free", "greenfield dashboard --port 8766" if busy else "")]
    try:
        socket.create_connection(("pypi.org", 443), timeout=3).close()
        out.append(_r("network.reachability", "Network", "pass", "https to pypi.org works"))
    except OSError as e:
        out.append(_r("network.reachability", "Network", "warn", f"cannot reach pypi.org:443 ({e})", "Set your proxy (HTTPS_PROXY) or work offline; offline commands are unaffected"))
    return out + [_r("agent.web_access", "Agent", "info", "web access cannot be detected from a CLI", "Enable browsing in your agent host before research")]


CHECKS = [c_python, c_platform, c_which, c_install, c_hooks, c_privacy, c_attestation, c_run, c_network]


def run_checks(project, network=False):
    project = Path(project).expanduser().resolve()
    run, res = _run_ctx(project)
    ctx = {"project": project, "network": network, "installs": _installs(project), "run": run, "run_result": res}
    out = []
    for check in CHECKS:
        try:
            out += check(ctx)
        except Exception as e:  # a crashing check is a finding, never a crash of doctor
            out.append(_r(f"doctor.{check.__name__[2:]}", "Environment", "warn", f"check crashed: {type(e).__name__}: {e}", "report this"))
    return sorted(out, key=lambda r: GROUPS.index(r["group"]))  # stable: keeps check order inside a group


def summarize(results):
    n = {s: sum(r["status"] == s for r in results) for s in ("pass", "warn", "fail", "info")}
    code = 3 if any(r["id"] == "environment.platform" and r["status"] == "fail" for r in results) else 1 if n["fail"] else 0
    return {**n, "exit_code": code}


def apply_fixes(project, results):
    """Safe local repairs for failing privacy checks. Returns the list of what changed (errors reported, not raised)."""
    project, done = Path(project).expanduser().resolve(), []
    failing = {r["id"] for r in results if r["status"] == "fail"}
    if "privacy.permissions" in failing:
        for p in _loose(project):
            try:
                p.chmod(0o700 if p.is_dir() else 0o600)
                done.append(f"chmod {'700' if p.is_dir() else '600'} {p}")
            except OSError as e:
                done.append(f"could not chmod {p}: {e.strerror or e}")
    if "privacy.ignored" in failing and (missing := gitignore_missing(project)):
        path = project / ".gitignore"
        try:
            if path.is_symlink():
                raise OSError("is a symlink")
            text = path.read_text(encoding="utf-8") if path.exists() else ""
            path.write_text(text + ("\n" if text and not text.endswith("\n") else "") + "\n".join([gf_install.GITIGNORE_MARK, *missing]) + "\n", encoding="utf-8")
            done.append(f"added to .gitignore: {' '.join(missing)}")
        except OSError as e:
            done.append(f"could not update .gitignore: {e.strerror or e}")
    return done


def _handler(args):
    results = run_checks(args.project, args.network)
    fixed = []
    if args.fix and any(r["status"] == "fail" and r["id"] in ("privacy.permissions", "privacy.ignored") for r in results):
        if sys.stdin.isatty() and sys.stdout.isatty() and input("Fix folder permissions and .gitignore now? [y/N] ").strip().lower() not in ("y", "yes"):
            pass
        else:
            fixed = apply_fixes(args.project, results)
            results = run_checks(args.project, args.network)
    s = summarize(results)
    args.exit_code = s["exit_code"]
    return {"checks": results, "summary": s, "fixed": fixed}


def _text(data, args):
    out, group = [], None
    for r in data["checks"]:
        if r["group"] != group:
            group = r["group"]
            out.append(f"\n{group}")
        out.append(f"  {MARK[r['status']]} {r['detail']}")
        if r["fix"] and r["status"] != "pass":
            out.append(f"         fix: {r['fix']}")
    s = data["summary"]
    out += [f"\nFixed: {f}" for f in data["fixed"]]
    p, w = s["fail"], s["warn"]
    out.append(f"\n{p} problem{'s' * (p != 1)}, {w} warning{'s' * (w != 1)}." + (" Run the fix commands above." if p or w else " All good."))
    return "\n".join(out).lstrip("\n") + "\n"


def register(sub, cmd):
    """Add `doctor` to the CLI; cmd is cli._cmd."""
    p = cmd(sub, "doctor", "check your setup and print the command that fixes each problem", [
        "greenfield doctor", "greenfield doctor --fix", "greenfield --json doctor --network"], _handler, _text)
    p.add_argument("--fix", action="store_true", help="repair folder permissions and .gitignore lines (nothing else is changed)")
    p.add_argument("--network", action="store_true", help="also test the dashboard port and one HTTPS host (the only mode that opens sockets)")
