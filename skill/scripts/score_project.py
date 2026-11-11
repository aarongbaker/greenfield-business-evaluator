#!/usr/bin/env python3
"""Validate and score a greenfield evaluation. Standard library only.

This script validates STRUCTURE, not factual truth, provenance, URLs' contents,
or the predictive merit of the score. Source and experiment audits remain essential.
"""

import argparse
import datetime as dt
import json
import os
import pathlib
import re
import sys
import textwrap
from urllib.parse import urlparse
from gf_profiles import BASE, GATE_HELP, PROFILES
from gf_common import old_entry, GFError, VERSION, atomic_write, finite_nonneg, load_json, report, resolve_inside
from gf_ledger import UNCONFIRMED, verified_behavior, reviewed_claims
import gf_history
import gf_ledger
import gf_materials

PILLAR_WEIGHTS = BASE
CORE = ("problem", "market", "value", "economics", "distribution")
# What each pillar asks, in a founder's words, for instructions.
PLAIN = {"problem": "the problem is real", "market": "enough buyers exist", "value": "people want your solution",
         "economics": "people will pay enough", "distribution": "you can reach buyers affordably",
         "competition": "you can beat the alternatives", "execution": "you can deliver it", "timing": "the timing is right"}
ASK = {"problem": "Is the problem real?", "market": "Do enough buyers exist?", "value": "Do people want your solution?",
       "economics": "Will people pay enough?", "distribution": "Can you reach buyers affordably?",
       "competition": "Can you beat the alternatives?", "execution": "Can you deliver it?", "timing": "Is the timing right?"}
CLASSIFICATIONS = {"fact", "estimate", "inference", "assumption"}
SEVERITIES = {"confirmed", "plausible", "resolved"}
SUPPORTED_SCHEMA = "2.0"
# The one verdict label table: scorer text, portfolio, dashboard and DECISION.md all read it.
VERDICTS = {
    "PROCEED_TO_BOUNDED_PILOT": {"label": "Proceed to bounded pilot", "tone": "good", "meaning": "Core gates met. Pilot only, not scale."},
    "VALIDATE_BEFORE_BUILD": {"label": "Validate before build", "tone": "warn", "meaning": "Test with real customers before writing code; stop or reframe if tested findings stay below the bar."},
    "PIVOT": {"label": "Pivot", "tone": "warn", "meaning": "Evidence shows a severe core weakness."},
    "NO_GO": {"label": "No go", "tone": "bad", "meaning": "A confirmed fatal blocker overrides the score."},
    "RESEARCH_INCOMPLETE": {"label": "Research incomplete", "tone": "neutral", "meaning": "Not a launch decision yet."},
    # Not a scorer decision: for callers showing an evaluation that failed validation.
    "INVALID": {"label": "Can't score", "tone": "bad", "meaning": "evaluation.json has input errors."},
}
DEPRECATED_FIELDS = ["memo_label", "source_review_gate_open"]  # kept populated through 2.x, removed in 3.0


def is_iso_date(v):
    try:
        if not isinstance(v, str):
            return False
        return dt.date.fromisoformat(v).isoformat() == v
    except ValueError:
        return False


def has_http_url(v):
    if not isinstance(v, str) or not v:
        return False
    try:
        p = urlparse(v)
    except ValueError:  # e.g. "http://[" is an invalid IPv6 URL
        return False
    return p.scheme in ("http", "https") and bool(p.netloc)


def nonempty_str(v):
    return isinstance(v, str) and bool(v.strip())


def path_str(v):
    return nonempty_str(v) and "\x00" not in v


def member(value, allowed):
    """Membership test that never raises on unhashable data (lists, dicts)."""
    return isinstance(value, str) and value in allowed


def short(v, limit=120):
    r = repr(v)
    return r if len(r) <= limit else r[:limit - 3] + "..."


def nonneg_ok(v):
    try:
        finite_nonneg(v, "value")
        return True
    except GFError:
        return False


class Warnings(list):
    """validate() warnings, carrying the ledger facts to score() so the evaluation dict is never touched."""
    facts = {}


def validate(data, base_dir=None):
    errors, warnings = [], Warnings()
    if not isinstance(data, dict):
        return ["Evaluation must be a JSON object"], []
    version = data.get("schema_version")
    if version != SUPPORTED_SCHEMA:
        errors.append(f"schema_version must be {SUPPORTED_SCHEMA!r} (got {short(version)}); "
                      "migrate older evaluations per README before scoring")
    # Always apply the strict (v2) receipt and source-review checks, so an
    # absent or wrong version can never switch them off.
    is_v2 = True
    base_dir = pathlib.Path(base_dir or ".").resolve()
    # Resolve data paths once, confined to the evaluation folder; every later use reads these two variables.
    paths = {}
    for key in ('evidence_ledger', 'verification_report'):
        if path_str(data.get(key)):
            try:
                paths[key] = resolve_inside(base_dir, data[key])
            except GFError as exc:
                errors.append(f'{key} must stay inside the evaluation folder: {exc}')
    ledger_path, report_path = paths.get('evidence_ledger'), paths.get('verification_report')
    for key, name in (('evidence_ledger', 'experiment-ledger.jsonl'), ('verification_report', 'source-verification.json')):
        if path_str(data.get(key)) and data[key] != name:
            errors.append(f'{key} must be {name} in the evaluation folder')
    facts = gf_materials.analyze(data, ledger_path, base_dir) if ledger_path else gf_materials.analyze(data, base_dir / 'experiment-ledger.jsonl', base_dir)
    warnings.facts = facts
    warnings.extend(facts['warnings'])
    signed_for = lambda p: any(p in x['pillar_ids'] for x in facts['signed'])

    def receipt_ok(evid, pillar=None):
        if not ledger_path:
            return False
        ok, why = verified_behavior(ledger_path, evid, pillar)
        if ok and 'absolute path' in why:
            warnings.append(f'Receipt {evid}: {why}')
        if not ok and why.startswith(UNCONFIRMED):
            warnings.append(f"Receipt {evid} not confirmed on this machine ({why}); re-confirm with "
                            f"`greenfield ledger reattest --ledger {data['evidence_ledger']}` or set GF_ATTEST_KEY_FILE to the signing key")
            return True  # structurally fine; score() withholds the pilot verdict while this warning stands
        return ok

    project = data.get("project")
    if not isinstance(project, dict) or not all(nonempty_str(project.get(k)) for k in ("name", "idea", "initial_customer", "geography", "business_type", "goal")):
        errors.append("project requires nonempty name, idea, initial_customer, geography, business_type, goal")
    profile = (project or {}).get('business_model', 'general') if isinstance(project, dict) else 'general'
    if not member(profile, PROFILES):
        errors.append('project.business_model must be one of: ' + ', '.join(sorted(PROFILES)))
        profile = 'general'
    if is_v2 and not isinstance(data.get('pilot_gates', {}), dict):
        errors.append('pilot_gates must be an object')
    if data.get("as_of") == "":  # the template's "not started" marker (W24): incomplete, not invalid
        warnings.append("Not started: set as_of to today's date and replace any REPLACE_ project fields")
    elif not is_iso_date(data.get("as_of")):
        errors.append("as_of must be an ISO YYYY-MM-DD date")
    left = sorted(k for k, v in (project if isinstance(project, dict) else {}).items() if isinstance(v, str) and v.startswith("REPLACE_"))
    if left and data.get("as_of") != "":
        warnings.append("project." + ", project.".join(left) + " still hold REPLACE_ placeholders: fill them in")
    execution = data.get("execution")
    if not isinstance(execution, dict):
        errors.append("execution must be an object")
        execution = {}
    if type(execution.get("web_used")) is not bool:
        errors.append("execution.web_used must be a boolean")
    if type(execution.get("customer_validation_performed")) is not bool:
        errors.append("execution.customer_validation_performed must be a boolean")
    if type(execution.get("subagents_actual")) is not int or execution["subagents_actual"] < 0:
        errors.append("execution.subagents_actual must be a nonnegative integer")
    if not nonempty_str(execution.get("mode")):
        errors.append("execution.mode must be nonempty")
    pillars = data.get("pillars")
    if not isinstance(pillars, dict):
        errors.append("pillars must be an object")
        pillars = {}
    missing = set(PILLAR_WEIGHTS) - set(pillars)
    extra = set(pillars) - set(PILLAR_WEIGHTS)
    if missing:
        errors.append("missing pillars: " + ", ".join(sorted(missing)))
    if extra:
        errors.append("unknown pillars: " + ", ".join(sorted(extra)))
    claims = data.get("claims")
    if not isinstance(claims, list):
        errors.append("claims must be an array")
        claims = []
    claim_ids = set()
    claim_by_id = {}
    for idx, claim in enumerate(claims):
        path = f"claims[{idx}]"
        if not isinstance(claim, dict):
            errors.append(path + " must be an object")
            continue
        cid = claim.get("id")
        if not nonempty_str(cid) or cid in claim_ids:
            errors.append(path + ".id must be a unique nonempty string")
        else:
            claim_ids.add(cid)
            claim_by_id[cid] = claim
        if not member(claim.get("pillar"), PILLAR_WEIGHTS):
            errors.append(path + ".pillar must be one of: " + ", ".join(sorted(PILLAR_WEIGHTS)))
        kind = claim.get("classification")
        if not member(kind, CLASSIFICATIONS):
            errors.append(path + ".classification must be one of: " + ", ".join(sorted(CLASSIFICATIONS)))
        if not nonempty_str(claim.get("statement")):
            errors.append(path + ".statement missing")
        source_url = claim.get("source_url", "")
        artifact = claim.get("artifact_path", "")
        if kind == "fact" and not (has_http_url(source_url) or nonempty_str(artifact)):
            errors.append(path + ": facts require source_url or artifact_path")
        if source_url and not has_http_url(source_url):
            errors.append(path + ".source_url must be an HTTP(S) URL")
        if kind == "fact" and nonempty_str(artifact) and not any(
                x['artifact']['path'] == artifact and x['id'] in facts['intact'] and claim.get('pillar') in x['pillar_ids'] for x in facts['counted']):
            errors.append(f"{path}: artifact_path {short(artifact)} has no attested receipt for {short(claim.get('pillar'))}: run greenfield evidence add")
        if kind == "estimate" and not nonempty_str(claim.get("notes")):
            warnings.append(path + ": estimate has no documented formula in notes")
        if kind == "assumption" and source_url:
            warnings.append(path + ": assumption has a URL; clarify if source supports a fact or just context")
        if source_url and not nonempty_str(claim.get("accessed_date")):
            warnings.append(path + ": source has no access date")
    for p in PILLAR_WEIGHTS:
        item = pillars.get(p)
        if not isinstance(item, dict):
            errors.append(f"pillars.{p} must be an object")
            continue
        q, e = item.get("quality"), item.get("evidence")
        if q is not None and (type(q) is not int or not 0 <= q <= 5):
            errors.append(f"pillars.{p}.quality must be null or an integer from 0–5")
        if type(e) is not int or not 0 <= e <= 5:
            errors.append(f"pillars.{p}.evidence must be an integer from 0–5")
        if not nonempty_str(item.get("finding")):
            errors.append(f"pillars.{p}.finding is required")
        ids = item.get("claim_ids", [])
        if not isinstance(ids, list):
            errors.append(f"pillars.{p}.claim_ids must be an array")
            ids = []
        for cid in ids:
            if not member(cid, claim_ids):
                errors.append(f"pillars.{p} refers to unknown claim {short(cid)}")
        behaviors = item.get("behaviors", [])
        if not isinstance(behaviors, list):
            errors.append(f"pillars.{p}.behaviors must be an array")
            behaviors = []
        for j, behavior in enumerate(behaviors):
            if not isinstance(behavior, dict) or not all(nonempty_str(behavior.get(k)) for k in ("kind", "description", "observed_at", "source_or_artifact")):
                errors.append(f"pillars.{p}.behaviors[{j}] must include kind, description, observed_at, source_or_artifact")
        if nonempty_str(item.get("assessed_at")) and gf_materials.assessed_problem(item["assessed_at"]):
            errors.append(f"pillars.{p}.assessed_at {gf_materials.assessed_problem(item['assessed_at'])}: run greenfield evidence assessed {p}")
        if type(q) is int and q > facts['rubric'][p]:  # the total counts it at the rubric level
            warnings.append(f"pillars.{p}: quality {q} is above what evidence {e} supports ({facts['rubric'][p]})")
        by_id = {x['id']: x for x in facts['events']}
        for b in behaviors:
            if isinstance(b, dict) and b.get('ledger_event_id') is not None and not isinstance(b['ledger_event_id'], str):
                errors.append(f'pillars.{p}: ledger_event_id must be a string')
            linked = by_id.get(b.get('ledger_event_id')) if isinstance(b, dict) and isinstance(b.get('ledger_event_id'), str) else None
            if not linked or linked.get('kind') not in gf_materials.KIND_CEILING:
                continue
            if not gf_materials.kind_fits(linked['kind'], p):
                errors.append(f"pillars.{p}: {linked['id']} is {linked['kind']}, which cannot back {p}")
            if linked.get('material') in gf_materials.MATERIALS and p not in gf_materials.MATERIALS[linked['material']][2]:
                errors.append(f"pillars.{p}: {linked['id']} is {linked['material']}, which cannot back {p}")
            if b.get('kind') != linked['kind']:
                errors.append(f"pillars.{p}.behaviors kind is {short(b.get('kind'))} but {linked['id']} was recorded as {linked['kind']}")
        if type(e) is int and e >= 3 and signed_for(p) and e > facts['best'][p]:
            errors.append(f"pillars.{p}: evidence {e} is above what its receipts support ({facts['best'][p]})")
        if type(e) is int and e >= 3 and not signed_for(p) and not any(isinstance(b, dict) and b.get("verified") is True and nonempty_str(b.get("source_or_artifact")) for b in behaviors):
            errors.append(f"pillars.{p}: evidence >=3 requires a verified documented observed behavior")
        if is_v2 and type(e) is int and e >= 3:
            ledger_name = data.get('evidence_ledger')
            if not path_str(ledger_name):
                errors.append(f"pillars.{p}: v2 evidence >=3 requires evidence_ledger path")
            elif ledger_path and not any(isinstance(b, dict) and nonempty_str(b.get('ledger_event_id')) and receipt_ok(b['ledger_event_id'], p) for b in behaviors):
                if signed_for(p):  # the signed result still counts; it just cannot support Proceed
                    warnings.append(f"pillars.{p}: its receipt is unlinked or its file changed, so it cannot support a pilot")
                else:
                    errors.append(f"pillars.{p}: evidence >=3 must reference an intact human-attested behavioral ledger receipt for this pillar")
        if type(e) is int and e >= 3 and not execution.get("customer_validation_performed") and p in ("problem", "value", "distribution", "economics"):
            warnings.append(f"pillars.{p}: strong claimed behavior but customer_validation_performed=false; investigate")
        if not ids:
            warnings.append(f"pillars.{p}: no claims linked")
    blockers = data.get("hard_blockers", [])
    if not isinstance(blockers, list):
        errors.append("hard_blockers must be an array")
        blockers = []
    for i, blocker in enumerate(blockers):
        path = f"hard_blockers[{i}]"
        if not isinstance(blocker, dict) or not member(blocker.get("status"), SEVERITIES) or type(blocker.get("fatal")) is not bool or not nonempty_str(blocker.get("finding")):
            errors.append(path + " requires status (" + ", ".join(sorted(SEVERITIES)) + "), fatal boolean, and finding")
            continue
        ids = blocker.get("source_ids", [])
        if not isinstance(ids, list):
            errors.append(path + ".source_ids must be an array")
            continue
        for cid in ids:
            if not member(cid, claim_ids):
                errors.append(path + f": unknown claim {short(cid)}")
        if blocker.get("fatal") and blocker.get("status") == "confirmed":
            sourced = [claim_by_id[cid] for cid in ids if member(cid, claim_by_id)]
            if not ids:
                errors.append(path + ": confirmed fatal blocker requires documented source IDs")
            elif not any(c.get("classification") == "fact" and (has_http_url(c.get("source_url")) or nonempty_str(c.get("artifact_path"))) for c in sourced):
                errors.append(path + ": confirmed fatal blocker requires at least one directly sourced factual claim")
    experiments = data.get("experiments", [])
    if not isinstance(experiments, list):
        errors.append("experiments must be an array")
    model = data.get("market_model", {})
    if model is not None and not isinstance(model, dict):
        errors.append("market_model must be an object if present")
    elif isinstance(model, dict):
        for name in ("tam", "sam", "som"):
            entry = model.get(name)
            if not isinstance(entry, dict):
                continue
            vals = [entry.get(k) for k in ("low", "base", "high")]
            if all(v is not None for v in vals):
                if not all(nonneg_ok(v) for v in vals):
                    errors.append(f"market_model.{name} range must be nonnegative finite numbers")
                elif not vals[0] <= vals[1] <= vals[2]:
                    errors.append(f"market_model.{name}: require low <= base <= high")
    if is_v2 and isinstance(data.get('pilot_gates', {}), dict):
        for gate in PROFILES[profile]['pilot_gates']:
            entry = data['pilot_gates'].get(gate)
            if entry is not None and (not isinstance(entry,dict) or type(entry.get('passed')) is not bool or not isinstance(entry.get('evidence_ids', []), list)):
                errors.append('pilot_gates.'+gate+' needs passed boolean and evidence_ids array')
    for key in ('evidence_ledger', 'verification_report'):
        if data.get(key) not in (None, '') and not path_str(data.get(key)):
            errors.append(f'{key} must be a relative path string (got {short(data.get(key))})')
    review_map = {}
    if is_v2 and report_path and ledger_path:
        try:
            review_map = reviewed_claims(ledger_path,report_path)
        # Malformed report/ledger FILE contents only; evaluation data is checked outside this try.
        except (ValueError, OSError, TypeError, KeyError, AttributeError) as exc:
            msg = str(exc).replace(str(base_dir) + os.sep, '') if base_dir else str(exc)  # relative: keeps output machine-independent
            nxt = f'; next: {exc.hint}' if getattr(exc, 'hint', None) else ''
            warnings.append(f'Could not validate source review ledger/report: {msg or type(exc).__name__}{nxt}')
        referenced = {cid for item in pillars.values() if isinstance(item,dict) and isinstance(item.get('claim_ids'),list) for cid in item['claim_ids'] if isinstance(cid,str)}
        for claim in claims:
            if isinstance(claim,dict) and claim.get('classification')=='fact' and claim.get('source_url') and member(claim.get('id'),referenced) and review_map.get(claim['id'])!='supported':
                warnings.append('Unreviewed public source claim: '+claim['id'])
    closed = {}
    if is_v2 and isinstance(data.get('pilot_gates',{}),dict):
        for gate in PROFILES[profile]['pilot_gates']:
            entry=data.get('pilot_gates',{}).get(gate)
            if isinstance(entry,dict) and entry.get('passed') is True:
                evidence_ids = entry.get('evidence_ids',[])
                if not isinstance(evidence_ids, list):
                    continue  # already reported above
                if not evidence_ids:
                    errors.append(f'pilot_gates.{gate}: passed gate requires linked evidence identifiers')
                for evid in evidence_ids:
                    if isinstance(evid,str) and evid.startswith('EV-'):
                        if not receipt_ok(evid):
                            errors.append(f'pilot_gates.{gate}: behavioral ledger receipt invalid {short(evid)}')
                        else:
                            errors.extend(f'pilot_gates.{gate}: {m}' for m in gate_receipt_problems(evid, gate, facts, closed))
                    elif not isinstance(evid,str) or review_map.get(evid)!='supported':
                        errors.append(f'pilot_gates.{gate}: claim {short(evid)} must have an intact human source review')
                    else:
                        if 'claim' not in GATE_HELP[gate]['accepts']:
                            errors.append(f'pilot_gates.{gate}: accepts no claim; link a receipt')
                        elif not gf_materials.claim_closes_gate(claim_by_id.get(evid, {}), gate, facts['events']):
                            errors.append(f'pilot_gates.{gate}: claim {evid} needs a current source review naming {gate}')
                        if evid in closed:
                            errors.append(f'pilot_gates.{gate}: {evid} already closes {closed[evid]}: one id closes one gate')
                        closed[evid] = gate
    errors.extend(gf_materials.reuse_errors(facts['counted']))
    anchor, own = facts['anchor'], data.get('evaluation_id')
    has_signed = any(x.get('sig') for x in facts['events'])
    if anchor and own and anchor != own:
        errors.append(f"evaluation_id {short(own)} differs from the ledger's {anchor}")
    elif not own and has_signed:
        errors.append('evaluation_id is missing: run greenfield evidence init')
    elif not own:
        warnings.append('evaluation_id is missing: run greenfield evidence init')
    if isinstance(data.get('hard_blockers'), list):
        errors.extend(gf_history.blocker_problems(data, base_dir, review_map, facts['intact']))
    facts['shortened'] = gf_history.ledger_shortened(base_dir, facts['events'])
    if facts['shortened']:
        warnings.append('experiment ledger was shortened: restore it from backup; no pilot verdict until it is whole')
    linked_ids = {b.get('ledger_event_id') for item in pillars.values() if isinstance(item, dict) and isinstance(item.get('behaviors'), list) for b in item['behaviors'] if isinstance(b, dict) and isinstance(b.get('ledger_event_id'), str)}
    for x in facts['counted']:
        for p in x['pillar_ids']:
            if x['id'] not in linked_ids and gf_materials.kind_fits(x['kind'], p):
                warnings.append(f"Ledger receipt {x['id']} for {p} is not linked from evaluation.json")
    return errors, warnings


def gate_receipt_problems(evid, gate, facts, closed):
    """Why this receipt cannot close this gate (Decision 3), and record that it closes it."""
    event = next((x for x in facts['counted'] if x['id'] == evid), None)
    if event is None:
        return [f'{evid} does not belong to this evaluation']
    out = []
    if event['kind'] not in GATE_HELP[gate]['accepts']:
        out.append(f"does not accept {event['kind']}")
    if event.get('material') in gf_materials.MATERIALS and gate not in gf_materials.MATERIALS[event['material']][3]:
        out.append(f"{event['material']} cannot close it")
    if event.get('gate_ids') and gate not in event['gate_ids']:
        out.append(f'{evid} was recorded for {", ".join(event["gate_ids"])}')
    if event.get('result') != 'pass':
        out.append(f"{evid} came back {event.get('result') or 'with no result'}: it cannot close {gate}")
    for other, other_gate in closed.items():
        if other_gate == gate:
            continue
        prior = next((x for x in facts['counted'] if x['id'] == other), None)
        if other == evid or (prior and gf_materials._same_artifact(prior, event)):
            out.append(f'{evid} already closes {other_gate}: one file closes one gate')
    closed[evid] = gate
    return out


def proceed_problems(data, qs, facts):
    """Unmet receipt rules for Proceed (W42), as gap items; empty when every quality is backed."""
    rubric, backed, newest = facts.get('rubric', {}), facts.get('backed', {}), facts.get('newest', {})
    out = []
    for p, q in qs.items():
        level = rubric.get(p, 3)
        if q is not None and q > level:
            text = f"{p} quality {q} has no receipt" if newest.get(p) is None else f"{p} quality {q} is above its rubric level {level}"
            out.append({"key": f"rubric:{p}", "text": text})
        if q is not None and (p in CORE or q > 3) and newest.get(p):
            when = gf_materials._when((data['pillars'][p].get('assessed_at') or ''))
            if when is None or when <= gf_materials._when(newest[p]):
                out.append({"key": f"assess:{p}", "pillar": p, "text": f"re-assess {p}"})
    for p in CORE:
        if not backed.get(p) and data['pillars'][p]['evidence'] >= 3:
            out.append({"key": f"backed:{p}", "text": f"{p} needs an intact passing or mixed receipt"})
    return out


def failed_core(facts):
    """Core pillars whose governing receipt, at evidence 3 or more, came back fail (W41)."""
    gov = facts.get('governing', {})
    return [p for p in CORE if p in gov and gov[p].get('result') == 'fail' and gf_materials.ceiling(gov[p]) >= 3]


def failed_gates(facts, missing):
    """Open gates whose newest receipt naming them came back fail (W41)."""
    out = []
    for gate in missing:
        named = [x for x in facts.get('signed', []) if gate in (x.get('gate_ids') or [])]
        if named and max(named, key=lambda x: x['recorded_at']).get('result') == 'fail':
            out.append(gate)
    return out


def next_experiment(route):
    """The top planner route's first step (W40/W50), or None."""
    if not route or not route["steps"]:
        return None
    s = route["steps"][0]
    return {"id": s["experiment_id"], "new": s["new_experiment"], "entry": s["as"], "title": s["title"], "pillars": s["pillars"],
            "pillar": (s["pillars"] or [None])[0], "gate": s["gate"], "hypothesis": s.get("hypothesis") or s["title"]}


def findings_cap(result):
    """W41: evidence is in, nothing else is outstanding, and no planner route reaches 75: the findings hold the score."""
    qs, total = result["quality_scores"], result["weighted_quality_0_to_100"]
    return (result["decision"] == "VALIDATE_BEFORE_BUILD" and result["route"] is None and not result["missing_core_behavior_evidence"]
            and not _to_assess(result) and not result["missing_pilot_gates"] and not result["source_review_pending"]
            and not result["unresolved_plausible_fatal_blockers"] and not any("ledger reattest" in w for w in result["warnings"])
            and not result["injected_events"] and not result["ledger_shortened"]
            and (total < 75 or any(qs[p] < 3 for p in CORE)))


def _total_and_decision(data, facts, warnings):
    """The pure scoring core: total, verdict and the Proceed checks. The planner (W50) evaluates routes only through this."""
    pillars = data["pillars"]
    qs = {p: pillars[p].get("quality") for p in PILLAR_WEIGHTS}  # missing quality == null
    ev = {p: pillars[p]["evidence"] for p in PILLAR_WEIGHTS}
    complete = all(v is not None for v in qs.values())
    profile_name = data.get('project', {}).get('business_model', 'general')
    profile = PROFILES.get(profile_name, PROFILES['general'])
    weights = profile['weights']
    cap = facts.get('rubric', {})  # only proven points count: research alone tops out at 3 of 5 per pillar
    total = round(sum(weights[p] * min(qs[p], cap.get(p, 3)) / 5 for p in weights), 1) if complete else None
    avg_ev = round(sum(ev.values()) / 8, 2)
    blockers = data.get("hard_blockers", [])
    fatal = [b for b in blockers if b["status"] == "confirmed" and b["fatal"]]
    possible_fatal = [b for b in blockers if b["status"] == "plausible" and b["fatal"]]
    web = data["execution"]["web_used"]
    missing_gates = [gate for gate in profile['pilot_gates'] if not (isinstance(data.get('pilot_gates',{}).get(gate),dict)
                     and data['pilot_gates'][gate].get('passed') is True
                     and data['pilot_gates'][gate].get('evidence_ids'))]
    unconfirmed = any('ledger reattest' in w or w.startswith('Legacy receipt') for w in warnings) or bool(facts.get('injected')) or bool(facts.get('shortened'))
    receipt_gaps = proceed_problems(data, qs, facts) if complete else []
    source_risk = bool(data.get('claims') and
                       (not data.get('verification_report') or any('Unreviewed public source claim' in w or 'Could not validate source review ledger/report' in w for w in warnings)))
    if fatal:
        decision = "NO_GO"
        reason = "A sourced, confirmed, unresolved fatal blocker overrides the score."
    elif not web or not complete or not data["as_of"] or any(isinstance(v, str) and v.startswith("REPLACE_") for v in data["project"].values()):
        decision = "RESEARCH_INCOMPLETE"
        reason = "Live research or necessary pillar assessments are missing; do not treat this as a launch decision."
    elif total < 50 and any(qs[p] <= 1 and ev[p] >= 3 for p in CORE):
        decision = "PIVOT"
        reason = "Low weighted attractiveness plus behavior-backed evidence of a severe core weakness."
    elif total >= 75 and not possible_fatal and not missing_gates and not source_risk and not unconfirmed and not receipt_gaps and all(qs[p] >= 3 and ev[p] >= 3 for p in CORE):
        decision = "PROCEED_TO_BOUNDED_PILOT"
        reason = "All five core pillars meet conservative attractiveness and evidence gates; pilot only, not scale."
    else:
        decision = "VALIDATE_BEFORE_BUILD"
        reason = "Proceed only with experiments targeted at the weakest decision-critical assumptions."
    return {'qs': qs, 'ev': ev, 'complete': complete, 'profile_name': profile_name, 'weights': weights, 'total': total, 'avg_ev': avg_ev,
            'fatal': fatal, 'possible_fatal': possible_fatal, 'web': web, 'missing_gates': missing_gates, 'unconfirmed': unconfirmed,
            'receipt_gaps': receipt_gaps, 'source_risk': source_risk, 'decision': decision, 'reason': reason}


def score(data, warnings):
    facts = getattr(warnings, 'facts', {})
    # Contract: only call after validate(data) returned no errors (main() and score_file() do).
    c = _total_and_decision(data, facts, warnings)
    qs, ev, complete, profile_name, weights, total, avg_ev = c['qs'], c['ev'], c['complete'], c['profile_name'], c['weights'], c['total'], c['avg_ev']
    fatal, possible_fatal, web, missing_gates, receipt_gaps = c['fatal'], c['possible_fatal'], c['web'], c['missing_gates'], c['receipt_gaps']
    source_risk, decision, reason = c['source_risk'], c['decision'], c['reason']
    gaps = [p for p in CORE if qs[p] is None or ev[p] < 3]
    if missing_gates:
        warnings.append('Unmet business-model pilot gates: '+', '.join(missing_gates))
    if source_risk:
        warnings.append('Public citations need source report and human source review before pilot approval')
    if data["execution"].get("subagents_actual", 0) == 0:
        warnings.append("No actual subagents recorded: use 'single-agent fallback', not 'parallel fan-out'")
    if not web:
        warnings.append("No live web research performed; prices, market sizes and competitor landscape unverified")
    result = {
        "schema_version": "2.0",
        "business_model_profile": profile_name,
        "missing_pilot_gates": missing_gates,
        "source_review_gate_open": not source_risk,  # deprecated: reads true when no review is pending
        "source_review_pending": source_risk,
        "as_of": data["as_of"],
        "project": data["project"]["name"],
        "decision": decision,
        "verdict_label": VERDICTS[decision]["label"],
        "memo_label": "VALIDATE_BEFORE_BUILD (research incomplete)" if decision == "RESEARCH_INCOMPLETE" else decision,
        "reason": reason,
        "weighted_quality_0_to_100": total,
        "evidence_average_0_to_5": avg_ev,
        "pillar_weights": weights,
        "quality_scores": qs,
        "evidence_scores": ev,
        "missing_core_behavior_evidence": gaps,
        "confirmed_fatal_blockers": [b.get("id", "unspecified") for b in fatal],
        "unresolved_plausible_fatal_blockers": [b.get("id", "unspecified") for b in possible_fatal],
        "web_research_performed": web,
        "subagents_actual": data["execution"]["subagents_actual"],
        "warnings": sorted(set(warnings)),
        "receipt_gaps": receipt_gaps,
        "failed_core": failed_core(facts),
        "failed_gates": failed_gates(facts, missing_gates),
        "injected_events": list(facts.get('injected', [])),
        "ledger_shortened": bool(facts.get('shortened')),
        "deprecated_fields": DEPRECATED_FIELDS,
        "disclaimer": "Heuristic triage, not a probability of commercial success or legal approval."
    }
    route, unraisable = None, []
    if decision == "VALIDATE_BEFORE_BUILD":
        import gf_plan  # inside the function: gf_plan imports this module
        route, unraisable = gf_plan.choose(data, facts, result["warnings"])
        route = gf_plan.summary(route)
    result["route"] = route
    result["next_experiment"] = next_experiment(route)
    result["findings_cap"] = findings_cap(result)
    result["gap"] = _verdict_gap(result, unraisable)
    result["headline"] = headline(result, data)
    result["next_step"] = next_step(result, data)
    return result


def clip(text, limit, ellipsis="…"):
    """One printable line of at most limit characters (code points, so no surrogate is split)."""
    text = re.sub(r"[\x00-\x08\x0e-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]", "", re.sub(r"[\t\n\x0b\x0c\r]+", " ", str(text))).rstrip()
    return text if len(text) <= limit else text[:limit - len(ellipsis)].rstrip() + ellipsis


def names(items):
    items = list(items)
    return " and ".join(items) if len(items) < 3 else ", ".join(items[:-1]) + " and " + items[-1]


def headline(result, data):
    """At most 90 characters saying why this verdict, built from the result by rule, never model-written."""
    d, qs, ev = result["decision"], result["quality_scores"], result["evidence_scores"]
    if d == "NO_GO":
        b = next(b for b in data["hard_blockers"] if b["status"] == "confirmed" and b["fatal"])
        text = f"Fatal blocker confirmed: {b.get('id', 'unspecified')} {b['finding']}"
    elif d == "RESEARCH_INCOMPLETE":
        missing = sum(q is None for q in qs.values())
        parts = ([f"{missing} of {len(qs)} pillars unassessed"] if missing else []) + \
                ([] if result["web_research_performed"] else ["no live web research"])
        text = "Research incomplete: " + ", ".join(parts)
    elif d == "PIVOT":
        weak = [p for p in CORE if qs[p] <= 1 and ev[p] >= 3]
        text = f"Behavior-backed evidence shows a severe weakness in {names(weak)}: rethink before building"
    elif d == "PROCEED_TO_BOUNDED_PILOT":
        text = "All five core pillars clear the evidence gates: run a bounded pilot"
    elif result["unresolved_plausible_fatal_blockers"]:
        text = "Plausible fatal blocker unresolved: " + ", ".join(result["unresolved_plausible_fatal_blockers"])
    elif result["failed_core"]:
        text = f"A tested core assumption failed on {names(result['failed_core'])}: stop or reframe"
    elif result["failed_gates"]:
        text = f"{result['failed_gates'][0]} came back fail: change the plan and retest it, or stop or reframe"
    elif result["missing_core_behavior_evidence"]:
        thin = sorted(result["missing_core_behavior_evidence"], key=lambda p: ev[p])
        # naming two of five equally untested pillars would single them out for no reason
        text = (f"No customer test yet on {'any' if len(thin) == len(CORE) else len(thin)} of the {len(CORE)} core questions: test them before building" if len(thin) > 2
                else f"Evidence is thin on {names(thin)}: test {'these' if len(thin) > 1 else 'it'} before building")
    elif any("ledger reattest" in w for w in result["warnings"]):
        text = "Ledger receipts are not confirmed on this machine: re-attest before a pilot"
    elif any(w.startswith("Legacy receipt") for w in result["warnings"]):
        text = "Older receipts have no evaluation binding: re-record them before a pilot"
    elif result["ledger_shortened"]:
        text = "The experiment ledger was shortened: restore it before a pilot"
    elif result["injected_events"]:
        text = "Some receipts were confirmed by code, not at a terminal: re-record them before a pilot"
    elif _to_assess(result):
        text = "Re-assess findings from your new receipts, then re-score"
    elif result.get("findings_cap"):
        low = [p for p in CORE if qs[p] < 3]
        total = result["weighted_quality_0_to_100"]
        text = (f"Evidence is in and findings hold quality at {total}/100, below the 75 bar: stop or reframe" if total < 75
                else f"Evidence is in and quality on {names(low)} is below 3: stop or reframe")
    elif any(qs[p] < 3 for p in CORE):
        text = f"Quality is weak on {names(p for p in CORE if qs[p] < 3)}: fix the offer before a pilot"
    elif result["missing_pilot_gates"]:
        text = "Pilot gates unmet: " + ", ".join(result["missing_pilot_gates"])
    elif result["source_review_pending"]:
        text = "Public citations need a human source review before a pilot"
    elif result["receipt_gaps"]:
        text = "Quality runs ahead of the receipts: " + result["receipt_gaps"][0]["text"]
    else:
        text = f"Weighted quality {result['weighted_quality_0_to_100']}/100 is below the 75 pilot bar"
    return clip(text, 90)


def _to_assess(result):
    return [g["pillar"] for g in result.get("receipt_gaps", []) if g["key"].startswith("assess:")]


STOP_STEP = 'Your experiments ran and the findings stay below the bar; stop, or reframe with greenfield start --new --idea "<new framing>".'


def plain(pillars):
    """'whether the problem is real and enough buyers exist' for a list of pillars."""
    return "whether " + names(PLAIN.get(p, p) for p in pillars)


def _experiment_step(nxt, demo=False):
    target = f"see {plain(nxt['pillars'])}" if nxt["pillars"] else f"close gate {nxt['gate']}"
    record = "record the result, pass or fail, with `greenfield evidence add`."
    if not nxt["id"]:
        return f"Record your {nxt['entry']} file to {target}: {record}"
    if nxt["new"] and demo:  # the bundled demo is read-only
        return f"Run the {nxt['title'].lower()} test to {target}: `greenfield plan` lists every step. This is sample data, so nothing is saved."
    if nxt["new"]:
        return f"Run the {nxt['title'].lower()} test to {target}: add it with `greenfield plan --add-experiments`, then {record}"
    long_form = f"Run your experiment \"{nxt['hypothesis']}\" to {target}, then {record}"
    return long_form if len(long_form) <= 200 else f"Run your next planned experiment to {target}, then {record}"


def next_step(result, data):
    """One imperative sentence: the single next thing to do for this verdict."""
    d, qs = result["decision"], result["quality_scores"]
    if d == "NO_GO":
        return f"Do not build; revisit only if new sourced evidence resolves blocker {result['confirmed_fatal_blockers'][0]}."
    if d == "RESEARCH_INCOMPLETE":
        return "Ask your assistant to finish the research, then run `greenfield score`."
    if d == "PIVOT":
        return "Reframe the idea around its weakest core pillar and start a new run with `greenfield start --new --idea '<new framing>'`."
    if d == "PROCEED_TO_BOUNDED_PILOT":
        return "Run a bounded pilot against its pre-committed thresholds; do not scale yet."
    if result["unresolved_plausible_fatal_blockers"]:
        return f"Investigate blocker {result['unresolved_plausible_fatal_blockers'][0]}: find a source that confirms or rules it out, then run `greenfield score`."
    if result["failed_core"]:
        return STOP_STEP
    if result["failed_gates"]:
        return f"{result['failed_gates'][0]} came back fail: change the plan and retest it, or stop or reframe."
    nxt = result.get("next_experiment")
    if result["missing_core_behavior_evidence"]:
        if nxt:
            return _experiment_step(nxt, data.get('evaluation_id') in gf_materials.RESERVED_IDS)
        p = min(result["missing_core_behavior_evidence"], key=lambda p: result["evidence_scores"][p])
        return f"Test {p} with real customers, then record the result, pass or fail, with `greenfield evidence add`."
    if any("ledger reattest" in w for w in result["warnings"]):
        return "Re-confirm your receipts with `greenfield ledger reattest`, then re-score."
    if any(w.startswith("Legacy receipt") for w in result["warnings"]):
        return "Re-record older receipts with `greenfield evidence add`, then re-score."
    if result["ledger_shortened"]:
        return "Restore experiment-ledger.jsonl from your backup, then re-score."
    if result["injected_events"]:
        return f"Re-record {', '.join(result['injected_events'])} at a terminal with `greenfield evidence add`, then re-score."
    if _to_assess(result):
        return f"Ask your assistant to re-assess {names(_to_assess(result))} from your new receipts and stamp them with `greenfield evidence assessed {' '.join(_to_assess(result))}`."
    if nxt:
        return _experiment_step(nxt, data.get('evaluation_id') in gf_materials.RESERVED_IDS)
    if result.get("findings_cap"):
        return STOP_STEP
    if result["missing_pilot_gates"]:
        return f"Close pilot gate {result['missing_pilot_gates'][0]}: record a passing receipt for it with `greenfield evidence add --gate {result['missing_pilot_gates'][0]}`."
    if result["source_review_pending"]:
        return "Check that the web pages your research cites say what it claims: run `greenfield sources check --allow-network`, then `greenfield evidence status`."
    return "Run `greenfield plan` and start its first experiment."


def verdict_gap(result):
    """Unmet PROCEED_TO_BOUNDED_PILOT requirements, as score() stored them (W50); recomputed for an older decision.json."""
    return result["gap"] if "gap" in result else _verdict_gap(result)


def _verdict_gap(result, unraisable=()):
    """Unmet PROCEED_TO_BOUNDED_PILOT requirements, by the same rules as score(): dicts with key, text and, for pillar
    fields, pillar/field/current/needed and by_experiment. Empty when already proceeding; only the blockers when one is confirmed fatal."""
    if result["decision"] == "PROCEED_TO_BOUNDED_PILOT":
        return []
    if result["confirmed_fatal_blockers"]:
        return [{"key": f"blocker:{b}", "text": f"Resolve blocker {b}"} for b in result["confirmed_fatal_blockers"]]
    qs, ev, weights = result["quality_scores"], result["evidence_scores"], result["pillar_weights"]
    # Unassessed pillars count as 3 (the core floor); then raise the heaviest pillars until the 75 bar is met.
    need = {p: max(3 if p in CORE or qs[p] is None else 0, qs[p] or 0) for p in qs}
    while round(sum(weights[p] * need[p] / 5 for p in weights), 1) < 75:
        need[max((p for p in need if need[p] < 5), key=lambda p: (weights[p], -need[p]))] += 1
    def item(p, f, cur, n):
        out = {"key": f"{p}.{f}", "pillar": p, "field": f, "current": cur, "needed": n, "text": f"{p} {f} {'not assessed' if cur is None else cur} → {n}"}
        if f == "quality" and cur is not None:  # W49: quality is a finding, so the gap is an investigation
            out["text"] = f"{p} quality would need to reach {n} (now {cur}): only new research evidence cited in {p} can change it"
            out["by_experiment"] = p not in unraisable
        return out
    out = [item(p, "quality", None, need[p]) for p in qs if qs[p] is None]
    if not result["as_of"] or result["project"].startswith("REPLACE_"):
        out.append({"key": "started", "text": "start the evaluation"})
    if not result["web_research_performed"]:
        out.append({"key": "web", "text": "run live web research"})
    out += [item(p, "quality", qs[p], need[p]) for p in qs if qs[p] is not None and need[p] > qs[p]]
    out += [item(p, "evidence", ev[p], 3) for p in CORE if ev[p] < 3]
    out += [{"key": f"blocker:{b}", "text": f"Resolve blocker {b}"} for b in result["unresolved_plausible_fatal_blockers"]]
    out += [{"key": f"gate:{g}", "text": f"close gate {g}"} for g in result["missing_pilot_gates"]]
    if result["source_review_pending"]:
        n = sum(w.startswith("Unreviewed public source claim") for w in result["warnings"])
        out.append({"key": "source_review", "text": f"review {n} source{'s' * (n != 1)}" if n else "a human review of the sources"})
    if any("ledger reattest" in w for w in result["warnings"]):
        out.append({"key": "reattest", "text": "re-attest ledger receipts on this machine"})
    return out + result.get("receipt_gaps", [])


def gap_text(gap):
    """One line for the verdict gap, shared by the terminal summary and Mission Control: pillar fields grouped by target."""
    groups, rest = {}, []
    for i in gap:
        if "field" in i:
            groups.setdefault((i["field"], i["needed"], i.get("by_experiment", True)), []).append(i["pillar"])
        else:
            rest.append(i["text"])
    parts = [f"{f} {n}: {', '.join(ps)}" + ("" if by else " (not reachable by another experiment)")
             for (f, n, by), ps in sorted(groups.items(), key=lambda kv: (kv[0][0] != "quality", -kv[0][1], not kv[0][2]))]
    return "; ".join(parts + rest)


# (pattern with one name group, summary when it matches more than once)
COLLAPSE = (
    (r"pillars\.(\w+): no claims linked$", "{n} pillars have no linked claims: {names}"),
    (r"pillars\.(\w+): quality \d is above what evidence", "{n} pillars have quality above what their evidence supports: {names}"),
    (r"pillars\.(\w+): strong claimed behavior", "{n} pillars claim strong behavior without customer validation: {names}"),
    (r"(claims\[\d+\]): source has no access date$", "{n} sources have no access date: {names}"),
    (r"(claims\[\d+\]): estimate has no documented formula", "{n} estimates have no formula in notes: {names}"),
    (r"(claims\[\d+\]): assumption has a URL", "{n} assumptions cite a URL: {names}"),
    (r"Unreviewed public source claim: (.+)$", "{n} public source claims need human review: {names}"),
    (r"Receipt (\S+) not confirmed on this machine", "{n} ledger receipts not confirmed on this machine: {names}"),
)
RANK = (("blocker", 0), ("pilot gate", 1), ("source", 2), ("citation", 2), ("receipt", 2),
        ("research", 3), ("linked claims", 3), ("subagents", 3), ("customer validation", 3))


def summarize_warnings(warnings):
    """Collapse repeated warnings by pattern and order them: blockers, pilot gates, sources, research gaps, the rest."""
    groups, out = {}, []
    for w in dict.fromkeys(warnings):
        for pattern, summary in COLLAPSE:
            m = re.match(pattern, w)
            if m:
                if summary not in groups:
                    groups[summary] = []
                    out.append(summary)
                groups[summary].append((m.group(1), w))
                break
        else:
            out.append(w)
    lines = [(groups[x][0][1] if len(groups[x]) == 1 else x.format(n=len(groups[x]), names=", ".join(n for n, _ in groups[x])))
             if x in groups else x for x in out]
    return sorted(lines, key=lambda w: next((r for k, r in RANK if k in w.lower()), 4))


GLYPHS = {"unicode": {"dot": "●", "full": "█", "empty": "░", "sep": "·", "item": "•", "dash": "—", "more": "…"},
          "ascii": {"dot": "*", "full": "#", "empty": ".", "sep": "-", "item": "-", "dash": "-", "more": "..."}}
TONES = {"good": "32", "warn": "33", "bad": "31", "neutral": "2"}


def bar(value, glyphs="unicode", total=5):
    g = GLYPHS[glyphs]
    return g["full"] * value + g["empty"] * (total - value)


def render_text(result, *, color, width=80, glyphs="unicode", all_warnings=False):
    """The one-screen summary a person sees on a terminal. Pure: same result, same text."""
    g = GLYPHS[glyphs]
    line = lambda text: clip(text, width, g["more"])
    verdict = VERDICTS.get(result["decision"], {"label": result["decision"], "tone": "neutral"})
    badge = f"{g['dot']} {verdict['label'].upper()}"
    title = clip(f"{result['project']} {g['sep']} as of {result['as_of'] or 'not started'}", max(10, width - len(badge) - 3), g["more"])
    if color:
        badge = f"\033[1;{TONES[verdict['tone']]}m{badge}\033[0m"
    total = result["weighted_quality_0_to_100"]
    out = [badge + "   " + title,
           line(result["headline"]),
           line(f"Weighted quality {f'{total:g}/100' if total is not None else g['dash'] + ' / 100 (incomplete)'}   "
                f"Evidence avg {result['evidence_average_0_to_5']:.1f}/5   "
                f"Fatal blockers {len(result['confirmed_fatal_blockers'])}"), "",
           line(f"{'Pillar':<14} {'Wt':>2}  {'Quality':<14}  {'Evidence':<12}Profile {result['business_model_profile']}")]
    for p, w in result["pillar_weights"].items():
        q, e = result["quality_scores"][p], result["evidence_scores"][p]
        out.append(f"{p:<14} {w:>2}  {(bar(q, glyphs) + f' {q}') if q is not None else g['dash'] + ' not assessed':<14}  {bar(e, glyphs)} {e}")
    raw = result["warnings"]
    items = list(raw) if all_warnings else summarize_warnings(raw)
    gap = verdict_gap(result)
    if gap and not all_warnings:  # the title already says "not started" and the gap line says "start the evaluation"
        items = [w for w in items if not w.startswith("Not started:")]
    blockers = result["unresolved_plausible_fatal_blockers"]
    if blockers and not all_warnings:
        items.insert(0, "Plausible fatal blocker unresolved: " + ", ".join(blockers))
    if items:
        shown = items if all_warnings else items[:5]
        note = "" if len(shown) == len(items) else f" (top 5 shown; --all-warnings for every one)"
        out += ["", f"! {len(raw)} warning{'s' * (len(raw) != 1)}{note}"]
        out += [line(f"  {g['item']} {w}") for w in shown]
        if len(items) > len(shown):
            out.append(f"  +{len(items) - len(shown)} more")
    if gap:
        out += textwrap.wrap("To reach Proceed: " + gap_text(gap), width, subsequent_indent="  ")
    out += textwrap.wrap(clip("Next: " + result["next_step"], 400, g["more"]), width, subsequent_indent="      ")
    out.append("Heuristic triage, not a probability of commercial success.")
    text = "\n".join(out) + "\n"
    return text.encode("ascii", "replace").decode() if glyphs == "ascii" else text


def score_file(path):
    """Load, validate and score one evaluation: (result | None, errors, warnings). Bad input never raises."""
    return _score_trusted(path, allow_injected=False)


def _score_trusted(path, *, allow_injected):
    """score_file, optionally counting confirm_via: injected events as confirmed. Private: tests and the pinned demo only (W49)."""
    path = pathlib.Path(path)
    try:
        data = load_json(path)
    except GFError as exc:
        return None, [str(exc)], []
    with gf_ledger.demo_scope(path.parent) as demo:  # W52: only the pinned demo folder counts its script-signed events
        errors, warnings = validate(data, path.parent)
        if errors:
            return None, errors, warnings
        if (allow_injected or demo) and warnings.facts.get('injected'):
            warnings.facts['injected'] = []
            warnings[:] = [w for w in warnings if 'confirm_via: injected' not in w]
        result = score(data, warnings)
    if demo:
        result["demo"] = True
    return result, [], result["warnings"]


def recompute_decision(eval_path, project_root):
    """score_file() for an evaluation confined to project_root: (result | None, errors, warnings). Never raises on bad input."""
    try:
        path = resolve_inside(project_root, eval_path, must_exist=True)
    except GFError as exc:
        return None, [str(exc)], []
    return score_file(path)


def run(args):
    result, errors, _ = score_file(args.evaluation)
    if errors:
        for err in errors:
            print("ERROR: " + err, file=sys.stderr)
        print(f"  next: fix the field(s) above and re-run `greenfield score {args.evaluation}`", file=sys.stderr)
        return 2
    body = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    text = sys.stdout.isatty() and not args.json
    if args.output:
        try:
            args.output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            atomic_write(args.output, body, mode=0o600)
        except OSError as exc:
            return report(GFError(f"cannot write decision: {exc.strerror or exc}", path=args.output, hint="choose a writable --output path"))
    if text:
        color = not args.no_color and not os.environ.get("NO_COLOR") and os.environ.get("TERM") != "dumb"
        try:
            "●█░·•—…".encode(sys.stdout.encoding or "ascii")
            glyphs = "unicode"
        except (UnicodeEncodeError, LookupError):
            glyphs = "ascii"
        print(render_text(result, color=color, glyphs=glyphs, all_warnings=args.all_warnings), end="")
        if args.output:
            print(f"Saved decision.json to {args.output}")
        return 0
    if not args.output:
        print(body, end="")
    for warning in result["warnings"]:
        print("WARNING: " + warning, file=sys.stderr)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    parser.add_argument("evaluation", type=pathlib.Path, help="Input evaluation.json")
    parser.add_argument("--output", type=pathlib.Path, help="Write decision JSON here (default: stdout)")
    parser.add_argument("--json", action="store_true", help="Print decision JSON even on a terminal (agents: always pass this)")
    parser.add_argument("--all-warnings", action="store_true", help="Text mode: list every warning instead of the top 5 groups")
    parser.add_argument("--no-color", action="store_true", help="Text mode: no colour (also off with NO_COLOR or TERM=dumb)")
    args = parser.parse_args(argv)
    try:
        return run(args)
    except Exception as exc:  # never a traceback, never a verdict after an unexpected error
        print(f"ERROR: internal validator error ({type(exc).__name__}: {str(exc)[:120]}). No decision was written. "
              "Please report this with your evaluation.json.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(old_entry(main, "score_project.py", "greenfield score"))
