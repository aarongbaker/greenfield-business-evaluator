"""PreToolUse self-attestation guard (W27): refuses agent tool calls that record or forge a human attestation.

Defense in depth only. The real locks are the TTY prompt and the HMAC key (W11); a spelling this parser
misses still cannot produce a valid signature.
"""
from __future__ import annotations
import os
from pathlib import Path
import re
import shlex

LEDGER_NAME = "experiment-ledger.jsonl"
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
FILE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
FOLDER_WORDS = (".config/greenfield", "attest.key", "GF_CONFIG_DIR", "GF_ATTEST_KEY_FILE")
HUMAN = "Attestations are human-only. Run this yourself in your own terminal"


def config_dir():
    return Path(os.environ.get("GF_CONFIG_DIR") or Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "greenfield")


def _real(p, base="."):
    return Path(os.path.realpath(Path(base) / Path(str(p)).expanduser()))


def protected_paths(project="."):
    """Config folder, key file, and the active run's ledger files (resolved)."""
    out = {config_dir()}
    if os.environ.get("GF_ATTEST_KEY_FILE"):
        out.add(Path(os.environ["GF_ATTEST_KEY_FILE"]))
    try:  # no active run is fine
        import gf_context
        from gf_common import load_json
        ctx = gf_context.run_context(project)
        out.add(ctx["ledger"])
        named = load_json(ctx["evaluation"]).get("evidence_ledger")
        if isinstance(named, str) and named:
            out.add(ctx["evaluation"].parent / named)
    except Exception:
        pass
    return {_real(p) for p in out}


def split_commands(cmd):
    """Split a shell line into argv lists on ; & | ( ) < > and newlines. Raises ValueError if unparseable."""
    lex = shlex.shlex(cmd.replace("\n", " ; "), posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    segs, cur = [], []
    for tok in lex:
        if tok and set(tok) <= set(lex.punctuation_chars):
            segs, cur = (segs + [cur] if cur else segs), []
        else:
            cur.append(tok)
    return segs + [cur] if cur else segs


def is_attestation(argv):
    """True for any spelling of a ledger `record` carrying --attester (script, CLI, module, quoted)."""
    text = " ".join(argv)
    return ("--attester" in text and re.search(r"\brecord\b", text) is not None
            and re.search(r"gf_ledger|greenfield|\bledger\b", text) is not None)


def _hit(argv, depth=0):
    head = next((t for t in argv if "=" not in t), "")
    if depth < 3 and os.path.basename(head) in SHELLS:
        for i, t in enumerate(argv[:-1]):
            if re.fullmatch(r"-[a-z]*c", t):
                return any(_hit(s, depth + 1) for s in split_commands(argv[i + 1]))
    return is_attestation(argv)


def _deny_command(cmd, project):
    try:
        for seg in split_commands(cmd):
            if _hit(seg):
                return f"{HUMAN}: {' '.join(seg)}"
    except ValueError:
        if re.search(r"ledger|attester|greenfield", cmd):
            return f"{HUMAN} (this command could not be parsed safely, so it was refused): {cmd}"
    words = FOLDER_WORDS + (str(config_dir()),)
    if any(w in cmd for w in words):
        return "The Greenfield config folder holds the attestation key and is off limits to agents. If you need it, work outside the agent."
    return None


def decide(tool_name, tool_input, project="."):
    """None to allow, or the reason text to deny."""
    if not isinstance(tool_input, dict):
        return None
    if tool_name in FILE_TOOLS:
        raw = tool_input.get("file_path") or tool_input.get("notebook_path") or tool_input.get("path")
        if not isinstance(raw, str) or not raw:
            return None
        p = _real(raw, project)
        if p.name == LEDGER_NAME or any(p == q or q in p.parents for q in protected_paths(project)):
            return f"{p} is a ledger or attestation file. Agents may not write it; edit it yourself, outside the agent, if you must."
        return None
    cmd = tool_input.get("command")
    return _deny_command(cmd, project) if isinstance(cmd, str) else None


def guard_response(raw, project="."):
    """Hook JSON -> deny response dict, or None to allow."""
    if not isinstance(raw, dict) or raw.get("hook_event_name") not in (None, "PreToolUse"):
        return None
    reason = decide(raw.get("tool_name", ""), raw.get("tool_input"), project)
    if reason is None:
        return None
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason}}
