"""PreToolUse self-attestation guard (W27): refuses agent tool calls that record or forge a human attestation.

Defense in depth only. The real locks are the TTY prompt and the HMAC key (W11); a spelling this parser
misses still cannot produce a valid signature.
"""
from __future__ import annotations
import os
from pathlib import Path
import re
import shlex

from gf_ledger import LEDGER_NAME, config_dir

SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
FILE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
READ_TOOLS = {"Read", "Grep", "Glob"}
SIGNED_FILES = {LEDGER_NAME, "quality-history.jsonl", "source-verification.json"}
RAW_DENIED = "Agents may not read materials/raw/: it holds unredacted personal data"
FILES_DENIED = "That path holds signed evidence or private materials, and agents may not touch it. Run the command yourself, outside the agent."
GF_HEADS = {"greenfield", "greenfield.py", "cli.py"}
# Read-only or tool-owned commands that legitimately name a signed file (skill/references/v2-workflows.md).
EXEMPT = re.compile(r"\b(?:ledger\s+(?:verify|summary|record)|task\s+coverage|sources\s+check|score)\b")
SEGMENT = re.compile(r"(?:^|/)(?:materials/raw(?:/|$)|receipts/|(?:experiment-ledger\.jsonl|quality-history\.jsonl|source-verification\.json)$)")
RAW_GLOB = re.compile(r"(?:^|/)materials/+(?:raw(?:/|$)|[*?\[{])|\*\*/raw(?:/|$)")
FOLDER_WORDS = (".config/greenfield", "attest.key", "GF_CONFIG_DIR", "GF_ATTEST_KEY_FILE")
HUMAN = "Attestations are human-only. Run this yourself in your own terminal"


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
    """True for a `record` carrying --attester or an intake command, however spelled or wrapped (script, unbuffer, expect, python -c)."""
    text = re.sub(r"[\[\]'\",()]", " ", " ".join(argv))  # pty.spawn(['greenfield','evidence','add']) reads as words
    if re.search(r"\b(?:greenfield|cli\.py|gf_ledger)\b.*\b(?:evidence\s+(?:add|redact)|(?:ledger\s+)?(?:reattest|reidea))\b", text):
        return True
    return ("--attester" in text and re.search(r"\brecord\b", text) is not None
            and re.search(r"gf_ledger|greenfield|\bledger\b", text) is not None)


def _hit(argv, depth=0):
    head = next((t for t in argv if "=" not in t), "")
    if depth < 3 and os.path.basename(head) in SHELLS:
        for i, t in enumerate(argv[:-1]):
            if re.fullmatch(r"-[a-z]*c", t):
                return any(_hit(s, depth + 1) for s in split_commands(argv[i + 1]))
    return is_attestation(argv)


def _touches_signed(argv):
    head = next((t for t in argv if "=" not in t), "")
    runner = {os.path.basename(t) for t in argv[:2]}
    if runner & GF_HEADS and EXEMPT.search(" ".join(argv)):
        return False
    if os.path.basename(head) in SHELLS:  # sh -c is unpacked by _hit_files
        return False
    return any(SEGMENT.search(part) for t in argv for part in t.split("="))


def _hit_files(argv, depth=0):
    head = next((t for t in argv if "=" not in t), "")
    if depth < 3 and os.path.basename(head) in SHELLS:
        for i, t in enumerate(argv[:-1]):
            if re.fullmatch(r"-[a-z]*c", t):
                return any(_hit_files(s, depth + 1) for s in split_commands(argv[i + 1]))
    return _touches_signed(argv)


def _deny_command(cmd, project):
    try:
        for seg in split_commands(cmd):
            if _hit(seg):
                return f"{HUMAN}: {' '.join(seg)}"
            if _hit_files(seg):
                return FILES_DENIED
    except ValueError:
        if re.search(r"ledger|attester|greenfield|materials/raw|receipts/", cmd):
            return f"{HUMAN} (this command could not be parsed safely, so it was refused): {cmd}"
    words = FOLDER_WORDS + (str(config_dir()),)
    if any(w in cmd for w in words):
        return "The Greenfield config folder holds the attestation key and is off limits to agents. If you need it, work outside the agent."
    return None


def _is_run_folder(p):
    return (p / "evaluation.json").exists()


def _in_raw(p):
    return any(a.name == "raw" and a.parent.name == "materials" for a in (p, *p.parents))


def _deny_read(tool_name, tool_input, project):
    raw = tool_input.get("file_path") if tool_name == "Read" else tool_input.get("path")
    if isinstance(raw, str) and raw:
        p = _real(raw, project)
        keys = {_real(config_dir())} | ({_real(os.environ["GF_ATTEST_KEY_FILE"])} if os.environ.get("GF_ATTEST_KEY_FILE") else set())
        if _in_raw(p) or any(p == q or q in p.parents for q in keys):
            return RAW_DENIED
        # shortcut: a search rooted above the run folder can still reach raw/ (documented known gap).
        if tool_name != "Read" and p.is_dir() and (_is_run_folder(p) or (p.name == "materials" and _is_run_folder(p.parent))):
            return RAW_DENIED
    pattern = tool_input.get("pattern") if tool_name == "Glob" else tool_input.get("glob")
    if tool_name != "Read" and isinstance(pattern, str) and RAW_GLOB.search(pattern):
        return RAW_DENIED
    return None


def _signed_path(p):
    if p.name in SIGNED_FILES or _in_raw(p):
        return True
    return any(a.name == "receipts" and _is_run_folder(a.parent) for a in p.parents)  # src/receipts/ in the founder's own code stays writable


def decide(tool_name, tool_input, project="."):
    """None to allow, or the reason text to deny."""
    if not isinstance(tool_input, dict):
        return None
    if tool_name in FILE_TOOLS:
        raw = tool_input.get("file_path") or tool_input.get("notebook_path") or tool_input.get("path")
        if not isinstance(raw, str) or not raw:
            return None
        p = _real(raw, project)
        if _signed_path(p) or any(p == q or q in p.parents for q in protected_paths(project)):
            return f"{p} is a ledger or attestation file. Agents may not write it; edit it yourself, outside the agent, if you must."
        return None
    if tool_name in READ_TOOLS:
        return _deny_read(tool_name, tool_input, project)
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
