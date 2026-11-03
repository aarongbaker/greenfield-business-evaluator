#!/usr/bin/env python3
"""Opt-in local observability hooks; preserves unrelated hooks and supports removal.

Run after `greenfield install`. Does not modify model permissions, API settings, or global config.
"""
import argparse
import json
from pathlib import Path
import shlex

from gf_common import GFError, VERSION, atomic_write_json
from gf_roles import hook_matcher

NAME = "greenfield-business-evaluator"
MARKER = "gf_observe.py"
GUARD_MARKER = " hook guard --"  # W27: the self-attestation guard's own marker
GUARD_MATCHER = "Bash|Write|Edit|MultiEdit|NotebookEdit|apply_patch"
REGEX = hook_matcher()
PLATFORM_EVENTS = {
    "claude": ("SubagentStart", "SubagentStop", "PreToolUse", "PostToolUseFailure"),
    "codex": ("SubagentStart", "SubagentStop", "PreToolUse"),
}
# Removal also scans events dropped from the table (legacy PostToolUse) and both platforms' sets.
SCAN_EVENTS = tuple(dict.fromkeys(e for v in PLATFORM_EVENTS.values() for e in v)) + ("PostToolUse",)


def path_for(project, platform):
    if platform == "claude":
        return project / ".claude" / "settings.local.json"
    return project / ".codex" / "hooks.json"


def script_for(project, platform):
    base = project / (".claude" if platform == "claude" else ".agents") / "skills" / NAME
    return base / "scripts" / "gf_observe.py"


def _ours(h):
    c = str(h.get("command", "")) if isinstance(h, dict) else ""
    return (MARKER in c and " hook --project " in c, "greenfield.py" in c and GUARD_MARKER in c)


def transform(path, command, mode, *, platform, guard=None):
    """Install/remove hooks. `command` is the observability hook, `guard` the guard; None leaves that kind alone on install."""
    if platform not in PLATFORM_EVENTS:
        raise ValueError(f"Unknown platform: {platform!r}")
    old = json.loads(path.read_text()) if path.is_file() else {}
    if not isinstance(old, dict):
        raise ValueError(f"Expected object at {path}")
    data = json.loads(json.dumps(old))
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError(f"Expected hooks object at {path}")
    for event in SCAN_EVENTS:
        groups = hooks.setdefault(event, [])
        if not isinstance(groups, list):
            raise ValueError(f"Expected array for hooks.{event} in {path}")
        kept = []
        for group in groups:
            if not isinstance(group, dict):
                kept.append(group)
                continue
            hs = group.get("hooks")
            if not isinstance(hs, list):
                kept.append(group)
                continue
            def drop(h):
                obs, grd = _ours(h)
                return (obs and (mode == "remove" or command is not None)) or (grd and (mode == "remove" or guard is not None))
            remainder = [h for h in hs if not drop(h)]
            if remainder:
                copy = dict(group)
                copy["hooks"] = remainder
                kept.append(copy)
        if mode == "install" and guard and event == "PreToolUse":
            kept.append({"matcher": GUARD_MATCHER, "hooks": [{"type": "command", "command": guard, "timeout": 5}]})
        if mode == "install" and command and event in PLATFORM_EVENTS[platform]:
            if event.startswith("Subagent"):
                new_group = {"matcher": REGEX, "hooks": [{"type": "command", "command": command, "timeout": 5}]}
            else:
                # tool matchers filter tool_name, not agent_type; hook code filters agent_type.
                new_group = {"hooks": [{"type": "command", "command": command, "timeout": 5}]}
            kept.append(new_group)
        if kept:
            hooks[event] = kept
        else:
            hooks.pop(event, None)
    if not hooks:
        data.pop("hooks", None)
    # Avoid writing back if unchanged; never overwrite without parsing existing JSON.
    if data != old:
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, data)
    return data != old


def configure(action, project, platform, *, guard=False, observe=True):
    """Install or remove the hooks; return [(changed, settings path)]. GFError (nothing written) if a precondition fails."""
    project = Path(project).expanduser().resolve()
    platforms = ("claude", "codex") if platform == "both" else (platform,)
    if action == "install":
        missing = [str(script_for(project, name)) for name in platforms if not script_for(project, name).is_file()]
        if missing:
            raise GFError("Install the Greenfield skill first. Missing:\n" + "\n".join(missing), hint="greenfield install", code=3)
    # Preflight JSON validity on every destination before modifying any of them.
    for name in platforms:
        path = path_for(project, name)
        if path.is_file():
            data = json.loads(path.read_text())
            if not isinstance(data, dict) or not isinstance(data.get("hooks", {}), dict):
                raise GFError(f"Unexpected hooks JSON format: {path}", path=path)
    out = []
    for name in platforms:
        script = script_for(project, name)
        # Absolute script and project paths allow hooks to work from nested cwd.
        cmd = " ".join(("python3", shlex.quote(str(script)), "hook", "--project", shlex.quote(str(project)), "--provider", name))
        gcmd = " ".join(("python3", shlex.quote(str(script.with_name("greenfield.py"))), "hook guard --project", shlex.quote(str(project)), "--provider", name))
        out.append((transform(path_for(project, name), cmd if observe else None, action, platform=name, guard=gcmd if guard else None), path_for(project, name)))
    return out


INSTALL_NOTE = ("Review/trust project hooks in your agent client. Mission Control hooks record metadata only; the guard hook refuses agent attempts to record human attestations.\n"
                "For Codex, open /hooks and approve the newly installed hooks if prompted.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    parser.add_argument("action", choices=("install", "remove"))
    parser.add_argument("--project", default=".")
    parser.add_argument("--platform", choices=("claude", "codex", "both"), default="both")
    args = parser.parse_args(argv)
    try:
        result = configure(args.action, args.project, args.platform)
    except GFError as e:
        parser.error(str(e))
    for changed, path in result:
        print(("Updated" if changed else "Already current"), path)
    if args.action == "install":
        print(INSTALL_NOTE)
    return 0
