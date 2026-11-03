"""W29: the generated top of DECISION.md (verdict callout + scorecard), rendered from decision.json and evaluation.json."""
from __future__ import annotations
import difflib
import hashlib
import sys
from pathlib import Path
from _version import __version__
from gf_common import GFError, atomic_write, load_json
from gf_portfolio import md_cell
from gf_profiles import PROFILES
from score_project import GLYPHS, bar, clip, gap_text, verdict_gap

START = "<!-- greenfield:generated v1 — do not edit; run `greenfield report` -->"
END = "<!-- greenfield:generated end -->"
ALERTS = {"NO_GO": "CAUTION", "PIVOT": "WARNING", "RESEARCH_INCOMPLETE": "NOTE",
          "VALIDATE_BEFORE_BUILD": "TIP", "PROCEED_TO_BOUNDED_PILOT": "IMPORTANT"}


def render_block(decision, evaluation, sha="", ascii=False):
    """The marker-wrapped block. Raises GFError when decision.json no longer matches evaluation.json (re-run `score`)."""
    style = "ascii" if ascii else "unicode"
    pillars, g = evaluation["pillars"], GLYPHS[style]
    for p, w in decision["pillar_weights"].items():
        if (pillars[p].get("quality"), pillars[p]["evidence"]) != (decision["quality_scores"][p], decision["evidence_scores"][p]):
            raise GFError("decision.json is stale: scores differ from evaluation.json", hint="run `greenfield score` first")
    d, ex = decision["decision"], evaluation["execution"]
    profile = decision["business_model_profile"]
    gates = PROFILES.get(profile, PROFILES["general"])["pilot_gates"]
    total, runs = decision["weighted_quality_0_to_100"], ex.get("subagents_actual", 0)
    research = ("live web" if decision["web_research_performed"] else "no live web") + \
        (f", {runs} parallel specialists" if runs else f", {ex.get('mode', 'single agent').replace('_', ' ')}")
    rows = ["| Pillar | Weight | Quality | Evidence | Finding | Claims |", "| --- | --- | --- | --- | --- | --- |"]
    for p, w in sorted(decision["pillar_weights"].items(), key=lambda kv: -kv[1]):
        q, e, src = decision["quality_scores"][p], decision["evidence_scores"][p], pillars[p]
        gap = " (gap)" if q is not None and q >= 4 and e <= 1 else ""
        rows.append(f"| {p.capitalize()} | {w} | {bar(q, style) + f' {q}' if q is not None else g['sep'] * 5 + '  not assessed'} | "
                    f"{bar(e, style)} {e} | {md_cell(src.get('finding') or 'Not evaluated')}{gap} | "
                    f"{', '.join(md_cell(c) for c in src.get('claim_ids') or [])} |")
    change = gap_text(verdict_gap(decision)) or "none; the verdict is already Proceed to bounded pilot"
    lines = [START, f"# {clip(decision['project'], 120)}: investment memo", "",
             f"As of {decision['as_of'] or 'not started'} {g['sep']} Profile: {profile} {g['sep']} Research: {research} {g['sep']} "
             f"Scorer {__version__}" + (f" {g['sep']} decision.json sha256 {sha[:4]}{g['more']}{sha[-4:]}" if sha else ""), "",
             f"> [!{ALERTS[d]}]", f"> **{d}.** {decision['headline']}", ">",
             f"> Weighted quality {f'{total:g} / 100' if total is not None else 'incomplete'} {g['sep']} "
             f"Evidence average {decision['evidence_average_0_to_5']:.1f} / 5 {g['sep']} " +
             (f"{len(gates) - len(decision['missing_pilot_gates'])} of {len(gates)} pilot gates passed" if gates else "no pilot gates"), "",
             *rows, "", f"**What would change this verdict:** {md_cell(change, 400)}", END]
    if ascii:  # the markers stay byte-identical so merge still finds them
        lines[1:-1] = [x.encode("ascii", "replace").decode() for x in lines[1:-1]]
    return "\n".join(lines) + "\n"


def _span(lines):
    """(start, end) line indexes of the generated block, ignoring marker lookalikes inside code fences; None if absent."""
    fence, start = None, None
    for i, line in enumerate(lines):
        s = line.strip()
        if s[:3] in ("```", "~~~"):
            fence = None if fence == s[:3] else fence or s[:3]
        elif fence is None and start is None and s.startswith("<!-- greenfield:generated v1"):
            start = i
        elif fence is None and start is not None and s == END:
            return start, i
    return None


def merge(existing_md, block):
    """Replace the block between the markers, every other byte untouched; no markers: put it on top."""
    lines = existing_md.splitlines(keepends=True)
    span = _span(lines)
    if span is None:
        return block + ("\n" + existing_md if existing_md else "")
    return "".join(lines[:span[0]]) + block + "".join(lines[span[1] + 1:])


def edited_lines(existing_md, last_block):
    """1-based memo line numbers inside the generated block that differ from `last_block` (what `report` last wrote)."""
    lines = existing_md.splitlines()
    span = _span(existing_md.splitlines(keepends=True))
    if span is None or not last_block:
        return []
    cur, old = lines[span[0]:span[1] + 1], last_block.splitlines()
    out = []
    for tag, i1, i2, _, _ in difflib.SequenceMatcher(None, old, cur, autojunk=False).get_opcodes():
        if tag != "equal":
            out += range(span[0] + i1 + 1, span[0] + max(i2, i1 + 1) + 1)
    return out


def _handler(args):
    if args.folder:
        folder = args.folder
    else:
        import gf_context
        folder = gf_context.run_context(args.project, args.run)["research_dir"]
    dec_path, memo = folder / "decision.json", folder / "DECISION.md"
    if not dec_path.exists():
        raise GFError("decision.json not found", path=dec_path, hint="run `greenfield score` first")
    decision = load_json(dec_path)
    evaluation = load_json(folder / "evaluation.json")
    block = render_block(decision, evaluation, hashlib.sha256(dec_path.read_bytes()).hexdigest(), args.ascii)
    existing = memo.read_text(encoding="utf-8") if memo.exists() else ""
    if existing and _span(existing.splitlines(keepends=True)) is None:
        print(f"note: {memo.name} had no generated block; inserted one at the top, nothing removed", file=sys.stderr)
    side = folder / ".DECISION.generated.md"  # last block written, so a hand edit can be named next time
    edited = edited_lines(existing, side.read_text(encoding="utf-8") if side.exists() else "")
    if edited:
        print(f"warning: overwrote hand edits to the generated block in {memo.name} (lines {', '.join(map(str, edited))}); "
              "put your own text below the block", file=sys.stderr)
    atomic_write(memo, merge(existing, block))
    atomic_write(side, block)
    return {"path": str(memo), "decision": decision["decision"]}


def register(sub, cmd):
    p = cmd(sub, "report", "write the verdict callout and scorecard at the top of DECISION.md from decision.json", [
        "greenfield report", "greenfield report research/greenfield/my-idea --ascii"], _handler,
        lambda r, a: f"Updated {r['path']} ({r['decision']})\n")
    p.add_argument("folder", type=Path, nargs="?", help="research folder with evaluation.json and decision.json (default: the active run's)")
    p.add_argument("--run", metavar="ID", help="run id (default: the active run)")
    p.add_argument("--ascii", action="store_true", help="use # and . instead of block characters")
