"""Score planner (W50): the fewest receipts that reach a target with Proceed, judged only by the scorer's own core.

The planner never writes quality. It assumes each planned receipt passes and that the founder's re-assessed findings
earn the qualities it lists; everything it cannot plan (blockers, re-attestation, re-assessment, source reviews) is a
manual step.
"""
from __future__ import annotations
import copy
import itertools
import json
from pathlib import Path

import gf_materials
from gf_materials import CORE, KIND_CEILING, MATERIALS
from gf_profiles import BASE, GATE_HELP, PROFILES

CATALOG = Path(__file__).resolve().parent.parent / "assets" / "experiment-catalog.json"
MAX_RECEIPTS = 10
ORDER = list(BASE)
_CACHE = []


def catalog():
    """Catalog entries with kind, ceiling, pillars and gates taken from the materials table, so the two cannot drift."""
    if not _CACHE:
        for e in json.loads(CATALOG.read_text(encoding="utf-8")):
            kind, ceil, pillars, gates = MATERIALS[e["as"]]
            _CACHE.append({**e, "kind": kind, "ceiling": min(KIND_CEILING[kind], ceil), "pillars": list(pillars), "gates": list(gates)})
    return _CACHE


def _cap(c):
    return min(5, c + 1)  # quality a passing receipt at evidence c supports (Decision 5)


def _total(weights, q):
    return round(sum(weights[p] * q[p] / 5 for p in weights), 1)


class _State:
    """Where the evaluation stands, read the way score() reads it."""

    def __init__(self, data, facts, profile):
        self.data, self.facts, self.profile = data, facts, profile
        self.weights = PROFILES[profile]["weights"]
        pillars = data["pillars"]
        self.qs = {p: pillars[p].get("quality") for p in self.weights}
        self.ev = {p: pillars[p]["evidence"] for p in self.weights}
        self.rubric = {p: facts.get("rubric", {}).get(p, 3) for p in self.weights}
        self.best = {p: facts.get("best", {}).get(p, 0) for p in self.weights}
        self.backed = facts.get("backed", {})
        gov, newest = facts.get("governing", {}), facts.get("newest", {})
        self.result = {p: (gov.get(p) or {}).get("result") for p in self.weights}
        self.rule = {}
        for p in self.weights:
            stamp = gf_materials._when(pillars[p].get("assessed_at") or "")
            after = stamp is not None and (newest.get(p) is None or stamp > gf_materials._when(newest[p]))
            if self.ev[p] >= 5 or (after and self.result[p] == "fail"):
                self.rule[p] = "none"  # finding-capped: nothing more to plan
            elif after and (self.result[p] == "mixed" or (self.qs[p] is not None and self.qs[p] < self.rubric[p])):
                self.rule[p] = "higher"  # one receipt of a higher ceiling at most
            else:
                self.rule[p] = "any"
        self.q0 = {p: min(self.qs[p], self.rubric[p]) for p in self.weights} if None not in self.qs.values() else None
        self.required = [p for p in CORE if self.ev[p] < 3 or not self.backed.get(p)]
        # A finding-capped pillar keeps its re-assessed quality unless a stronger receipt is planned on it.
        self.base = {p: self.rubric[p] if self.rule[p] == "any" or self.q0 is None else self.q0[p] for p in self.weights}

    def useful(self, p, c):
        if self.rule[p] == "none":
            return False
        return c > self.best[p] or (self.rule[p] == "any" and self.result[p] == "fail" and c >= self.best[p])

    def max_cap(self, p):
        caps = [_cap(e["ceiling"]) for e in catalog() if p in e["pillars"] and self.useful(p, e["ceiling"])]
        return max([self.base[p], *caps])

    def unraisable(self):
        return [p for p in self.weights if self.rule[p] == "none" or not any(p in e["pillars"] and self.useful(p, e["ceiling"]) for e in catalog())]


def _assign(ms, st):
    """Best pillar assignment for a multiset of entries under the per-file caps (Decision 1): {pillar: index} or None.

    Every entry must back at least one pillar (else a smaller multiset dominates) and every required core pillar
    needs a receipt. Maximizes the weighted quality headroom the receipts open."""
    w = st.weights
    order = [p for p in st.required] + sorted((p for p in w if p not in st.required), key=lambda p: -w[p])
    gain = {(p, j): w[p] * (max(st.base[p], _cap(e["ceiling"])) - st.base[p])
            for p in order for j, e in enumerate(ms) if p in e["pillars"] and st.useful(p, e["ceiling"])}
    if any(not any((p, j) in gain for j in range(len(ms))) for p in st.required):
        return None
    bound = [0] * (len(order) + 1)
    for i in range(len(order) - 1, -1, -1):
        bound[i] = bound[i + 1] + max([g for (p, _), g in gain.items() if p == order[i]] or [0])
    core_used, total_used, pick = [0] * len(ms), [0] * len(ms), {}
    best = [-1, None]

    def dfs(i, got):
        if got + bound[i] <= best[0]:
            return
        if i == len(order):
            if all(total_used):
                best[0], best[1] = got, dict(pick)
            return
        p, seen = order[i], set()
        for j, e in enumerate(ms):
            if (p, j) not in gain or total_used[j] >= 3 or (p in CORE and core_used[j] >= 2):
                continue
            key = (e["id"], core_used[j], total_used[j])
            if key in seen:
                continue
            seen.add(key)
            total_used[j] += 1
            core_used[j] += p in CORE
            pick[p] = j
            dfs(i + 1, got + gain[(p, j)])
            del pick[p]
            total_used[j] -= 1
            core_used[j] -= p in CORE
        if p not in st.required:
            dfs(i + 1, got)

    dfs(0, 0)
    return best[1]


def _qualities(st, caps, aim):
    """Spread one-notch raises, heaviest pillar first, until the aim is met; core pillars first reach 3."""
    q = dict(st.q0)
    for p in CORE:
        if q[p] < 3:
            if caps[p] < 3:
                return None
            q[p] = 3
    while _total(st.weights, q) < aim:
        moved = False
        for p in sorted(st.weights, key=lambda p: (-st.weights[p], q[p], ORDER.index(p))):
            if _total(st.weights, q) >= aim:
                break
            if q[p] < caps[p]:
                q[p] += 1
                moved = True
        if not moved:
            break
    return q


def _match_gates(steps, gates):
    """One gate per artifact (Decision 3): a maximum matching of open gates onto the route's receipts."""
    owner = {}

    def try_gate(g, seen):
        for i, s in enumerate(steps):
            if i in seen or g not in s["entry"]["gates"] or s["entry"]["kind"] not in GATE_HELP[g]["accepts"]:
                continue
            seen.add(i)
            if i not in owner or try_gate(owner[i], seen):
                owner[i] = g
                return True
        return False

    for g in gates:
        try_gate(g, set())
    return {g: i for i, g in owner.items()}


def _simulate(st, q, ev2, caps, planned):
    """Score the projected evaluation through the scorer's core: pillar qualities and evidence after the route."""
    import score_project
    sim = copy.deepcopy(st.data)
    sim["project"]["business_model"] = st.profile
    for p in st.weights:
        sim["pillars"][p]["quality"], sim["pillars"][p]["evidence"] = q[p], ev2[p]
    sim["pilot_gates"] = {g: {"passed": True, "evidence_ids": ["EV-planned"]} for g in PROFILES[st.profile]["pilot_gates"]}
    sim["hard_blockers"] = [b for b in sim.get("hard_blockers", []) if not (isinstance(b, dict) and b.get("status") == "plausible")]  # manual steps
    sim["verification_report"] = sim.get("verification_report") or "source-verification.json"  # manual step
    facts = {"rubric": caps, "backed": {p: bool(st.backed.get(p) or p in planned) for p in CORE}, "newest": {}}
    return score_project._total_and_decision(sim, facts, [])


def _routes(st, target, aim):
    entries = [e for e in catalog() if any(p in e["pillars"] and st.useful(p, e["ceiling"]) for p in st.weights)]
    # Best case first: every pillar at its highest plannable evidence. If even that cannot Proceed, no route can.
    best_ev = {p: max([st.ev[p], *(e["ceiling"] for e in entries if p in e["pillars"] and st.useful(p, e["ceiling"]))]) for p in st.weights}
    best_caps = {p: st.max_cap(p) for p in st.weights}
    q = _qualities(st, best_caps, aim)
    if q is None or _simulate(st, q, best_ev, best_caps, {p for p in CORE if best_ev[p] > st.ev[p]})["decision"] != "PROCEED_TO_BOUNDED_PILOT":
        return []
    found = []
    for k in range(0, MAX_RECEIPTS + 1):
        for ms in itertools.combinations_with_replacement(entries, k):
            if 2 * k < sum(p in st.required for p in CORE):
                continue
            pick = _assign(list(ms), st) if k else ({} if not st.required else None)
            if pick is None:
                continue
            caps, ev2 = dict(st.base), dict(st.ev)
            for p, j in pick.items():
                caps[p] = max(caps[p], _cap(ms[j]["ceiling"]))
                ev2[p] = max(ev2[p], ms[j]["ceiling"])
            if _total(st.weights, caps) < target:
                continue
            q = _qualities(st, caps, aim)
            if q is None:
                continue
            core = _simulate(st, q, ev2, caps, set(pick))
            if core["decision"] != "PROCEED_TO_BOUNDED_PILOT" or core["total"] < target:
                continue
            steps = [{"entry": e, "pillars": sorted((p for p, j in pick.items() if j == i), key=ORDER.index)} for i, e in enumerate(ms)]
            found.append({"steps": steps, "quality_targets": q, "evidence_after": ev2, "total": core["total"]})
        if any(r["total"] >= aim for r in found):
            break
    return found


def _experiment_ids(steps, data, facts):
    """Map each pillar step onto an unrun experiment that covers its pillars, else the lowest unused EXP-n."""
    rows = [x for x in data.get("experiments") or [] if isinstance(x, dict) and isinstance(x.get("id"), str)]
    run = {e.get("experiment_id") for e in facts.get("counted", [])}
    free = [x for x in rows if x["id"] not in run]
    taken = {x["id"] for x in rows}
    n = 1
    for s in steps:
        s["experiment_id"], s["new_experiment"] = None, False
        if not s["pillars"]:
            continue
        hit = next((x for x in free if set(s["pillars"]) <= set(gf_materials.exp_pillars(x))), None)
        if hit:
            free.remove(hit)
            s["experiment_id"], s["hypothesis"] = hit["id"], hit.get("hypothesis") or s["entry"]["title"]
            continue
        while f"EXP-{n}" in taken:
            n += 1
        taken.add(f"EXP-{n}")
        s["experiment_id"], s["new_experiment"], s["hypothesis"] = f"EXP-{n}", True, s["entry"]["title"]


def _commands(steps, slug):
    """The founder's commands for each step. A PII-likely or binary file always goes to raw/ first (W46)."""
    rel, names = f"research/greenfield/{slug}", {}
    for s in steps:
        e = s["entry"]
        stem, ext = Path(e["file"]).stem, Path(e["file"]).suffix
        names[stem] = names.get(stem, 0) + 1
        stem = stem if names[stem] == 1 else f"{stem}-{names[stem]}"
        binary = ext == ".pdf"
        if e["pii_likely"] or binary:
            s["bring"] = f"{rel}/materials/raw/{stem}{ext}"
            path = f"{rel}/materials/inbox/{stem}.redacted{ext}"
            s["redact"] = (f"redact by hand and save to {path}" if binary else
                           f"greenfield evidence redact {s['bring']} --drop-column email")
        else:
            s["bring"], s["redact"], path = f"{rel}/materials/inbox/{stem}{ext}", None, f"{rel}/materials/inbox/{stem}{ext}"
        s["command"] = " ".join([f"greenfield evidence add {path} --as {e['as']}", *(f"--pillar {p}" for p in s["pillars"]),
                                 *([f"--gate {s['gate']}"] if s.get("gate") else []), *([f"--experiment {s['experiment_id']}"] if s["experiment_id"] else []),
                                 f"--result <pass|fail> --consent {e['consent']} --attester \"<you>\"", *(["--redacted"] if binary else [])])


def _finish(route, st, gates, slug):
    steps = route["steps"]
    match = _match_gates(steps, gates)
    for g in gates:
        if g in match:
            steps[match[g]]["gate"] = g
        else:
            e = min((e for e in catalog() if g in e["gates"] and e["kind"] in GATE_HELP[g]["accepts"]), key=lambda e: (e["usd"], e["days"], bool(e["pillars"])))
            steps.append({"entry": e, "pillars": [], "gate": g})
    _experiment_ids(steps, st.data, st.facts)
    steps.sort(key=lambda s: (not s["pillars"], s["new_experiment"], -max([st.weights[p] for p in s["pillars"]] or [0])))
    _commands(steps, slug)
    route.update(receipts=len(steps), days=max([s["entry"]["days"] for s in steps] or [0]), usd=sum(s["entry"]["usd"] for s in steps))
    return route


def plan(data, facts=None, *, target=75, top=3, profile=None, slug=None, warnings=(), folder=None):
    """Routes to target with Proceed, best first, plus the manual steps no receipt can replace. Pure: writes nothing."""
    import score_project
    facts = facts or {}
    profile = profile or data.get("project", {}).get("business_model") or "general"
    st = _State(data, facts, profile)
    slug = slug or (Path(folder).name if folder else "<slug>")
    out = {"target": target, "profile": profile, "routes": [], "manual": _manual(data, facts, warnings, folder, profile), "unraisable": st.unraisable()}
    if st.q0 is None:
        out["manual"].insert(0, "fill every pillar's quality first")
        return out
    out["start_total"], out["start_qualities"] = _total(st.weights, st.q0), dict(st.q0)
    out["above_evidence"] = [{"pillar": p, "quality": st.qs[p], "evidence": st.ev[p], "rubric": st.rubric[p]} for p in st.weights if st.qs[p] > st.rubric[p]]
    if any(st.rule[p] == "none" for p in st.required):
        return out
    ceiling = _total(st.weights, {p: st.max_cap(p) for p in st.weights})
    if ceiling < target:
        return out
    aim = target + 1.0 if ceiling >= target + 1.0 else target
    pillar_gates = PROFILES[profile]["pilot_gates"]
    missing = [g for g in pillar_gates if not (isinstance((data.get("pilot_gates") or {}).get(g), dict) and data["pilot_gates"][g].get("passed") is True)]
    gates = [g for g in missing if g not in score_project.failed_gates(facts, missing)]
    routes = [_finish(r, st, gates, slug) for r in _routes(st, target, aim)]
    for r in routes:
        r["slack"] = round(r["total"] - target, 1)
    # a route whose tests are all in evaluation.json already is the one the founder chose (`plan --add-experiments --route N`)
    routes.sort(key=lambda r: (r["slack"] < 1.0, any(s["new_experiment"] for s in r["steps"]), r["receipts"], r["days"], r["usd"], -r["total"]))
    firsts = set()
    for r in routes:
        first = (r["steps"][0]["entry"]["id"], tuple(r["steps"][0]["pillars"]), r["steps"][0].get("gate")) if r["steps"] else None
        if first not in firsts:
            firsts.add(first)
            out["routes"].append(r)
        if len(out["routes"]) >= top:
            break
    return out


def _manual(data, facts, warnings, folder, profile):
    import score_project
    out = [f"confirm or resolve blocker {b.get('id')} with sourced evidence" for b in data.get("hard_blockers", [])
           if isinstance(b, dict) and b.get("status") == "plausible" and b.get("fatal")]
    if any("ledger reattest" in w for w in warnings):
        out.append("greenfield ledger reattest")
    missing = [g for g in PROFILES[profile]["pilot_gates"] if not (isinstance((data.get("pilot_gates") or {}).get(g), dict) and data["pilot_gates"][g].get("passed") is True)]
    out += [f"gate {g} failed: change the plan and retest, or reframe" for g in score_project.failed_gates(facts, missing)]
    claims = [c for c in data.get("claims") or [] if isinstance(c, dict)]
    report = Path(folder) / "source-verification.json" if folder else None
    if claims and (not data.get("verification_report") or (report is not None and not report.is_file())):
        url = any(c.get("classification") == "fact" and c.get("source_url") for c in claims)
        out.append("greenfield sources check" + (" --allow-network" if url else "") + "   (no source report yet; Proceed needs one)")
    elif claims and folder:
        try:
            out += [c["command"] for c in gf_materials._unreviewed(data, Path(folder), facts.get("events", []))]
        except (OSError, ValueError, KeyError, TypeError):
            pass
    return out


def choose(data, facts, warnings):
    """The shared chooser (W40/W50): the top route to 75 in cheap mode, or None. score() calls this once."""
    try:
        got = plan(data, facts, target=75, top=1, warnings=warnings)
    except (KeyError, TypeError, ValueError, AttributeError):  # validate() already passed; never let the planner break a score
        return None, []
    return (got["routes"][0] if got["routes"] else None), got["unraisable"]


def summary(route):
    """JSON-ready route without catalog internals."""
    if not route:
        return None
    return {"steps": [{"entry": s["entry"]["id"], "title": s["entry"]["title"], "as": s["entry"]["as"], "experiment_id": s["experiment_id"],
                       "new_experiment": s["new_experiment"], "pillars": s["pillars"], "gate": s.get("gate"),
                       "evidence_after": {p: route["evidence_after"][p] for p in s["pillars"]}, "bring": s["bring"], "redact": s["redact"],
                       "command": s["command"]} for s in route["steps"]],
            "quality_targets": route["quality_targets"], "total": route["total"], "receipts": route["receipts"], "days": route["days"], "usd": route["usd"]}


def add_experiments(ev_path, route):
    """Write the route's new experiments into evaluation.json (agent-safe: no attestation)."""
    from gf_common import load_json
    data = load_json(ev_path)
    rows = data.setdefault("experiments", [])
    have = {x.get("id") for x in rows if isinstance(x, dict)}
    added = []
    for s in route["steps"]:
        if s["new_experiment"] and s["experiment_id"] not in have:
            e = s["entry"]
            rows.append({"id": s["experiment_id"], "pillars": s["pillars"], "hypothesis": e["pass_hint"], "success_threshold": e["pass_hint"],
                         "method": e["title"], "status": "proposed"})
            added.append(s["experiment_id"])
    gf_materials._save(Path(ev_path), data)
    return added


def for_cli(ev_path, *, target=75, top=3, profile=None, add=False, route=1):
    """`greenfield plan`: validate and score the evaluation, plan from it, optionally write the new experiments."""
    import score_project
    from gf_common import GFError, load_json
    ev_path = Path(ev_path).resolve()
    data = load_json(ev_path)
    errors, warnings = score_project.validate(data, ev_path.parent)
    if errors:
        raise GFError(f"{len(errors)} problem(s) to fix before planning; first: {errors[0]}", path=ev_path, hint=f"greenfield score {ev_path}")
    facts = warnings.facts
    current = score_project.score(copy.deepcopy(data), warnings)
    out = plan(data, facts, target=target, top=max(top, route), profile=profile, warnings=current["warnings"], folder=ev_path.parent)
    if not 1 <= route <= max(1, len(out["routes"])):
        raise GFError(f"there is no route {route}: the plan has {len(out['routes'])}", path=ev_path, hint="greenfield plan")
    added = add_experiments(ev_path, out["routes"][route - 1]) if add and out["routes"] else []
    return {"current": {k: current[k] for k in ("decision", "verdict_label", "weighted_quality_0_to_100", "quality_scores", "evidence_scores")},
            **{k: v for k, v in out.items() if k != "routes"}, "routes": [summary(r) for r in out["routes"]], "added_experiments": added}


def render(out):
    """The plan as text, in the order a founder acts on it."""
    cur = out["current"]
    lines = [f"Now {cur['weighted_quality_0_to_100']} · {cur['verdict_label']} · core evidence "
             f"{sum(cur['evidence_scores'][p] >= 3 for p in CORE)}/5 at 3 or more"]
    if out.get("above_evidence"):
        lines.append("Findings above the evidence: " + ", ".join(f"{a['pillar']} {a['quality']} (rubric {a['rubric']})" for a in out["above_evidence"])
                     + f"; planned from {out['start_total']}")
    if not out["routes"]:
        lines.append(f"No route to {out['target']} with Proceed: the findings hold the score, or nothing left can be planned.")
    for n, r in enumerate(out["routes"]):
        if n:
            first = r["steps"][0] if r["steps"] else None
            lines.append(f"Alternative: {r['receipts']} receipts -> {r['total']}" + (f", starting with {first['as']} for {', '.join(first['pillars']) or first['gate']}" if first else ""))
            continue
        lines.append(f"Cheapest route to {out['target']} + Proceed: {r['receipts']} receipts, ~{max(1, round(r['days'] / 7))} weeks, ~${r['usd']} -> {r['total']}")
        for i, s in enumerate(r["steps"], 1):
            what = (", ".join(s["pillars"]) + f" evidence {max(s['evidence_after'].values())}") if s["pillars"] else f"gate {s['gate']}"
            if s["pillars"] and s["gate"]:
                what += f", gate {s['gate']}"
            exp = f"   ({s['experiment_id']}{', new' if s['new_experiment'] else ''})" if s["experiment_id"] else ""
            lines.append(f" {i}. {s['as']:<12}{s['title']} -> {what}{exp}")
            lines.append(f"    bring: {s['bring']}" + ("   (may hold personal data: keep it out of inbox/)" if "/raw/" in s["bring"] else ""))
            if s["redact"]:
                lines.append(f"    then:  {s['redact']}")
            lines.append(f"    then:  {s['command']}")
        if any(s["new_experiment"] for s in r["steps"]) and not out.get("added_experiments"):
            lines.append(" First: greenfield plan --add-experiments   (writes the new experiments into evaluation.json)")
        raised = [f"{p} {q}" for p, q in r["quality_targets"].items() if q != out["start_qualities"][p]]
        lines.append(" Then re-assess findings and stamp each pillar with greenfield evidence assessed <pillar>. The route assumes they reach: "
                     + (", ".join(raised) or "their current values"))
    if out.get("added_experiments"):
        lines.append(" Added to evaluation.json: " + ", ".join(out["added_experiments"]))
    lines += [f" Manual: {m}" for m in out["manual"]]
    lines.append("The planner assumes each receipt passes and that your re-assessed findings earn these qualities; it never writes quality.")
    return "\n".join(lines) + "\n"
