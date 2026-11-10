#!/usr/bin/env python3
"""Rebuild skill/assets/demo-proceed: the W52 services example that reaches Proceed (route A, 76.6).

Every receipt is signed by this script with the bundled DEMO key, so each event records confirm_via: injected and
counts only inside the pinned demo path. After a rebuild, paste the printed hashes into gf_ledger.DEMO_PINNED, then
write decision.json with the printed score command.
"""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skill" / "scripts"))
OUT = ROOT / "skill" / "assets" / "demo-proceed"

# (file, --as, kind, pillars, gate, experiment, outcome, rows)
RECEIPTS = [
    ("receipts/discovery-calls.csv", "analytics", "customer_action", ["market", "problem"], None, "EXP-1",
     "SAMPLE: 14 of 60 cold-emailed clinic managers booked a discovery call", "week,emails_sent,calls_booked\n1,30,6\n2,30,8\n"),
    ("receipts/invoice-redacted.txt", "invoice", "paid_test", ["economics", "value"], "paid_engagement", "EXP-2",
     "SAMPLE: one clinic paid the full $2,400 audit fee", "SAMPLE INVOICE (redacted)\nClient: [REDACTED CLINIC]\nService: compliance audit\nAmount paid: $2,400\nStatus: PAID\n"),
    ("receipts/referrals.csv", "channel", "customer_action", ["distribution"], None, "EXP-3",
     "SAMPLE: 5 referral intros from 2 partner accountants produced 3 calls", "source,intros,calls\naccountant-a,3,2\naccountant-b,2,1\n"),
    ("receipts/hours-log.csv", "ops-record", "feasibility_proof", [], "delivery_capacity", "",
     "SAMPLE: the paid audit took 18 hours against a planned 20", "task,hours\nintake,2\nreview,10\nreport,6\n"),
    ("receipts/sop-handoff.md", "ops-record", "feasibility_proof", [], "owner_dependence", "",
     "SAMPLE: a contractor ran the second audit from the SOP without the founder", "# SAMPLE SOP handoff\n\nAudit 2 delivered by a contractor from the written SOP; founder reviewed only the final report.\n"),
]
QUALITY = {"problem": 4, "market": 4, "value": 4, "economics": 4, "distribution": 4, "competition": 3, "execution": 3, "timing": 3}


def evaluation():
    finding = lambda p: f"SAMPLE: {p} finding for the demo; fictional."
    pillars = {p: {"quality": q, "evidence": 1, "finding": finding(p), "claim_ids": [], "behaviors": []} for p, q in QUALITY.items()}
    pillars["market"]["claim_ids"] = ["C1"]
    return {
        "schema_version": "2.0", "evaluation_id": "eval-demo-proceed", "as_of": "2026-11-01",
        "project": {"name": "SAMPLE Clinic Compliance Audits", "idea": "Fixed-fee compliance audits for small dental clinics",
                    "initial_customer": "Independent dental clinics with 2 to 10 staff", "geography": "US", "business_type": "Services",
                    "goal": "bootstrapped", "business_model": "services"},
        "execution": {"web_used": True, "subagents_actual": 0, "mode": "single-agent fallback", "customer_validation_performed": True},
        "pillars": pillars,
        "claims": [{"id": "C1", "pillar": "market", "classification": "fact", "statement": "SAMPLE: the US has about 200,000 dentists.",
                    "source_url": "https://www.ada.org/resources/research/health-policy-institute", "source_title": "SAMPLE citation",
                    "published_date": "2025-01-01", "accessed_date": "2026-11-01", "independent_origin": False, "notes": "SAMPLE DATA"}],
        "hard_blockers": [],
        "experiments": [
            {"id": "EXP-1", "pillars": ["market", "problem"], "hypothesis": "SAMPLE: clinic managers book calls from cold email", "status": "done",
             "success_threshold": "at least 10 calls from 60 emails"},
            {"id": "EXP-2", "pillars": ["economics", "value"], "hypothesis": "SAMPLE: a clinic pays the full audit fee", "status": "done",
             "success_threshold": "one clinic pays $2,400"},
            {"id": "EXP-3", "pillars": ["distribution"], "hypothesis": "SAMPLE: accountants refer clinics", "status": "done",
             "success_threshold": "at least 3 calls from referrals"},
        ],
        "market_model": {}, "evidence_ledger": "experiment-ledger.jsonl", "verification_report": "source-verification.json", "pilot_gates": {},
    }


def main():
    import gf_evidence, gf_ledger, gf_materials
    shutil.rmtree(OUT, ignore_errors=True)
    (OUT / "receipts").mkdir(parents=True)
    key_file = OUT / "demo-attest.key"
    key_file.write_bytes(hashlib.sha256(b"greenfield DEMO attestation key: never use it for real receipts").digest())
    os.environ["GF_ATTEST_KEY_FILE"] = str(key_file)  # this process only
    data, ev, ledger = evaluation(), OUT / "evaluation.json", OUT / "experiment-ledger.jsonl"
    ev.write_text(json.dumps(data, indent=2) + "\n")
    bind = gf_materials.binding(data, OUT)
    injected = lambda summary: None
    for name, material, kind, pillars, gate, exp, outcome, body in RECEIPTS:
        (OUT / name).write_text(body)
        e = gf_ledger.append(ledger, kind, data["project"]["name"], f"SAMPLE {material} {Path(name).name}", outcome, name, "SAMPLE Founder",
                             "2026-10-20", pillars=pillars, experiment_id=exp, confirm=injected,
                             extra={**bind, "material": material, "result": "pass", "gate_ids": [gate] if gate else [], "consent": "own_data", "pii": "declared_redacted"})
        for p in pillars:
            data["pillars"][p]["evidence"] = 3
            data["pillars"][p]["behaviors"] = [{"kind": kind, "description": outcome, "observed_at": "2026-10-20", "source_or_artifact": name,
                                                "verified": True, "ledger_event_id": e["id"]}]
        if gate:
            data["pilot_gates"][gate] = {"passed": True, "evidence_ids": [e["id"]]}
    stamp = dt.datetime.now(dt.timezone.utc).isoformat()
    for item in data["pillars"].values():
        item["assessed_at"] = stamp
    ev.write_text(json.dumps(data, indent=2) + "\n")
    gf_evidence.check(ev, OUT / "source-verification.json")
    entry = json.loads((OUT / "source-verification.json").read_text())["claims"][0]
    claim = data["claims"][0]
    gf_ledger.append(ledger, "source_review", data["project"]["name"], "source review C1", "supported", "source-verification.json", "SAMPLE Founder",
                     "2026-10-21", claim_id="C1", confirm=injected,
                     extra={**bind, "gate_ids": [], "claim_digest": gf_materials.claim_digest(claim), "entry_digest": gf_evidence.entry_digest(entry, claim)})
    (OUT / "README.md").write_text("# Worked example that reaches Proceed (DEMO)\n\nDEMO DATA. A fictional services evaluation whose receipts are "
                                   "signed by a bundled DEMO key. It counts only in this folder, unedited; copied anywhere else it verifies "
                                   "nothing. Score it with `greenfield demo --proceed`.\n")
    for f in ("evaluation.json", "experiment-ledger.jsonl"):
        print(f'"{f}": "{hashlib.sha256((OUT / f).read_bytes()).hexdigest()}",')
    print("DEMO key_id:", gf_ledger.key_id(key_file.read_bytes()))
    print("then: python3 skill/scripts/greenfield.py score skill/assets/demo-proceed/evaluation.json --output skill/assets/demo-proceed/decision.json")


if __name__ == "__main__":
    main()
