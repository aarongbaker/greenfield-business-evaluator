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
from gf_profiles import BASE, PROFILES
from gf_common import old_entry, GFError, VERSION, atomic_write, finite_nonneg, load_json, report, resolve_inside
from gf_ledger import UNCONFIRMED, verified_behavior, reviewed_claims

PILLAR_WEIGHTS = BASE
CORE = ("problem", "market", "value", "economics", "distribution")
CLASSIFICATIONS = {"fact", "estimate", "inference", "assumption"}
SEVERITIES = {"confirmed", "plausible", "resolved"}
SUPPORTED_SCHEMA = "2.0"
# The one verdict label table: scorer text, portfolio, dashboard and DECISION.md all read it.
VERDICTS = {
    "PROCEED_TO_BOUNDED_PILOT": {"label": "Proceed to bounded pilot", "tone": "good", "meaning": "Core gates met. Pilot only, not scale."},
    "VALIDATE_BEFORE_BUILD": {"label": "Validate before build", "tone": "warn", "meaning": "Run the next experiment before writing code."},
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


def validate(data, base_dir=None):
    errors, warnings = [], []
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
        if type(e) is int and e >= 3 and not any(isinstance(b, dict) and b.get("verified") is True and nonempty_str(b.get("source_or_artifact")) for b in behaviors):
            errors.append(f"pillars.{p}: evidence >=3 requires a verified documented observed behavior")
        if is_v2 and type(e) is int and e >= 3:
            ledger_name = data.get('evidence_ledger')
            if not path_str(ledger_name):
                errors.append(f"pillars.{p}: v2 evidence >=3 requires evidence_ledger path")
            elif ledger_path and not any(isinstance(b, dict) and nonempty_str(b.get('ledger_event_id')) and receipt_ok(b['ledger_event_id'], p) for b in behaviors):
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
            warnings.append('Could not validate source review ledger/report: '+type(exc).__name__)
        referenced = {cid for item in pillars.values() if isinstance(item,dict) and isinstance(item.get('claim_ids'),list) for cid in item['claim_ids'] if isinstance(cid,str)}
        for claim in claims:
            if isinstance(claim,dict) and claim.get('classification')=='fact' and claim.get('source_url') and member(claim.get('id'),referenced) and review_map.get(claim['id'])!='supported':
                warnings.append('Unreviewed public source claim: '+claim['id'])
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
                    elif not isinstance(evid,str) or review_map.get(evid)!='supported':
                        errors.append(f'pilot_gates.{gate}: claim {short(evid)} must have an intact human source review')
    return errors, warnings


def score(data, warnings):
    # Contract: only call after validate(data) returned no errors (main() and score_file() do).
    pillars = data["pillars"]
    qs = {p: pillars[p].get("quality") for p in PILLAR_WEIGHTS}  # missing quality == null
    ev = {p: pillars[p]["evidence"] for p in PILLAR_WEIGHTS}
    complete = all(v is not None for v in qs.values())
    profile_name = data.get('project', {}).get('business_model', 'general')
    profile = PROFILES.get(profile_name, PROFILES['general'])
    weights = profile['weights']
    total = round(sum(weights[p] * qs[p] / 5 for p in weights), 1) if complete else None
    avg_ev = round(sum(ev.values()) / 8, 2)
    blockers = data.get("hard_blockers", [])
    fatal = [b for b in blockers if b["status"] == "confirmed" and b["fatal"]]
    possible_fatal = [b for b in blockers if b["status"] == "plausible" and b["fatal"]]
    web = data["execution"]["web_used"]
    missing_gates = [gate for gate in profile['pilot_gates'] if not (isinstance(data.get('pilot_gates',{}).get(gate),dict)
                     and data['pilot_gates'][gate].get('passed') is True
                     and data['pilot_gates'][gate].get('evidence_ids'))]
    unconfirmed = any('ledger reattest' in w for w in warnings)
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
    elif total >= 75 and not possible_fatal and not missing_gates and not source_risk and not unconfirmed and all(qs[p] >= 3 and ev[p] >= 3 for p in CORE):
        decision = "PROCEED_TO_BOUNDED_PILOT"
        reason = "All five core pillars meet conservative attractiveness and evidence gates; pilot only, not scale."
    else:
        decision = "VALIDATE_BEFORE_BUILD"
        reason = "Proceed only with experiments targeted at the weakest decision-critical assumptions."
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
        "deprecated_fields": DEPRECATED_FIELDS,
        "disclaimer": "Heuristic triage, not a probability of commercial success or legal approval."
    }
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
    elif result["missing_core_behavior_evidence"]:
        thin = sorted(result["missing_core_behavior_evidence"], key=lambda p: ev[p])[:2]
        text = f"Evidence is thin on {names(thin)}: test {'these' if len(thin) > 1 else 'it'} before building"
    elif any(qs[p] < 3 for p in CORE):
        text = f"Quality is weak on {names(p for p in CORE if qs[p] < 3)}: fix the offer before a pilot"
    elif result["missing_pilot_gates"]:
        text = "Pilot gates unmet: " + ", ".join(result["missing_pilot_gates"])
    elif result["source_review_pending"]:
        text = "Public citations need a human source review before a pilot"
    elif any("ledger reattest" in w for w in result["warnings"]):
        text = "Ledger receipts are not confirmed on this machine: re-attest before a pilot"
    else:
        text = f"Weighted quality {result['weighted_quality_0_to_100']}/100 is below the 75 pilot bar"
    return clip(text, 90)


def next_step(result, data):
    """One imperative sentence: the single next thing to do for this verdict."""
    d, qs = result["decision"], result["quality_scores"]
    first = next(iter(data.get("experiments") or []), None)
    if d == "NO_GO":
        return f"Do not build; revisit only if new sourced evidence resolves blocker {result['confirmed_fatal_blockers'][0]}."
    if d == "RESEARCH_INCOMPLETE":
        todo = (["fill pillar quality scores"] if None in qs.values() else []) + \
               ([] if result["web_research_performed"] else ["run live web research"])
        return (" and ".join(todo) + ", then re-score.").capitalize()
    if d == "PIVOT":
        return "Reframe the idea around the weak core pillar and evaluate it as a new evaluation.json."
    if d == "PROCEED_TO_BOUNDED_PILOT":
        return "Run a bounded pilot against its pre-committed thresholds; do not scale yet."
    if isinstance(first, dict) and nonempty_str(first.get("hypothesis")):
        return clip(f"Run {first.get('id') or 'the first experiment'} ({first['hypothesis']}), "
                    "record the result with `greenfield ledger record`, then re-score.", 200)
    if result["unresolved_plausible_fatal_blockers"]:
        return f"Confirm or resolve blocker {result['unresolved_plausible_fatal_blockers'][0]} with sourced evidence, then re-score."
    if result["missing_core_behavior_evidence"]:
        p = min(result["missing_core_behavior_evidence"], key=lambda p: result["evidence_scores"][p])
        return f"Record a paid-test result for {p} with `greenfield ledger record`, then re-score."
    if result["missing_pilot_gates"]:
        return f"Link reviewed evidence to pilot gate {result['missing_pilot_gates'][0]}, then re-score."
    if result["source_review_pending"]:
        return "Run `greenfield sources check` on the cited sources and record a human source review, then re-score."
    return "Run the experiment that tests the weakest core pillar, then re-score."


def verdict_gap(result):
    """Unmet PROCEED_TO_BOUNDED_PILOT requirements, by the same rules as score(): dicts with key, text and, for pillar
    fields, pillar/field/current/needed. Empty when already proceeding; only the blockers when one is confirmed fatal."""
    if result["decision"] == "PROCEED_TO_BOUNDED_PILOT":
        return []
    if result["confirmed_fatal_blockers"]:
        return [{"key": f"blocker:{b}", "text": f"Resolve blocker {b}"} for b in result["confirmed_fatal_blockers"]]
    qs, ev, weights = result["quality_scores"], result["evidence_scores"], result["pillar_weights"]
    # Unassessed pillars count as 3 (the core floor); then raise the heaviest pillars until the 75 bar is met.
    need = {p: max(3 if p in CORE or qs[p] is None else 0, qs[p] or 0) for p in qs}
    while round(sum(weights[p] * need[p] / 5 for p in weights), 1) < 75:
        need[max((p for p in need if need[p] < 5), key=lambda p: (weights[p], -need[p]))] += 1
    item = lambda p, f, cur, n: {"key": f"{p}.{f}", "pillar": p, "field": f, "current": cur, "needed": n,
                                 "text": f"{p} {f} {'not assessed' if cur is None else cur} → {n}"}
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
        out.append({"key": "source_review", "text": f"review {n} source{'s' * (n != 1)}" if n else "verify sources and record a human review"})
    if any("ledger reattest" in w for w in result["warnings"]):
        out.append({"key": "reattest", "text": "re-attest ledger receipts on this machine"})
    return out


def gap_text(gap):
    """One line for the verdict gap, shared by the terminal summary and Mission Control: pillar fields grouped by target."""
    groups, rest = {}, []
    for i in gap:
        if "field" in i:
            groups.setdefault((i["field"], i["needed"]), []).append(i["pillar"])
        else:
            rest.append(i["text"])
    parts = [f"{f} {n}: {', '.join(ps)}" for (f, n), ps in sorted(groups.items(), key=lambda kv: (kv[0][0] != "quality", -kv[0][1]))]
    return "; ".join(parts + rest)


# (pattern with one name group, summary when it matches more than once)
COLLAPSE = (
    (r"pillars\.(\w+): no claims linked$", "{n} pillars have no linked claims: {names}"),
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
           line(result["headline"]), "",
           line(f"Weighted quality {f'{total:g}/100' if total is not None else g['dash'] + ' / 100 (incomplete)'}   "
                f"Evidence avg {result['evidence_average_0_to_5']:.1f}/5   "
                f"Fatal blockers {len(result['confirmed_fatal_blockers'])}"), "",
           line(f"{'Pillar':<14} {'Wt':>2}  {'Quality':<14}  {'Evidence':<12}Profile {result['business_model_profile']}")]
    for p, w in result["pillar_weights"].items():
        q, e = result["quality_scores"][p], result["evidence_scores"][p]
        out.append(f"{p:<14} {w:>2}  {(bar(q, glyphs) + f' {q}') if q is not None else g['dash'] + ' not assessed':<14}  {bar(e, glyphs)} {e}")
    raw = result["warnings"]
    items = list(raw) if all_warnings else summarize_warnings(raw)
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
    gap = verdict_gap(result)
    if gap:
        out += textwrap.wrap("To reach Proceed: " + gap_text(gap), width, subsequent_indent="  ")
    out += textwrap.wrap(clip("Next: " + result["next_step"], 400, g["more"]), width, subsequent_indent="      ")
    out.append("Heuristic triage, not a probability of commercial success.")
    text = "\n".join(out) + "\n"
    return text.encode("ascii", "replace").decode() if glyphs == "ascii" else text


def score_file(path):
    """Load, validate and score one evaluation: (result | None, errors, warnings). Bad input never raises."""
    path = pathlib.Path(path)
    try:
        data = load_json(path)
    except GFError as exc:
        return None, [str(exc)], []
    errors, warnings = validate(data, path.parent)
    if errors:
        return None, errors, warnings
    result = score(data, warnings)
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
