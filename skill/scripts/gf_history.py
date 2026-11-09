"""W49: quality is a finding. Each score of a run folder appends a snapshot to quality-history.jsonl, and the
differences between snapshots form a cumulative change log that every score prints, so a hand edit stays visible
even after it is undone. The quality baseline is all-null by definition: research-set qualities are changes too."""
from __future__ import annotations
import datetime as dt
import hashlib
import json
import os
from pathlib import Path

import gf_materials
from gf_profiles import BASE, PROFILES

HISTORY = "quality-history.jsonl"


def read(folder):
    """Every readable line of the run's history, oldest first."""
    try:
        text = (Path(folder) / HISTORY).read_text(encoding="utf-8")
    except OSError:
        return []
    out = []
    for line in text.splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            out.append(item)
    return out


def snapshots(folder):
    return [x["snapshot"] for x in read(folder) if isinstance(x.get("snapshot"), dict)]


def take(data, events):
    """What a score is made of, for diffing: qualities, blockers, claims, links and the ledger's tail."""
    project = data.get("project") if isinstance(data.get("project"), dict) else {}
    pillars = data.get("pillars") if isinstance(data.get("pillars"), dict) else {}
    profile = project.get("business_model") or "general"
    item = lambda p: pillars.get(p) if isinstance(pillars.get(p), dict) else {}
    claims = [c for c in data.get("claims") or [] if isinstance(c, dict) and isinstance(c.get("id"), str)]
    linked = {c["id"]: sorted(p for p in BASE if c["id"] in (item(p).get("claim_ids") or [])) for c in claims}
    return {
        "evaluation_id": data.get("evaluation_id"), "idea": project.get("idea"), "initial_customer": project.get("initial_customer"),
        "scores": {p: {"quality": item(p).get("quality"), "evidence": item(p).get("evidence")} for p in BASE},
        "assessed_at": {p: item(p).get("assessed_at") for p in BASE},
        "profile": profile,
        "weights": hashlib.sha256(json.dumps(PROFILES.get(profile, PROFILES["general"])["weights"], sort_keys=True).encode()).hexdigest()[:16],
        "events": len(events), "last_hash": events[-1].get("hash") if events else None,
        "blockers": {str(b.get("id")): {"status": b.get("status"), "fatal": b.get("fatal"), "resolved_by": b.get("resolved_by") or []}
                     for b in data.get("hard_blockers") or [] if isinstance(b, dict)},
        "claims": {c["id"]: {"classification": c.get("classification"), "linked": linked[c["id"]]} for c in claims},
        "claim_count": len(claims),
        "behaviors": {p: [b.get("ledger_event_id") for b in item(p).get("behaviors") or [] if isinstance(b, dict) and isinstance(b.get("ledger_event_id"), str)] for p in BASE},
        "pilot_gates": data.get("pilot_gates") if isinstance(data.get("pilot_gates"), dict) else {},
    }


def diff(old, new, at):
    """Changes from snapshot old to new, each a dict with kind and the values a reader needs."""
    out = []
    add = lambda kind, **kw: out.append({"at": at, "kind": kind, **kw})
    if old.get("evaluation_id") != new["evaluation_id"]:
        add("evaluation_id", old=old.get("evaluation_id"), new=new["evaluation_id"])
    if (old.get("idea"), old.get("initial_customer")) != (new["idea"], new["initial_customer"]):
        add("idea", old=old.get("idea"), new=new["idea"])
    if old.get("profile") != new["profile"]:
        add("profile", old=old.get("profile"), new=new["profile"])
    for p in BASE:
        q0, q1 = (old.get("scores") or {}).get(p, {}).get("quality"), new["scores"][p]["quality"]
        if q0 != q1:
            add("quality", pillar=p, old=q0, new=q1, assessed_before=bool((old.get("assessed_at") or {}).get(p)))
        a0, a1 = (old.get("assessed_at") or {}).get(p), new["assessed_at"][p]
        if a0 != a1:
            add("assessed_at", pillar=p, old=a0, new=a1)
        gone = [i for i in (old.get("behaviors") or {}).get(p, []) if i not in new["behaviors"][p]]
        if gone:
            add("behaviors_removed", pillar=p, ids=gone)
    ob, nb = old.get("blockers") or {}, new["blockers"]
    for i, b in nb.items():
        if i not in ob:
            add("blocker_added", id=i, status=b["status"], fatal=b["fatal"])
            continue
        for field in ("status", "fatal"):
            if ob[i].get(field) != b[field]:
                add("blocker", id=i, field=field, old=ob[i].get(field), new=b[field])
    for i, b in ob.items():
        if i not in nb:
            add("blocker_deleted", id=i, fatal=b.get("fatal"))
    oc, nc = old.get("claims") or {}, new["claims"]
    for i, c in oc.items():
        if i not in nc:
            add("claim_deleted", id=i)
            continue
        if c.get("classification") != nc[i]["classification"]:
            add("claim_reclassified", id=i, old=c.get("classification"), new=nc[i]["classification"])
        lost = [p for p in c.get("linked", []) if p not in nc[i]["linked"]]
        if lost:
            add("claim_unlinked", id=i, pillars=lost)
    if (old.get("pilot_gates") or {}) != new["pilot_gates"]:
        for g in sorted(set(old.get("pilot_gates") or {}) | set(new["pilot_gates"])):
            if (old.get("pilot_gates") or {}).get(g) != new["pilot_gates"].get(g):
                add("pilot_gate", gate=g)
    return out


def record(folder, data, events, origin=None):
    """Append this score's changes and snapshot; the first snapshot is diffed against the all-null quality baseline."""
    folder = Path(folder)
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    new = take(data, events)
    prior = snapshots(folder)
    base = prior[-1] if prior else {**new, "scores": {p: {"quality": None, "evidence": None} for p in BASE}, "assessed_at": dict.fromkeys(BASE)}
    changes = diff(base, new, now)
    with open(folder / HISTORY, "a", encoding="utf-8", opener=lambda p, fl: os.open(p, fl, 0o600)) as f:
        for c in changes:
            f.write(json.dumps({"at": now, "evaluation_id": new["evaluation_id"], "change": c}, ensure_ascii=False) + "\n")
        line = {"at": now, "evaluation_id": new["evaluation_id"], "snapshot": new, **({"origin": origin} if origin and not prior else {})}
        f.write(json.dumps(line, ensure_ascii=False) + "\n")
    return changes


def changes(folder):
    return [x["change"] for x in read(folder) if isinstance(x.get("change"), dict)]


def describe(log, facts):
    """The whole change log as lines. Quality changes the receipts support are summarized or cite the receipt."""
    out, low = [], 0
    counted, intact, gov = facts.get("counted", []), facts.get("intact", set()), facts.get("governing", {})
    for c in log:
        k = c.get("kind")
        if k == "quality":
            p, old, new = c["pillar"], c.get("old"), c.get("new")
            arrow = f"{p} quality {'unset' if old is None else old}→{'unset' if new is None else new}"
            if new is None:
                out.append(arrow)
                continue
            mine = [e for e in counted if p in e.get("pillar_ids", []) and gf_materials.kind_fits(e.get("kind"), p)]
            g = gov.get(p)
            covered = (not mine and new <= 3) or (g and g["id"] in intact and g.get("result") in ("pass", "mixed") and gf_materials.rubric(g) >= new)
            if covered and new <= 3:
                low += 1
            elif covered:
                out.append(f'{arrow} · {g["id"]} {g.get("material") or g["kind"]} {g["result"]}: "{g.get("outcome") or g.get("hypothesis")}"')
            elif not c.get("assessed_before") and (not mine or c["at"] < min(e["recorded_at"] for e in mine)):
                out.append(f"{arrow} set above what evidence supports (no receipt yet)")
            else:
                out.append(f"{arrow} changed by hand since {c['at'][:10]}")
        elif k == "evaluation_id":
            out.append(f"evaluation_id changed: {c.get('old')} → {c.get('new')}")
        elif k == "idea":
            out.append(f"idea changed: {c.get('old')!r} → {c.get('new')!r}")
        elif k == "profile":
            out.append(f"profile changed: {c.get('old')} → {c.get('new')}")
        elif k == "assessed_at":
            out.append(f"{c['pillar']} re-assessed at {c.get('new') or 'unset'}")
        elif k == "behaviors_removed":
            out.append(f"{c['pillar']}: {', '.join(c['ids'])} removed from behaviors[]")
        elif k == "blocker_added":
            out.append(f"blocker {c['id']} added ({c.get('status')}{', fatal' if c.get('fatal') else ''})")
        elif k == "blocker":
            out.append(f"blocker {c['id']} {c['field']} changed: {c.get('old')} → {c.get('new')}")
        elif k == "blocker_deleted":
            out.append(f"blocker {c['id']} was deleted" + (" (it was fatal)" if c.get("fatal") else ""))
        elif k == "claim_deleted":
            out.append(f"claim {c['id']} deleted")
        elif k == "claim_reclassified":
            out.append(f"claim {c['id']} reclassified: {c.get('old')} → {c.get('new')}")
        elif k == "claim_unlinked":
            out.append(f"claim {c['id']} unlinked from {', '.join(c['pillars'])}")
        elif k == "pilot_gate":
            out.append(f"pilot gate {c['gate']} edited")
    if low:
        out.insert(0, f"{low} findings set at quality ≤3")
    return out


def ledger_shortened(folder, events):
    """The ledger has no tail anchor, so compare it with every snapshot: fewer events, or a recorded hash gone."""
    hashes = {e.get("hash") for e in events}
    return any((s.get("events") or 0) > len(events) or (s.get("last_hash") and s["last_hash"] not in hashes) for s in snapshots(folder))


def blocker_problems(data, folder, review_map, intact):
    """A fatal blocker leaves only through `resolved` with resolved_by ids that are reviewed claims or verified receipts."""
    out = []
    now = {str(b.get("id")): b for b in data.get("hard_blockers") or [] if isinstance(b, dict)}
    ever_fatal = {i for s in snapshots(folder) if isinstance(s.get("blockers"), dict) for i, b in (s.get("blockers") or {}).items() if b.get("fatal")}
    for i, b in now.items():
        by = b.get("resolved_by") or []
        if not isinstance(by, list):
            out.append(f"hard_blockers {i}: resolved_by must be an array of claim or EV- ids")
            continue
        bad = [x for x in by if not isinstance(x, str) or not (x in intact or review_map.get(x) == "supported")]
        if bad:
            out.append(f"hard_blockers {i}: resolved_by {bad[0]!r} is not a reviewed claim or verified receipt in this run")
        if b.get("fatal") and b.get("status") == "resolved" and not by:
            out.append(f"hard_blockers {i}: a resolved fatal blocker needs resolved_by")
        if i in ever_fatal and not b.get("fatal") and not by:
            out.append(f"hard_blockers {i}: fatal changed to false without resolved_by")
    out += [f"blocker {i} was deleted: restore it and resolve it with resolved_by" for i in sorted(ever_fatal - set(now))]
    return out
