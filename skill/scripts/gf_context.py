"""Run context (W24): where the active run keeps its files, so commands need no paths."""
from __future__ import annotations
from gf_common import GFError, resolve_inside
import gf_observe


def run_context(project, run=None):
    """{run_id, research_dir, evaluation, decision, ledger, verification} for --run or the active run."""
    rid = run if run is not None else gf_observe.active_run(project)
    if run is not None:
        gf_observe.file_paths(project, run)  # validates the id (W6)
    if not rid:
        raise GFError("No active run", path=project, hint="Start one with `greenfield start --idea ...`, or pass a path.")
    meta = gf_observe.load_json(gf_observe.file_paths(project, rid)[0])
    rd = meta.get("research_dir")
    if not isinstance(rd, str) or not rd:
        raise GFError(f"run {rid} has no research folder", hint="greenfield link --research-dir research/greenfield/NAME")
    folder = resolve_inside(gf_observe.research_base(project, meta), rd)
    return {"run_id": rid, "research_dir": folder, "evaluation": folder / "evaluation.json", "decision": folder / "decision.json",
            "ledger": folder / "experiment-ledger.jsonl", "verification": folder / "source-verification.json"}
