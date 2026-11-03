#!/usr/bin/env python3
"""Validate and score a greenfield evaluation. Standard library only.

This script validates STRUCTURE, not factual truth, provenance, URLs' contents,
or the predictive merit of the score. Source and experiment audits remain essential.
"""

import argparse
import datetime as dt
import json
import math
import pathlib
import re
import sys
from urllib.parse import urlparse
from gf_profiles import BASE, PROFILES
from gf_ledger import verified_behavior, reviewed_claims

PILLAR_WEIGHTS = BASE
CORE = ("problem", "market", "value", "economics", "distribution")
CLASSIFICATIONS = {"fact", "estimate", "inference", "assumption"}
SEVERITIES = {"confirmed", "plausible", "resolved"}
SUPPORTED_SCHEMA = "2.0"


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
    p = urlparse(v)
    return p.scheme in ("http", "https") and bool(p.netloc)


def nonempty_str(v):
    return isinstance(v, str) and bool(v.strip())


def validate(data, base_dir=None):
    errors, warnings = [], []
    if not isinstance(data, dict):
        return ["Evaluation must be a JSON object"], []
    version = data.get("schema_version")
    if version != SUPPORTED_SCHEMA:
        errors.append(f"schema_version must be {SUPPORTED_SCHEMA!r} (got {version!r}); "
                      "migrate older evaluations per README before scoring")
    # Always apply the strict (v2) receipt and source-review checks, so an
    # absent or wrong version can never switch them off.
    is_v2 = True
    base_dir = pathlib.Path(base_dir or ".").resolve()
    project = data.get("project")
    if not isinstance(project, dict) or not all(nonempty_str(project.get(k)) for k in ("name", "idea", "initial_customer", "geography", "business_type", "goal")):
        errors.append("project requires nonempty name, idea, initial_customer, geography, business_type, goal")
    profile = (project or {}).get('business_model', 'general') if isinstance(project, dict) else 'general'
    if profile not in PROFILES:
        errors.append('project.business_model must be one of ' + ', '.join(sorted(PROFILES)))
        profile = 'general'
    if is_v2 and not isinstance(data.get('pilot_gates', {}), dict):
        errors.append('pilot_gates must be an object')
    if not is_iso_date(data.get("as_of")):
        errors.append("as_of must be an ISO YYYY-MM-DD date")
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
        if claim.get("pillar") not in PILLAR_WEIGHTS:
            errors.append(path + ".pillar invalid")
        kind = claim.get("classification")
        if kind not in CLASSIFICATIONS:
            errors.append(path + ".classification invalid")
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
            if cid not in claim_ids:
                errors.append(f"pillars.{p} refers to unknown claim {cid!r}")
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
            if not nonempty_str(ledger_name):
                errors.append(f"pillars.{p}: v2 evidence >=3 requires evidence_ledger path")
            else:
                ledger_path = (base_dir / ledger_name).resolve()
                if not ledger_path.is_relative_to(base_dir):
                    errors.append('evidence_ledger must remain inside the evaluation directory')
                elif not any(isinstance(b, dict) and nonempty_str(b.get('ledger_event_id')) and verified_behavior(ledger_path, b['ledger_event_id'], p)[0] for b in behaviors):
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
        if not isinstance(blocker, dict) or blocker.get("status") not in SEVERITIES or type(blocker.get("fatal")) is not bool or not nonempty_str(blocker.get("finding")):
            errors.append(path + " requires status, fatal, and finding")
            continue
        ids = blocker.get("source_ids", [])
        if not isinstance(ids, list):
            errors.append(path + ".source_ids must be an array")
            continue
        for cid in ids:
            if cid not in claim_ids:
                errors.append(path + f": unknown claim {cid!r}")
        if blocker.get("fatal") and blocker.get("status") == "confirmed":
            if not ids:
                errors.append(path + ": confirmed fatal blocker requires documented source IDs")
            elif not any(claim_by_id.get(cid, {}).get("classification") == "fact" and (has_http_url(claim_by_id.get(cid, {}).get("source_url")) or nonempty_str(claim_by_id.get(cid, {}).get("artifact_path"))) for cid in ids):
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
                if any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in vals):
                    errors.append(f"market_model.{name} range must be nonnegative finite numbers")
                elif not vals[0] <= vals[1] <= vals[2]:
                    errors.append(f"market_model.{name}: require low <= base <= high")
    if is_v2 and isinstance(data.get('pilot_gates', {}), dict):
        for gate in PROFILES[profile]['pilot_gates']:
            entry = data['pilot_gates'].get(gate)
            if entry is not None and (not isinstance(entry,dict) or type(entry.get('passed')) is not bool or not isinstance(entry.get('evidence_ids', []), list)):
                errors.append('pilot_gates.'+gate+' needs passed boolean and evidence_ids array')
    review_map = {}
    if is_v2 and data.get('verification_report') and data.get('evidence_ledger'):
        try:
            report_path = (base_dir / data['verification_report']).resolve()
            ledger_path = (base_dir / data['evidence_ledger']).resolve()
            if not report_path.is_relative_to(base_dir) or not ledger_path.is_relative_to(base_dir):
                errors.append('verification_report and evidence_ledger must remain inside evaluation directory')
            else:
                reviews = reviewed_claims(ledger_path,report_path)
                review_map = reviews
                referenced = {cid for item in pillars.values() if isinstance(item,dict) for cid in item.get('claim_ids',[])}
                for claim in claims:
                    if claim.get('classification')=='fact' and claim.get('source_url') and claim.get('id') in referenced and reviews.get(claim.get('id'))!='supported':
                        warnings.append('Unreviewed public source claim: '+str(claim.get('id')))
        except (ValueError, OSError, TypeError, KeyError) as exc:
            warnings.append('Could not validate source review ledger/report: '+type(exc).__name__)
    if is_v2 and isinstance(data.get('pilot_gates',{}),dict):
        for gate in PROFILES[profile]['pilot_gates']:
            entry=data.get('pilot_gates',{}).get(gate)
            if isinstance(entry,dict) and entry.get('passed') is True:
                evidence_ids = entry.get('evidence_ids',[])
                if not evidence_ids:
                    errors.append(f'pilot_gates.{gate}: passed gate requires linked evidence identifiers')
                for evid in evidence_ids:
                    if isinstance(evid,str) and evid.startswith('EV-'):
                        if not data.get('evidence_ledger') or not verified_behavior(base_dir / data['evidence_ledger'],evid)[0]:
                            errors.append(f'pilot_gates.{gate}: behavioral ledger receipt invalid {evid}')
                    elif not isinstance(evid,str) or review_map.get(evid)!='supported':
                        errors.append(f'pilot_gates.{gate}: claim {evid} must have an intact human source review')
    return errors, warnings


def score(data, warnings):
    pillars = data["pillars"]
    qs = {p: pillars[p]["quality"] for p in PILLAR_WEIGHTS}
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
    source_risk = bool(data.get('claims') and
                       (not data.get('verification_report') or any('Unreviewed public source claim' in w or 'Could not validate source review ledger/report' in w for w in warnings)))
    if fatal:
        decision = "NO_GO"
        reason = "A sourced, confirmed, unresolved fatal blocker overrides the score."
    elif not web or not complete:
        decision = "RESEARCH_INCOMPLETE"
        reason = "Live research or necessary pillar assessments are missing; do not treat this as a launch decision."
    elif total < 50 and any(qs[p] <= 1 and ev[p] >= 3 for p in CORE):
        decision = "PIVOT"
        reason = "Low weighted attractiveness plus behavior-backed evidence of a severe core weakness."
    elif total >= 75 and not possible_fatal and not missing_gates and not source_risk and all(qs[p] >= 3 and ev[p] >= 3 for p in CORE):
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
    return {
        "schema_version": "2.0",
        "business_model_profile": profile_name,
        "missing_pilot_gates": missing_gates,
        "source_review_gate_open": not source_risk,
        "as_of": data["as_of"],
        "project": data["project"]["name"],
        "decision": decision,
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
        "disclaimer": "Heuristic triage, not a probability of commercial success or legal approval."
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evaluation", type=pathlib.Path, help="Input evaluation.json")
    parser.add_argument("--output", type=pathlib.Path, help="Write decision JSON here (default: stdout)")
    args = parser.parse_args()
    try:
        data = json.loads(args.evaluation.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: Cannot read evaluation: {exc}", file=sys.stderr)
        return 2
    errors, warnings = validate(data, args.evaluation.parent)
    if errors:
        for err in errors:
            print("ERROR: " + err, file=sys.stderr)
        return 2
    result = score(data, warnings)
    body = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(body, encoding="utf-8")
    else:
        print(body, end="")
    for warning in result["warnings"]:
        print("WARNING: " + warning, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
