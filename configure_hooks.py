#!/usr/bin/env python3
"""Opt-in local observability hooks; preserves unrelated hooks and supports removal.

Run after install.py. Does not modify model permissions, API settings, or global config.
"""
import argparse
import json
from pathlib import Path
import shlex
import sys

NAME = "greenfield-business-evaluator"
MARKER = "gf_observe.py"
REGEX = "^gf[-_](problem|market|competition|economics|value|distribution|execution|timing|redteam)$"


def path_for(project, platform):
    if platform == "claude":
        return project / ".claude" / "settings.local.json"
    return project / ".codex" / "hooks.json"


def script_for(project, platform):
    base = project / (".claude" if platform == "claude" else ".agents") / "skills" / NAME
    return base / "scripts" / "gf_observe.py"


def transform(path, command, mode):
    old = json.loads(path.read_text()) if path.is_file() else {}
    if not isinstance(old, dict):
        raise ValueError(f"Expected object at {path}")
    data = json.loads(json.dumps(old))
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError(f"Expected hooks object at {path}")
    events = ("SubagentStart", "SubagentStop", "PreToolUse", "PostToolUse", "PostToolUseFailure")
    if "codex" in str(path):
        events = events[:-1]
    for event in events:
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
            remainder = [h for h in hs if not (isinstance(h, dict) and (MARKER in str(h.get("command", "")) and " hook --project " in str(h.get("command", ""))))]
            if remainder:
                copy = dict(group)
                copy["hooks"] = remainder
                kept.append(copy)
        if mode == "install":
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
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
    return data != old


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "remove"))
    parser.add_argument("--project", default=".")
    parser.add_argument("--platform", choices=("claude", "codex", "both"), default="both")
    args = parser.parse_args(argv)
    project = Path(args.project).expanduser().resolve()
    platforms = ("claude", "codex") if args.platform == "both" else (args.platform,)
    if args.action == "install":
        missing = [str(script_for(project, name)) for name in platforms if not script_for(project, name).is_file()]
        if missing:
            parser.error("Install the Greenfield skill first. Missing:\n" + "\n".join(missing))
    # Preflight JSON validity on every destination before modifying any of them.
    for platform in platforms:
        path = path_for(project, platform)
        if path.is_file():
            data = json.loads(path.read_text())
            if not isinstance(data, dict) or not isinstance(data.get("hooks", {}), dict):
                parser.error(f"Unexpected hooks JSON format: {path}")
    for platform in platforms:
        script = script_for(project, platform)
        # Absolute script and project paths allow hooks to work from nested cwd.
        cmd = " ".join(("python3", shlex.quote(str(script)), "hook", "--project", shlex.quote(str(project)), "--provider", platform))
        changed = transform(path_for(project, platform), cmd, args.action)
        print(("Updated" if changed else "Already current"), path_for(project, platform))
    if args.action == "install":
        print("Review/trust project hooks in your agent client. These hooks observe metadata only and never block execution.")
        print("For Codex, open /hooks and approve the newly installed hooks if prompted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
