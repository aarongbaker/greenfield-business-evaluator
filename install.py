#!/usr/bin/env python3
"""Install the shared Greenfield Business Evaluator skill into Claude Code and/or Codex.

Pure Python 3.11+, no network and no modification to model settings/configs.
Project scope: <project>/.claude/skills, <project>/.agents/skills, and role folders.
Personal scope: ~/.claude/skills, ~/.agents/skills; role folders in ~/.claude/agents and ~/.codex/agents.
"""

import argparse
import fnmatch
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parent
SKILL_NAME = "greenfield-business-evaluator"
IGNORED = ("__pycache__", "*.pyc", "*.pyo", ".DS_Store", "*.tmp-*", ".pytest_cache")
IGNORE = shutil.ignore_patterns(*IGNORED)
sys.path.insert(0, str(ROOT / "skill" / "scripts"))
from gf_common import VERSION, gitignore_missing

GITIGNORE_MARK = "# greenfield-business-evaluator: private research"


def install_file(src: pathlib.Path, dst: pathlib.Path, force: bool):
    if dst.exists() and not force:
        raise FileExistsError(f"{dst} exists. Re-run with --force to replace")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return dst


def install_skill(dst: pathlib.Path, force: bool):
    source = ROOT / "skill"
    if dst.exists():
        if not force:
            raise FileExistsError(f"{dst} exists. Re-run with --force to replace")
        # Replace only the owned skill folder; do not modify other skills.
        shutil.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, dst, ignore=IGNORE)
    leaked = [p for p in dst.rglob("*") if any(fnmatch.fnmatch(p.name, pat) for pat in IGNORED)]
    if leaked:
        raise RuntimeError(f"Ignored files were copied into {dst}: {leaked[:3]}")
    (dst / ".greenfield-version").write_text(VERSION + "\n", encoding="utf-8")
    return dst


def offer_gitignore(base: pathlib.Path, *, add: bool, never: bool):
    """Offer to git-ignore private research folders. Never fails the install; off a TTY only prints the lines."""
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
            print("Added to .gitignore:", " ".join(missing))
            return
        except OSError:
            pass
    print("Add these lines to .gitignore to keep private research out of commits:\n  " + "\n  ".join(missing))


def main(argv=None):
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
    args = parser.parse_args(argv)
    base = pathlib.Path(args.project).expanduser().resolve() if args.scope == "project" else pathlib.Path.home()
    targets = []
    if args.platform in ("claude", "both"):
        targets.append(("claude", base / ".claude" / "skills" / SKILL_NAME, base / ".claude" / "agents"))
    if args.platform in ("codex", "both"):
        targets.append(("codex", base / ".agents" / "skills" / SKILL_NAME,
                        base / (".codex" if args.scope == "project" else ".codex") / "agents"))
    # Preflight all destinations, so we don't partially install if they already exist.
    dests = []
    for platform, skill_dest, agent_dest in targets:
        dests.append(skill_dest)
        if not args.no_agents:
            dests.extend(agent_dest / p.name for p in sorted((ROOT / "platform" / platform / "agents").glob("gf-*.*")))
    conflicts = [p for p in dests if p.exists()]
    if conflicts and not args.force:
        print("Will not overwrite existing files without --force:\n" + "\n".join(str(p) for p in conflicts), file=sys.stderr)
        return 2
    for platform, skill_dest, agent_dest in targets:
        print("Installed", install_skill(skill_dest, args.force))
        if not args.no_agents:
            for src in sorted((ROOT / "platform" / platform / "agents").glob("gf-*.*")):
                print("Installed", install_file(src, agent_dest / src.name, args.force))
    if args.scope == "project":
        offer_gitignore(base, add=args.gitignore, never=args.no_gitignore)
    print("\nInstallation complete. Restart the coding agent if the skill is not immediately visible.")
    print("Claude: /greenfield-business-evaluator <idea>")
    print("Codex:  $greenfield-business-evaluator <idea>")
    print("This install does not enable network tools or bypass permissions. Check agent web access for live research.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
