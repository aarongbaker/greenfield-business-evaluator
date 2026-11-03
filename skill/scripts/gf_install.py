#!/usr/bin/env python3
"""Install the shared Greenfield Business Evaluator skill into Claude Code and/or Codex.

Pure Python 3.11+, no network and no modification to model settings/configs.
Project scope: <project>/.claude/skills, <project>/.agents/skills, and role folders.
Personal scope: ~/.claude/skills, ~/.agents/skills; role folders in ~/.claude/agents and ~/.codex/agents.
"""

import argparse
import datetime
import fnmatch
import hashlib
import json
import os
import pathlib
import shutil
import sys

from gf_common import GFError, VERSION, atomic_write_json, gitignore_missing

SKILL_SRC = pathlib.Path(__file__).resolve().parent.parent  # skill/ in a clone, greenfield_evaluator/ in a wheel
# A clone keeps role files beside skill/; the wheel ships them inside the package.
AGENT_SRC = next((p for p in (SKILL_SRC.parent / "platform", SKILL_SRC / "platform") if p.is_dir()), None)
SKILL_NAME = "greenfield-business-evaluator"
IGNORED = ("__pycache__", "*.pyc", "*.pyo", ".DS_Store", "*.tmp-*", ".pytest_cache", "platform")
IGNORE = shutil.ignore_patterns(*IGNORED)

GITIGNORE_MARK = "# greenfield-business-evaluator: private research"


def install_file(src: pathlib.Path, dst: pathlib.Path, force: bool):
    if dst.exists() and not force:
        raise FileExistsError(f"{dst} exists. Re-run with --force to replace")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return dst


MANIFEST = ".greenfield-install.json"


def sha(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def tree_hashes(root):
    """{relative posix path: sha256} for the files an install places under root (ignored names skipped)."""
    out = {}
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not any(fnmatch.fnmatch(d, pat) for pat in IGNORED)]
        for f in files:
            if not any(fnmatch.fnmatch(f, pat) for pat in IGNORED):
                p = pathlib.Path(dirpath, f)
                out[p.relative_to(root).as_posix()] = sha(p)
    return out


def read_manifest(skill_dest):
    """The install manifest, or None when absent or unreadable (callers fall back to the package's own files)."""
    try:
        data = json.loads((pathlib.Path(skill_dest) / MANIFEST).read_text(encoding="utf-8"))
        return data if isinstance(data.get("skill_files"), dict) and isinstance(data.get("agents"), dict) else None
    except (OSError, ValueError, AttributeError):
        return None


def write_manifest(skill_dest, agents, scope):
    skill_dest = pathlib.Path(skill_dest)
    files = {k: v for k, v in tree_hashes(skill_dest).items() if k != MANIFEST}
    atomic_write_json(skill_dest / MANIFEST, {
        "version": VERSION, "platform": "claude" if ".claude" in skill_dest.parts else "codex",
        "scope": scope, "installed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "skill_files": files, "agents": {str(d): sha(d) for _, d in agents if d.is_file()}})


def stage_and_swap(src, dst):
    """Copy src to a sibling staging folder, then swap by rename; on any error the old dst is left as it was."""
    dst = pathlib.Path(dst)
    stage, old = dst.with_name(dst.name + ".tmp-stage"), dst.with_name(dst.name + ".tmp-old")
    for p in (stage, old):
        shutil.rmtree(p, ignore_errors=True)
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copytree(src, stage, ignore=IGNORE)
        leaked = [p for p in stage.rglob("*") if any(fnmatch.fnmatch(p.name, pat) for pat in IGNORED)]
        if leaked:
            raise RuntimeError(f"Ignored files were copied into {dst}: {leaked[:3]}")
        (stage / ".greenfield-version").write_text(VERSION + "\n", encoding="utf-8")
        if dst.exists():
            dst.rename(old)
            try:
                stage.rename(dst)
            except OSError:
                old.rename(dst)
                raise
        else:
            stage.rename(dst)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    shutil.rmtree(old, ignore_errors=True)
    return dst


def install_skill(dst: pathlib.Path, force: bool):
    if dst.exists() and not force:
        raise FileExistsError(f"{dst} exists. Re-run with --force to replace")
    return stage_and_swap(SKILL_SRC, dst)


def offer_gitignore(base: pathlib.Path, *, add: bool, never: bool, out=None):
    """Offer to git-ignore private research folders. Never fails the install; off a TTY only prints the lines."""
    out = out or sys.stdout
    missing = gitignore_missing(base)
    if never or not missing or not (base / ".git").exists():
        return
    if not add and sys.stdin.isatty():
        try:
            add = input("Add these to .gitignore so private research stays out of commits? [Y/n] " + " ".join(missing) + " ").strip().lower() in ("", "y", "yes")
        except EOFError:
            add = False
        if not add:
            return
    path = base / ".gitignore"
    if add and not path.is_symlink():
        try:
            text = path.read_text(encoding="utf-8") if path.exists() else ""
            sep = "\n" if text and not text.endswith("\n") else ""
            path.write_text(text + sep + "\n".join([GITIGNORE_MARK, *missing]) + "\n", encoding="utf-8")
            print("Added to .gitignore:", " ".join(missing), file=out)
            return
        except OSError:
            pass
    print("Add these lines to .gitignore to keep private research out of commits:\n  " + "\n  ".join(missing), file=out)


def plan(platform, scope, project, no_agents):
    """[(skill_dest, [(agent_src, agent_dest)])] per platform; GFError when role files are needed but not shipped."""
    base = pathlib.Path(project).expanduser().resolve() if scope == "project" else pathlib.Path.home()
    if not no_agents and AGENT_SRC is None:
        raise GFError("agent role files are not in this copy", path=SKILL_SRC, hint="install from a clone or the package, or pass --no-agents", code=3)
    out = []
    for name in (("claude", "codex") if platform == "both" else (platform,)):
        skill_dest = base / (".claude" if name == "claude" else ".agents") / "skills" / SKILL_NAME
        agent_dest = base / (".claude" if name == "claude" else ".codex") / "agents"
        agents = [] if no_agents else [(p, agent_dest / p.name) for p in sorted((AGENT_SRC / name / "agents").glob("gf-*.*"))]
        out.append((skill_dest, agents))
    return base, out


def conflicts(targets):
    return [p for skill, agents in targets for p in [skill, *(d for _, d in agents)] if p.exists()]


def plan_install(targets, force=False, overwrite_modified=False):
    """[{op: create|replace, path, reason}] for what install will touch; GFError when it must refuse. Writes nothing."""
    acts, edited = [], []
    for skill_dest, agents in targets:
        rec = (read_manifest(skill_dest) or {}).get("agents", {})
        for path in [skill_dest, *(d for _, d in agents)]:
            if not path.exists():
                acts.append({"op": "create", "path": str(path), "reason": "new"})
                continue
            if not force:
                raise GFError(f"will not overwrite {path} without --force", path=path, hint="greenfield install --force")
            if path.is_file() and str(path) in rec and sha(path) != rec[str(path)]:
                edited.append(path)
            acts.append({"op": "replace", "path": str(path), "reason": "--force"})
    if edited and not overwrite_modified:
        raise GFError("edited since install: " + ", ".join(p.name for p in edited), path=edited[0], hint="greenfield install --force --overwrite-modified")
    return acts


def install(targets, force, scope="project", overwrite_modified=False):
    """Copy the skill and role files; return the installed paths."""
    plan_install(targets, force, overwrite_modified)
    done = []
    for skill_dest, agents in targets:
        done.append(install_skill(skill_dest, force))
        done.extend(install_file(src, dst, force) for src, dst in agents)
        write_manifest(skill_dest, agents, scope)
    return done


def _hooks_present(base, platform):
    import gf_hooks
    p = gf_hooks.path_for(base, platform)
    try:
        t = p.read_text(encoding="utf-8")
    except OSError:
        return False
    return (gf_hooks.MARKER in t and " hook --project " in t) or gf_hooks.GUARD_MARKER in t


def plan_uninstall(platform, scope, project, keep_hooks=False, purge_telemetry=False):
    """Removal plan [{op: remove|skip, path, reason}]. Only files whose hash matches the manifest (or the package copy) go."""
    if scope == "all":
        base, acts = plan_uninstall(platform, "project", project, keep_hooks, purge_telemetry)
        return base, acts + plan_uninstall(platform, "user", project, keep_hooks, purge_telemetry)[1]
    base, targets = plan(platform, scope, project, False)
    acts = []

    def judge(path, want):
        if not path.is_file():
            return
        if want is None or sha(path) == want:
            acts.append({"op": "remove", "path": str(path), "reason": "installed by greenfield"})
        else:
            acts.append({"op": "skip", "path": str(path), "reason": "edited since install, kept"})

    for skill_dest, agents in targets:
        man = read_manifest(skill_dest)
        if man is None and (skill_dest / MANIFEST).exists():
            acts.append({"op": "skip", "path": str(skill_dest / MANIFEST), "reason": "manifest unreadable, using package copy"})
        files = man["skill_files"] if man else tree_hashes(SKILL_SRC)
        for rel, want in files.items():
            judge(skill_dest / rel, want)
        for src, dst in agents:
            judge(dst, man["agents"].get(str(dst)) if man else sha(src))
        if not keep_hooks:
            name = "claude" if ".claude" in skill_dest.parts else "codex"
            if _hooks_present(base, name):
                import gf_hooks
                acts.append({"op": "remove", "path": str(gf_hooks.path_for(base, name)), "reason": "greenfield hooks (other hooks kept)"})
    if purge_telemetry and (base / ".greenfield-observe").is_dir():
        acts.append({"op": "remove", "path": str(base / ".greenfield-observe"), "reason": "--purge-telemetry"})
    return base, acts


def apply_uninstall(base, acts, platform, scope):
    """Remove planned paths; an OSError on one path is reported on stderr and skipped. Returns the failure count."""
    import gf_hooks
    failed = 0
    for a in acts:
        p = pathlib.Path(a["path"])
        if a["op"] != "remove":
            continue
        try:
            if p.name in ("settings.local.json", "hooks.json") and "hooks" in a["reason"]:
                gf_hooks.configure("remove", p.parent.parent, "claude" if p.name == "settings.local.json" else "codex")
            elif p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink(missing_ok=True)
        except OSError as e:
            failed += 1
            print(f"ERROR: could not remove {p}: {e}", file=sys.stderr)
    # Drop the leftovers install created, then empty folders; a folder still holding kept files stays.
    for sc, b in (("project", base), ("user", base)) if scope == "all" else ((scope, base),):
        for skill_dest, agents in plan(platform, sc, b, True)[1]:
            for junk in (MANIFEST, ".greenfield-version"):
                try:
                    (skill_dest / junk).unlink(missing_ok=True)
                except OSError as e:
                    failed += 1
                    print(f"ERROR: could not remove {skill_dest / junk}: {e}", file=sys.stderr)
            for dirpath, _, _ in os.walk(skill_dest, topdown=False):
                d = pathlib.Path(dirpath)
                if d.name == "__pycache__":
                    shutil.rmtree(d, ignore_errors=True)
                try:
                    d.rmdir()
                except OSError:
                    pass
    return failed


def uninstall_main(argv):
    parser = argparse.ArgumentParser(prog="greenfield uninstall", description="Remove what install placed; edited files and research are kept.")
    parser.add_argument("--platform", choices=("claude", "codex", "both"), default="both")
    parser.add_argument("--scope", choices=("project", "user", "all"), default="project")
    parser.add_argument("--project", default=".")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--keep-hooks", action="store_true")
    parser.add_argument("--purge-telemetry", action="store_true")
    args = parser.parse_args(argv)
    try:
        base, acts = plan_uninstall(args.platform, args.scope, args.project, args.keep_hooks, args.purge_telemetry)
        for a in acts:
            print(f"{a['op']:7} {a['path']}  ({a['reason']})")
        if args.dry_run or not any(a["op"] == "remove" for a in acts):
            return 0
        if not args.yes:
            if not sys.stdin.isatty():
                raise GFError("refusing to delete without confirmation", hint="re-run with --yes")
            if input("Remove these? [y/N] ").strip().lower() not in ("y", "yes"):
                return 1
        failed = apply_uninstall(base, acts, args.platform, args.scope)
    except GFError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    if failed:
        print(f"{failed} path(s) could not be removed; fix permissions and re-run `greenfield uninstall --yes`.", file=sys.stderr)
        return 1
    print("Removed. .gitignore lines and research/greenfield/ were left in place.")
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:1] == ["uninstall"]:
        return uninstall_main(argv[1:])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    parser.add_argument("--platform", choices=("claude", "codex", "both"), default="both")
    parser.add_argument("--scope", choices=("project", "user"), default="project")
    parser.add_argument("--project", default=".", help="Project root (for --scope project)")
    parser.add_argument("--no-agents", action="store_true", help="Install skill only; fan-out will use default subagents or sequential fallback")
    parser.add_argument("--force", action="store_true", help="Overwrite existing managed files/folders")
    g = parser.add_mutually_exclusive_group()
    g.add_argument("--gitignore", action="store_true", help="Add private research folders to .gitignore without asking (project scope, git repos)")
    g.add_argument("--no-gitignore", action="store_true", help="Never offer to edit .gitignore")
    parser.add_argument("--overwrite-modified", action="store_true", help="with --force, also replace role files you edited")
    parser.add_argument("--dry-run", action="store_true", help="print what would change and write nothing")
    args = parser.parse_args(argv)
    try:
        base, targets = plan(args.platform, args.scope, args.project, args.no_agents)
    except GFError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    try:
        acts = plan_install(targets, args.force, args.overwrite_modified)
    except GFError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    if args.dry_run:
        for a in acts:
            print(f"{a['op']:7} {a['path']}")
        return 0
    for path in install(targets, args.force, args.scope, args.overwrite_modified):
        print("Installed", path)
    if args.scope == "project":
        offer_gitignore(base, add=args.gitignore, never=args.no_gitignore)
    print("\nInstallation complete. Restart the coding agent if the skill is not immediately visible.")
    print("Claude: /greenfield-business-evaluator <idea>")
    print("Codex:  $greenfield-business-evaluator <idea>")
    print("This install does not enable network tools or bypass permissions. Check agent web access for live research.")
    return 0
