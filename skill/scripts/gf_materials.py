"""Materials intake (W45, W46): what founders bring, how a file becomes a signed receipt, and the reuse rules the scorer shares."""
from __future__ import annotations
import csv
import datetime as dt
import hashlib
import hmac
import io
import json
import mimetypes
from pathlib import Path
import re
import secrets
import shutil

from gf_common import GFError, atomic_write, load_json
import gf_ledger
from gf_ledger import BEHAVIOR
from gf_profiles import BASE, PROFILES, GATE_HELP

CORE = ("problem", "market", "value", "economics", "distribution")
ALL = sorted(BASE)
MARKET_SIDE = ("problem", "market", "value", "economics", "distribution", "competition", "timing")
CHANNEL_GATES = ("repeatable_channel", "credible_growth_channel", "liquidity_model")
# --as type -> ledger kind, evidence ceiling, pillars it may back, gates it may close (Decisions 2 and 3)
MATERIALS = {
    "analytics": ("customer_action", 3, MARKET_SIDE, CHANNEL_GATES),
    "signups": ("customer_action", 3, ("problem", "market", "value"), CHANNEL_GATES),
    "channel": ("customer_action", 3, ("distribution", "market"), CHANNEL_GATES[:2]),
    "presale": ("paid_test", 4, MARKET_SIDE, ("pricing_test", "demand_commitments", "paid_engagement")),
    "invoice": ("paid_test", 4, ("value", "economics", "problem", "distribution", "competition", "timing"), ("paid_engagement", "pricing_test", "transaction_margin")),
    "loi": ("signed_commitment", 4, ("problem", "value", "market", "competition"), ("demand_commitments", "supply_commitments", "funding_runway")),
    "supplier-loi": ("signed_commitment", 4, ("distribution", "market"), ("supply_commitments",)),
    "repeat": ("repeat_purchase", 5, tuple(ALL), ("repeatable_channel", "paid_engagement", "pricing_test")),
    "prototype": ("feasibility_proof", 4, ("execution",), ("delivery_capacity", "owner_dependence", "professional_review")),
    "model": ("feasibility_proof", 0, (), ("delivery_margin", "transaction_margin", "funding_runway", "liquidity_model", "venture_scale_market")),
    "ops-record": ("feasibility_proof", 4, ("execution",), ("delivery_capacity", "owner_dependence")),
    "memo": ("feasibility_proof", 4, ("execution",), ("jurisdiction_review", "compliance_path", "data_and_safety", "professional_review")),
}
NOT_RECEIPTS = ("interviews", "survey", "competitor-research")
KIND_CEILING = {"customer_action": 3, "paid_test": 4, "signed_commitment": 4, "feasibility_proof": 4, "repeat_purchase": 5}
FIT = {"customer_action", "paid_test", "signed_commitment", "repeat_purchase"}
RESULTS = ("pass", "mixed", "fail")
CONSENTS = ("own_data", "customer_terms", "public", "counterparty_signed")
RESERVED = {"demo-research", "demo-proceed"}
TEXT = {".csv", ".tsv", ".txt", ".md", ".json"}
MAGIC = {".pdf": (b"%PDF",), ".png": (b"\x89PNG",), ".jpg": (b"\xff\xd8\xff",), ".jpeg": (b"\xff\xd8\xff",),
         ".xlsx": (b"PK\x03\x04",), ".docx": (b"PK\x03\x04",)}
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE = re.compile(r"(?<![\w.])\+?\d[\d ().-]{8,}\d(?![\w.])")
CARD = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
PII_HEADERS = {"email", "e-mail", "name", "first_name", "last_name", "full_name", "phone", "address", "card", "ssn"}
NAMES_WARNING = "names in free text were not checked; redact names by hand"
CTX = None  # cli._ctx, set by register()


def kind_fits(kind, pillar):
    return kind in FIT or (kind == "feasibility_proof" and pillar == "execution")


def ceiling(event):
    """Highest evidence a signed event supports: the lower of its kind's and its material's (Decision 5)."""
    limit = KIND_CEILING.get(event.get("kind"), 0)
    mat = MATERIALS.get(event.get("material"))
    return min(limit, mat[1]) if mat else limit


def rubric(event):
    """The quality a receipt supports (Decision 5): evidence + 1 on pass, evidence on mixed, 2 on fail."""
    e = ceiling(event)
    return {"pass": min(5, e + 1), "mixed": e, "fail": 2}.get(event.get("result"), e)


def receipts(events):
    """Attested behavior events, minus those retired by a later --replaces."""
    retired = {e.get("replaces") for e in events if e.get("replaces")}
    return [e for e in events if e.get("kind") in BEHAVIOR and e.get("human_attested") and e.get("artifact") and e.get("id") not in retired]


def _same_artifact(a, b):
    if a["artifact"]["sha256"] == b["artifact"]["sha256"]:
        return True
    x, y = set(a.get("row_hashes") or ()), set(b.get("row_hashes") or ())
    return bool(x and y) and len(x & y) / min(len(x), len(y)) > 0.5


def reuse_errors(events):
    """Decision 1: one artifact or experiment backs at most 2 core pillars and 3 in all, whether linked or not."""
    out, rs = [], [e for e in receipts(events) if e.get("pillar_ids")]
    seen = set()
    for e in rs:
        group = [x for x in rs if _same_artifact(e, x) or (e.get("experiment_id") and x.get("experiment_id") == e["experiment_id"])]
        pillars = sorted({p for x in group for p in x["pillar_ids"]})
        core = [p for p in pillars if p in CORE]
        key = tuple(sorted(x["id"] for x in group))
        if key not in seen and (len(core) > 2 or len(pillars) > 3):
            seen.add(key)
            out.append(f"artifact {e['artifact']['path']} (sha256 {e['artifact']['sha256'][:12]}) backs {', '.join(pillars)} via {', '.join(key)}: "
                       "at most 2 core pillars and 3 in all; record different evidence for the others")
    return out


def row_hashes(path, key):
    """Keyed hashes of normalized data rows (CSV and TSV), so a re-saved export counts as the same artifact."""
    if path.suffix.lower() not in (".csv", ".tsv"):
        return []
    rows = list(csv.reader(io.StringIO(path.read_text(encoding="utf-8", errors="replace")), delimiter="\t" if path.suffix.lower() == ".tsv" else ","))
    return [hmac.new(key, "\x1f".join(c.strip().casefold() for c in r).encode("utf-8"), hashlib.sha256).hexdigest()[:32] for r in rows[1:] if any(c.strip() for c in r)]


def idea_sha(project):
    return hashlib.sha256(f"{project.get('idea', '')}\n{project.get('initial_customer', '')}".encode("utf-8")).hexdigest()


def idea_text(project):
    """The idea and initial customer, normalized for case and whitespace (what reidea compares)."""
    return " ".join(f"{project.get('idea', '')} / {project.get('initial_customer', '')}".casefold().split())


def binding(data, folder):
    return {"evaluation_id": data.get("evaluation_id", ""), "run_slug": Path(folder).resolve().name, "idea_sha": idea_sha(data["project"]), "idea_text": idea_text(data["project"])}


def _distance(a, b):
    row = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        prev, row[0] = row[0], i
        for j, y in enumerate(b, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (x != y))
    return row[-1]


def reidea(path, confirm=None):
    """Sign a typo-sized idea edit so earlier receipts keep counting (Decision 9). The limit is cumulative from the first text."""
    path = Path(path)
    data = load_json(path.parent / "evaluation.json")
    events, key = gf_ledger.read_ledger(path), gf_ledger.load_key()
    signed = [e for e in events if e.get("idea_text") and e.get("idea_sha") and not gf_ledger.signature_problem(e, key)]
    if not signed:
        raise GFError("no signed receipts to carry across an idea change", path=path)
    last, new_sha, new_text = signed[-1], idea_sha(data["project"]), idea_text(data["project"])
    if last["idea_sha"] == new_sha:
        return {"changed": False}
    original = next((e["original_idea_text"] for e in reversed(signed) if e.get("original_idea_text")), signed[0]["idea_text"])
    if _distance(original, new_text) > 10:
        raise GFError("that is more than a typo fix (over 10 characters from the original idea)", hint='greenfield start --new --idea "<new framing>", then re-record your receipts')
    (confirm or gf_ledger.tty_confirm)({"old idea": last["idea_text"], "new idea": new_text})
    fields = {"observed_at": dt.date.today().isoformat(), "kind": "idea_change", "project": data["project"].get("name") or path.parent.name, "hypothesis": "idea change", "outcome": "", "notes": "",
              "attester": "", "human_attested": False, "artifact": None, "pillar_ids": [], "claim_id": "", "experiment_id": "",
              **binding(data, path.parent), "previous_idea_sha": last["idea_sha"], "original_idea_text": original}
    return gf_ledger._write(path, fields, gf_ledger.load_key())


def exp_pillars(exp):
    if isinstance(exp.get("pillars"), list):
        return exp["pillars"]
    return [exp["pillar"]] if exp.get("pillar") else []


def _luhn(digits):
    total = 0
    for i, c in enumerate(reversed(digits)):
        n = int(c) * (2 if i % 2 else 1)
        total += n - 9 if n > 9 else n
    return total % 10 == 0


def pii_found(path):
    """What personal data a text file seems to hold, by label; names in free text are not detected."""
    text, found = path.read_text(encoding="utf-8", errors="replace"), set()
    if EMAIL.search(text):
        found.add("emails")
    if PHONE.search(text):
        found.add("phones")
    if any(_luhn(re.sub(r"\D", "", m.group())) for m in CARD.finditer(text)):
        found.add("cards")
    if path.suffix.lower() in (".csv", ".tsv") and text.strip():
        head = next(csv.reader(io.StringIO(text), delimiter="\t" if path.suffix.lower() == ".tsv" else ","), [])
        found |= {f"column {h.strip()}" for h in head if h.strip().lower() in PII_HEADERS}
    return sorted(found)


def _run(args, file=None):
    """(folder, evaluation path): --evaluation, --run, the run folder holding FILE, else the active run."""
    if getattr(args, "evaluation", None):
        ev = Path(args.evaluation).resolve()
        return ev.parent, ev
    if not getattr(args, "run", None) and file is not None:
        for parent in Path(file).absolute().parents:
            if (parent / "evaluation.json").is_file():
                return parent.resolve(), (parent / "evaluation.json").resolve()
    ctx = CTX(args)
    return ctx["research_dir"], ctx["evaluation"]


def _save(ev, data):
    atomic_write(ev, json.dumps(data, indent=2, ensure_ascii=False) + "\n", mode=0o600)


def _events(folder):
    return gf_ledger.read_ledger(folder / gf_ledger_name())


def gf_ledger_name():
    return "experiment-ledger.jsonl"


README = """Materials for this evaluation.

raw/      originals with personal data. The assistant cannot read this folder.
inbox/    redacted or PII-free files. The assistant reads these and they reach your AI provider.
          Interviews, surveys and competitor research stay here: they shape findings, not proof.

Redact first:   greenfield evidence redact materials/raw/FILE --drop-column email
Record proof:   greenfield evidence add FILE --as TYPE ...   (see: greenfield evidence types)
"""


def _file_preview(path):
    """What the human sees before signing: type, size, and for text files the row count and first lines."""
    out = {"type": mimetypes.guess_type(path.name)[0] or "unknown", "size": f"{path.stat().st_size} bytes"}
    if path.suffix.lower() in TEXT:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        out["rows"] = str(max(len(lines) - 1, 0)) if path.suffix.lower() in (".csv", ".tsv") else f"{len(lines)} lines"
        out["first lines"] = "\n  ".join(line[:120] for line in lines[:5])
    return out


def snapshot(folder, data, origin="start"):
    """Write the run's W49 history line; the first one says whether start or a legacy init began tracking."""
    import gf_history
    gf_history.record(folder, data, _events(folder), origin=origin)


def has_id_snapshot(folder):
    try:
        lines = (folder / "quality-history.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    return any(json.loads(line).get("evaluation_id") for line in lines if line.strip())


def setup_folders(folder):
    for sub in ("materials/inbox", "materials/raw", "receipts"):
        (folder / sub).mkdir(mode=0o700, parents=True, exist_ok=True)
    for sub in ("materials", "receipts"):
        ignore = folder / sub / ".gitignore"
        if not ignore.exists():
            ignore.write_text("*\n", encoding="utf-8")
    note = folder / "materials" / "README.txt"
    if not note.exists():
        note.write_text(README, encoding="utf-8")


def init(folder, ev):
    """Give an older folder an evaluation_id and the materials folders; safe to repeat."""
    if folder.name in RESERVED:
        raise GFError(f"{folder.name} is reserved for the bundled demo", hint="greenfield start --idea '...'")
    setup_folders(folder)
    data = load_json(ev)
    if data.get("evaluation_id"):
        return data
    events = _events(folder)
    signed = next((e["evaluation_id"] for e in events if e.get("sig") and e.get("evaluation_id")), None)
    data["evaluation_id"] = signed or "eval-" + secrets.token_hex(4)
    if not signed and events and not has_id_snapshot(folder):
        data["legacy"] = True
    _save(ev, data)
    if not (folder / "quality-history.jsonl").exists():
        snapshot(folder, data, "legacy" if data.get("legacy") else "init")
    return data


def _gate_problem(data, gate, material, kind):
    gates = PROFILES.get(data["project"].get("business_model", "general"), PROFILES["general"])["pilot_gates"]
    allowed = [g for g in MATERIALS[material][3] if g in gates]
    if gate not in allowed:
        return f"--as {material} cannot close {gate} on this profile; allowed: {', '.join(allowed) or 'none'}"
    if kind not in GATE_HELP[gate]["accepts"]:
        return f"{gate} does not accept {kind}"
    return None


def _experiment_hint(args, pillars):
    flags = " ".join(f"--pillar {p}" for p in pillars)
    return f"greenfield evidence experiment add --id {args.experiment or 'EXP-N'} {flags} --hypothesis 'WHAT YOU TESTED'"


def _check_magic(path):
    suffix = path.suffix.lower()
    if suffix not in TEXT and suffix not in MAGIC:
        raise GFError(f"{suffix or 'this file type'} is not accepted", path=path, hint="use csv, tsv, txt, md, json, pdf, png, jpg, xlsx or docx")
    if suffix in MAGIC:
        with path.open("rb") as f:
            head = f.read(8)
        if not head.startswith(MAGIC[suffix]):
            raise GFError(f"{path.name} is not really a {suffix} file", path=path)


def _source(args, folder):
    p = Path(args.file)
    for candidate in (p, folder / p):
        if candidate.is_file():
            return candidate.resolve()
    raise GFError("file not found", path=p, hint="give a path from here or from the run folder")


def _guard_raw(path):
    parts = path.parts
    for i in range(len(parts) - 1):
        if parts[i] == "materials" and parts[i + 1] == "raw" and not (Path(*parts[:i]) / "evaluation.json").is_file():
            raise GFError("materials/raw/ outside a run folder is not ignored by git", path=path,
                          hint="move the file to research/greenfield/<slug>/materials/raw/")


def _other_runs(folder, sha, rows):
    """Slugs/ids in sibling runs that already recorded this file or most of its rows (Decision 1)."""
    out = []
    for ledger in sorted(folder.parent.glob("*/" + gf_ledger_name())):
        if ledger.parent == folder:
            continue
        try:
            events = gf_ledger.read_ledger(ledger)
        except (OSError, ValueError):
            continue
        probe = {"artifact": {"sha256": sha}, "row_hashes": rows}
        out += [f"{ledger.parent.name}/{e['id']}" for e in receipts(events) if _same_artifact(probe, e)]
    return out


def add(args):
    """One human command per file: check, copy to receipts/, confirm at the terminal, append, link (W45)."""
    if args.as_type in NOT_RECEIPTS:
        raise GFError("Not a receipt: leave it in materials/inbox/ and ask the assistant to use it in findings")
    mat = MATERIALS[args.as_type]
    kind = args.kind or mat[0]
    pillars, gate = list(dict.fromkeys(args.pillar)), args.gate
    if args.result is None:
        raise GFError("--result is required: pass, mixed or fail, judged against the experiment's threshold")
    bad = [p for p in pillars if p not in mat[2]]
    if bad:
        raise GFError(f"--as {args.as_type} cannot back {', '.join(bad)}; allowed pillars: {', '.join(mat[2]) or 'none (gate only)'}")
    misfit = [p for p in pillars if not kind_fits(kind, p)]
    if misfit:
        raise GFError(f"{kind} cannot back {', '.join(misfit)}")
    if not pillars and not gate:
        raise GFError("name at least one --pillar or --gate, otherwise this file changes nothing")
    source = Path(args.file).absolute()
    _guard_raw(source)
    folder, ev = _run(args, source if source.is_file() else None)
    source = _source(args, folder)
    _guard_raw(source)
    if source.stat().st_size > 50 * 1024 * 1024:
        raise GFError("file is over 50 MB", path=source)
    _check_magic(source)
    data = init(folder, ev)
    events = _events(folder)
    if gate:
        problem = _gate_problem(data, gate, args.as_type, kind)
        if problem:
            raise GFError(problem)
    if args.observed and dt.date.fromisoformat(args.observed) > dt.date.today():
        raise GFError("--observed is in the future")
    experiments = {e.get("id"): e for e in data.get("experiments") or [] if isinstance(e, dict)}
    exp = experiments.get(args.experiment)
    if any(p in CORE for p in pillars) or args.experiment:
        if not exp or not set(pillars) <= set(exp_pillars(exp)):
            raise GFError(f"--experiment must name an experiment covering {', '.join(pillars) or 'this file'}", hint=_experiment_hint(args, pillars))
    pii, scanned = [], source.suffix.lower() in TEXT
    if scanned:
        pii = pii_found(source)
        if pii and not args.keep_pii:
            note = " The assistant may already have read this file." if "inbox" in source.parts else ""
            raise GFError(f"{source.name} holds personal data ({', '.join(pii)}).{note}",
                          hint=f"greenfield evidence redact {args.file} --drop-column email --mask emails,phones,cards   (or --keep-pii REASON)")
    elif not args.redacted and not args.keep_pii:
        raise GFError(f"{source.name} is not scanned for personal data", hint="redact it by hand, then pass --redacted, or pass --keep-pii REASON")
    key = gf_ledger.ensure_key()[0].read_bytes()
    rows = row_hashes(source, key)
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    reused = _other_runs(folder, sha, rows)
    outcome = args.outcome or args.result
    fields = {"material": args.as_type, "evaluation_id": data["evaluation_id"], "run_slug": folder.name,
              "idea_sha": idea_sha(data["project"]), "idea_text": idea_text(data["project"]), "gate_ids": [gate] if gate else [],
              "result": args.result, "consent": args.consent, "success_threshold": (exp or {}).get("success_threshold", ""), "reused_from": reused,
              "pii": "keep: " + args.keep_pii if args.keep_pii else "declared_redacted" if args.redacted else "clean", "row_hashes": rows}
    if data.get("legacy"):
        fields["legacy"] = True
    if args.replaces:
        old = next((e for e in events if e["id"] == args.replaces), None)
        if not old or old["kind"] != kind or sorted(old["pillar_ids"]) != sorted(pillars) or old.get("result") != args.result:
            raise GFError("--replaces needs an event with the same kind, pillars and result")
        fields["replaces"] = args.replaces
    trial = {"id": "new", "kind": kind, "human_attested": True, "artifact": {"path": source.name, "sha256": sha}, "pillar_ids": pillars,
             "experiment_id": args.experiment or "", "row_hashes": rows, "gate_ids": fields["gate_ids"]}
    problems = reuse_errors(events + [trial]) + ([_gate_reused(events, trial)] if gate and _gate_reused(events, trial) else [])
    if problems:
        raise GFError(problems[0])
    receipts_dir = folder / "receipts"
    observed = args.observed or dt.date.today().isoformat()
    target = receipts_dir / f"{observed}-{args.as_type}-{source.name}"
    made = not target.exists()
    if not made and hashlib.sha256(target.read_bytes()).hexdigest() != sha:
        raise GFError("a different file with this name is already in receipts/", path=target, hint="rename your file and retry")
    if made:
        shutil.copy2(source, target)
    hypothesis = args.hypothesis or (exp or {}).get("hypothesis") or f"{args.as_type} {source.name}"
    project = data["project"].get("name") or folder.name
    preview = {"material": args.as_type, "result": args.result, "threshold": fields["success_threshold"] or "none set", "pillars": ", ".join(pillars) or "none",
               "gates": gate or "none", "consent": args.consent, "personal data": "not scanned for personal data" if not scanned else (", ".join(pii) or "none found")}
    preview.update(_file_preview(target))
    if reused:
        preview["previously recorded for"] = ", ".join(reused)
    try:
        event = gf_ledger.append(folder / gf_ledger_name(), kind, project, hypothesis, outcome, str(target), args.attester, observed, "", pillars, "", args.experiment or "",
                                 confirm=gf_ledger.tty_confirm, extra=fields, preview=preview)
    except Exception:
        if made:
            target.unlink(missing_ok=True)
        raise
    effects = _apply(data, event, pillars, gate, args.result)
    _save(ev, data)
    closes = f"; closes {gate}" if gate and args.result == "pass" else ""
    names = " and ".join(pillars)
    tail = f" Ask the assistant to re-assess {names}, then run greenfield score." if pillars else " Run greenfield score."
    return {"event": event["id"], "effect": f"{event['id']} {args.as_type} ({args.result}) → {', '.join(effects) or 'no pillar'}{closes}.{tail}"}


def _gate_reused(events, trial):
    gate = trial["gate_ids"][0]
    for e in receipts(events):
        if e.get("gate_ids") and e["gate_ids"][0] != gate and _same_artifact(trial, e):
            return f"{trial['artifact']['path']} already closes {e['gate_ids'][0]}: one file closes one gate"
    return None


def _apply(data, event, pillars, gate, result):
    """Write the behaviors and gate link for an event; quality is never touched."""
    effects = []
    for p in pillars:
        item = data["pillars"][p]
        before, limit = item.get("evidence", 0), ceiling(event)
        item["evidence"] = max(before, limit)
        item.setdefault("behaviors", [])
        if not any(b.get("ledger_event_id") == event["id"] for b in item["behaviors"] if isinstance(b, dict)):
            item["behaviors"].append({"kind": event["kind"], "description": event["outcome"] or event["hypothesis"], "observed_at": event["observed_at"],
                                      "source_or_artifact": event["artifact"]["path"], "verified": True, "ledger_event_id": event["id"]})
        effects.append(f"{p} evidence {before}→{item['evidence']}")
        if p in CORE:
            data["execution"]["customer_validation_performed"] = True
    if gate and result == "pass":
        entry = data.setdefault("pilot_gates", {}).setdefault(gate, {"passed": False, "evidence_ids": []})
        entry["evidence_ids"] = list(dict.fromkeys(entry.get("evidence_ids", []) + [event["id"]]))
        entry["passed"] = True
    return effects


def link(args):
    """Agent-safe: connect an existing receipt or reviewed claim to a pillar or gate; never attests."""
    folder, ev = _run(args)
    data = init(folder, ev)
    events = _events(folder)
    if (args.pillar is None) == (args.gate is None):
        raise GFError("give exactly one of --pillar or --gate")
    if not args.id.startswith("EV-"):
        if not args.gate:
            raise GFError("a claim links to a --gate; pillars cite claims through claim_ids")
        claim = next((c for c in data.get("claims", []) if isinstance(c, dict) and c.get("id") == args.id), None)
        if not claim:
            raise GFError(f"unknown claim {args.id}")
        if "claim" not in GATE_HELP[args.gate]["accepts"]:
            raise GFError(f"{args.gate} accepts no claim")
        ok = claim_closes_gate(claim, args.gate, events)
        if not ok:
            raise GFError(f"{args.id} needs a source review naming {args.gate}", hint=f"greenfield ledger record --kind source_review --claim-id {args.id} --gate {args.gate} ...")
        entry = data.setdefault("pilot_gates", {}).setdefault(args.gate, {"passed": False, "evidence_ids": []})
        entry["evidence_ids"] = list(dict.fromkeys(entry.get("evidence_ids", []) + [args.id]))
        entry["passed"] = True
        _save(ev, data)
        return {"linked": args.id, "gate": args.gate}
    event = next((e for e in receipts(events) if e["id"] == args.id), None)
    if not event:
        raise GFError(f"{args.id} is not an attested receipt in this run's ledger")
    if args.pillar:
        if args.pillar not in event["pillar_ids"]:
            raise GFError(f"{args.id} was not recorded for {args.pillar}; recorded for: {', '.join(event['pillar_ids']) or 'none'}")
        return _linked(ev, data, event, [args.pillar], None, {"linked": args.id, "pillar": args.pillar})
    if args.gate not in (event.get("gate_ids") or []):
        raise GFError(f"{args.id} was not recorded for {args.gate}")
    if event.get("result") != "pass":
        raise GFError(f"{args.id} came back {event.get('result')}: it cannot close {args.gate}")
    return _linked(ev, data, event, [], args.gate, {"linked": args.id, "gate": args.gate})


def _linked(ev, data, event, pillars, gate, out):
    _apply(data, event, pillars, gate, event.get("result"))
    _save(ev, data)
    return out


def experiment_add(args):
    folder, ev = _run(args)
    data = init(folder, ev)
    rows = data.setdefault("experiments", [])
    if any(isinstance(e, dict) and e.get("id") == args.id for e in rows):
        raise GFError(f"experiment {args.id} already exists")
    if sum(p in CORE for p in set(args.pillar)) > 2:
        raise GFError("an experiment covers at most 2 core pillars")
    rows.append({"id": args.id, "pillars": sorted(set(args.pillar)), "hypothesis": args.hypothesis, "status": "proposed",
                 **({"success_threshold": args.success_threshold} if args.success_threshold else {})})
    _save(ev, data)
    return {"experiment": args.id}


def assessed(args):
    folder, ev = _run(args)
    data = load_json(ev)
    stamp = dt.datetime.now(dt.timezone.utc).isoformat()
    for p in args.pillars:
        data["pillars"][p]["assessed_at"] = stamp
    _save(ev, data)
    return {"assessed": args.pillars, "at": stamp}


def do_init(args):
    folder, ev = _run(args)
    tracked = (folder / "quality-history.jsonl").exists()
    data = init(folder, ev)
    out = {"evaluation_id": data["evaluation_id"], "folder": str(folder), "legacy": bool(data.get("legacy"))}
    n, m = len(data.get("hard_blockers") or []), len(data.get("claims") or [])
    if not tracked and (n or m):
        out["note"] = f"{n} blockers and {m} claims existed before tracking began"
    return out


def types(args):
    try:
        model = load_json(_run(args)[1])["project"].get("business_model", "general")
    except (GFError, OSError, ValueError):
        model = "general"
    gates = PROFILES.get(model, PROFILES["general"])["pilot_gates"]
    return {"profile": model, "types": [{"as": k, "kind": m[0], "evidence_up_to": m[1], "pillars": list(m[2]), "gates": [g for g in m[3] if g in gates]} for k, m in MATERIALS.items()],
            "not_receipts": list(NOT_RECEIPTS)}


def status(args):
    folder, ev = _run(args)
    data = init(folder, ev)
    events = _events(folder)
    rs = receipts(events)
    pillars = {p: {"evidence": data["pillars"][p].get("evidence"), "receipts": [e["id"] for e in rs if p in e["pillar_ids"]]} for p in ALL if p in data["pillars"]}
    gates = {g: (data.get("pilot_gates") or {}).get(g, {"passed": False, "evidence_ids": []}) for g in PROFILES.get(data["project"].get("business_model", "general"), PROFILES["general"])["pilot_gates"]}
    warnings = inbox_warnings(folder) + _bad_entries(data, folder)
    return {"evaluation_id": data["evaluation_id"], "pillars": pillars, "gates": gates, "receipts": [
        {"id": e["id"], "kind": e["kind"], "material": e.get("material"), "result": e.get("result"), "pillars": e["pillar_ids"], "gates": e.get("gate_ids", [])} for e in rs],
        "unreviewed_claims": _unreviewed(data, folder, events), "warnings": warnings}


def _bad_entries(data, folder):
    import gf_evidence
    try:
        entries = load_json(Path(folder) / "source-verification.json").get("claims", [])
    except (OSError, ValueError, GFError, AttributeError):
        return []
    claims, key = {c.get("id"): c for c in data.get("claims", []) if isinstance(c, dict)}, gf_ledger.load_key()
    return [f"{e.get('claim_id')}: {gf_evidence.entry_problem(e, claims.get(e.get('claim_id'), {}), key)}" for e in entries if gf_evidence.entry_problem(e, claims.get(e.get("claim_id"), {}), key)]


def inbox_warnings(folder):
    """Personal data found in materials/inbox/, which the assistant may read."""
    inbox = Path(folder) / "materials" / "inbox"
    out = []
    for f in sorted(inbox.iterdir()) if inbox.is_dir() else []:
        if f.is_file() and f.suffix.lower() in TEXT and (found := pii_found(f)):
            out.append(f"{f.name} in materials/inbox/ holds {', '.join(found)}: greenfield evidence redact {f}")
    return out


def _unreviewed(data, folder, events):
    report = folder / "source-verification.json"
    try:
        entries = {c.get("claim_id"): c for c in load_json(report).get("claims", [])}
    except (OSError, ValueError, GFError):
        entries = {}
    try:
        done = set(gf_ledger.reviewed_claims(folder / gf_ledger.LEDGER_NAME, "source-verification.json"))
    except (OSError, ValueError):
        done = {e.get("claim_id") for e in events if e["kind"] == "source_review"}
    used = {c for item in data["pillars"].values() if isinstance(item, dict) for c in item.get("claim_ids", [])}
    gate_of = {c: g for g, entry in (data.get("pilot_gates") or {}).items() if isinstance(entry, dict) for c in entry.get("evidence_ids", [])}
    rel = f"research/greenfield/{folder.name}"
    out = []
    for c in data.get("claims", []):
        if isinstance(c, dict) and c.get("classification") == "fact" and c.get("source_url") and c.get("id") in used and c["id"] not in done:
            gate = f" --gate {gate_of[c['id']]}" if c["id"] in gate_of else ""
            out.append({"id": c["id"], "text": c.get("text", ""), "url": c["source_url"], "excerpt": (entries.get(c["id"]) or {}).get("excerpt", ""),
                        "command": f"greenfield ledger record --kind source_review --claim-id {c['id']}{gate} --outcome supported --attester 'YOUR NAME' --artifact {rel}/source-verification.json"})
    return out


def redact(args):
    """Write a redacted copy to the run's materials/inbox/; the original stays in raw/."""
    source = Path(args.file).absolute()
    _guard_raw(source)
    folder, _ = _run(args, source if source.is_file() else None)
    source = _source(args, folder)
    _guard_raw(source)
    suffix = source.suffix.lower()
    if suffix not in TEXT:
        return {"written": None, "note": "redact by hand, then use --redacted"}
    masks = [m for m in (args.mask or "").split(",") if m]
    bad = set(masks) - {"emails", "phones", "cards"}
    if bad:
        raise GFError(f"unknown mask {', '.join(sorted(bad))}", hint="--mask emails,phones,cards")
    text = source.read_text(encoding="utf-8", errors="replace")
    changed = False
    if args.drop_column and suffix in (".csv", ".tsv"):
        delim = "\t" if suffix == ".tsv" else ","
        rows = list(csv.reader(io.StringIO(text), delimiter=delim))
        drop = {i for i, h in enumerate(rows[0] if rows else []) if h.strip().lower() in {c.lower() for c in args.drop_column}}
        missing = {c.lower() for c in args.drop_column} - {h.strip().lower() for h in (rows[0] if rows else [])}
        if missing:
            raise GFError(f"no column named {', '.join(sorted(missing))}", path=source)
        out = io.StringIO()
        csv.writer(out, delimiter=delim, lineterminator="\n").writerows([[c for i, c in enumerate(r) if i not in drop] for r in rows])
        text, changed = out.getvalue(), True
    for mask in masks:
        new = {"emails": EMAIL, "phones": PHONE, "cards": CARD}[mask].sub("[redacted]", text)
        changed |= new != text
        text = new
    if not changed:
        return {"written": None, "note": "nothing changed; " + NAMES_WARNING}
    inbox = folder / "materials" / "inbox"
    inbox.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = inbox / f"{source.stem}.redacted{source.suffix}"
    target.write_text(text, encoding="utf-8")
    return {"written": str(target), "note": NAMES_WARNING}


def _target(p):
    p.add_argument("--evaluation", type=Path, help="evaluation.json (default: the active run's)")
    p.add_argument("--run", metavar="ID", help="run id (default: the active run)")


def register(sub, cmd, group, ctx):
    """Add the `evidence` command group; cmd and group are cli._cmd and cli._group, ctx is cli._ctx."""
    global CTX
    CTX = ctx
    ev = group(sub, "evidence", "bring your own materials: record receipts and link them", ["greenfield evidence types", "greenfield evidence status"])
    p = cmd(ev, "add", "record one file as a human-attested receipt", [
        "greenfield evidence add stripe.redacted.csv --as presale --pillar value --pillar economics --experiment EXP-2 --result pass --consent customer_terms --attester 'Ana Ruiz'"], add)
    p.add_argument("file", help="the file to record")
    p.add_argument("--as", dest="as_type", required=True, choices=sorted(MATERIALS) + list(NOT_RECEIPTS), help="what the file is (see `greenfield evidence types`)")
    p.add_argument("--attester", required=True, help="the person confirming this receipt")
    p.add_argument("--consent", required=True, choices=CONSENTS, help="why you may keep this data")
    p.add_argument("--result", choices=RESULTS, help="the outcome against the experiment's threshold")
    p.add_argument("--kind", choices=sorted(BEHAVIOR), help="override the kind the type implies; the type's ceiling still applies")
    p.add_argument("--pillar", action="append", default=[], choices=ALL, help="pillar this backs (repeatable)")
    p.add_argument("--gate", choices=sorted(GATE_HELP), help="pilot gate this closes")
    p.add_argument("--experiment", help="experiment id; required for a core pillar")
    p.add_argument("--hypothesis", default="", help="default: the experiment's")
    p.add_argument("--outcome", default="", help="what happened, with no customer data")
    p.add_argument("--observed", help="date observed, YYYY-MM-DD (default today)")
    p.add_argument("--keep-pii", metavar="REASON", help="keep personal data in this receipt, for this reason")
    p.add_argument("--redacted", action="store_true", help="you redacted this binary file by hand")
    p.add_argument("--replaces", metavar="EV-ID", help="retire an earlier receipt with the same kind, pillars and result")
    _target(p)
    p = cmd(ev, "link", "connect a recorded receipt or reviewed claim (agent-safe)", ["greenfield evidence link EV-3f2a --pillar value", "greenfield evidence link C7 --gate jurisdiction_review"], link)
    p.add_argument("id", help="EV- id or claim id")
    p.add_argument("--pillar", choices=ALL, help="pillar to link to")
    p.add_argument("--gate", choices=sorted(GATE_HELP), help="gate to link to")
    _target(p)
    p = cmd(ev, "status", "pillars, receipts, gates, unreviewed claims and inbox warnings", ["greenfield evidence status"], status)
    _target(p)
    p = cmd(ev, "redact", "write a redacted copy into materials/inbox/", ["greenfield evidence redact materials/raw/x.csv --drop-column email"], redact)
    p.add_argument("file", help="the file to redact")
    p.add_argument("--drop-column", action="append", default=[], metavar="NAME", help="CSV or TSV column to remove (repeatable)")
    p.add_argument("--mask", metavar="LIST", help="comma list of emails, phones, cards")
    _target(p)
    p = cmd(ev, "init", "add a missing evaluation_id and the materials folders (agent-safe)", ["greenfield evidence init"], do_init)
    _target(p)
    p = cmd(ev, "types", "what each --as type can prove on this profile", ["greenfield evidence types"], types)
    _target(p)
    exp = group(ev, "experiment", "add experiments for proof you already have", ["greenfield evidence experiment add --id EXP-4 --pillar value --hypothesis 'They pay'"])
    p = cmd(exp, "add", "append a proposed experiment (agent-safe)", ["greenfield evidence experiment add --id EXP-4 --pillar value --hypothesis 'They pay'"], experiment_add)
    p.add_argument("--id", required=True, help="experiment id, such as EXP-4")
    p.add_argument("--pillar", action="append", required=True, choices=ALL, help="pillar it tests (repeatable)")
    p.add_argument("--hypothesis", required=True, help="what the experiment tests")
    p.add_argument("--success-threshold", default="", help="the bar a pass must clear")
    _target(p)
    p = cmd(ev, "assessed", "stamp pillars as re-assessed now (agent-safe)", ["greenfield evidence assessed problem value"], assessed)
    p.add_argument("pillars", nargs="+", choices=ALL, help="pillars you re-assessed")
    _target(p)


def claim_digest(claim):
    return gf_ledger.digest({k: claim.get(k) for k in ("statement", "source_url", "classification", "pillar")})


def claim_closes_gate(claim, gate, events):
    """True when the newest source review of this claim signed this gate and the claim's current text (Gate bindings)."""
    if claim.get("classification") != "fact" or not claim.get("source_url"):
        return False
    key = gf_ledger.load_key()
    last = None
    for e in events:
        if e.get("kind") == "source_review" and e.get("claim_id") == claim.get("id") and gf_ledger.trusted_artifact(events, e, key)[0]:
            last = e
    return bool(last) and last.get("outcome") == "supported" and gate in (last.get("gate_ids") or []) and last.get("claim_digest") == claim_digest(claim)


def _when(stamp):
    try:
        t = dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if "T" in str(stamp) and t.tzinfo else None


def assessed_problem(stamp):
    """Why an assessed_at value is unusable, or None. A date-only value would sort before a same-day receipt."""
    t = _when(stamp)
    return "must be a UTC datetime" if t is None else "is in the future" if t > dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5) else None


def analyze(data, ledger_path, folder):
    """Read the ledger once and return what the scorer needs: counted receipts, per-pillar rubric levels, and notes."""
    out = {"events": [], "counted": [], "signed": [], "intact": set(), "rubric": {p: 3 for p in BASE}, "best": {p: 0 for p in BASE}, "backed": {p: False for p in BASE},
           "newest": {p: None for p in BASE}, "governing": {}, "warnings": [], "anchor": None, "legacy": False, "injected": []}
    try:
        events = gf_ledger.read_ledger(ledger_path)
    except (OSError, ValueError):
        return out
    out["events"] = events
    project = data.get("project") if isinstance(data.get("project"), dict) else {}
    current = idea_sha(project)
    key = gf_ledger.load_key()
    out["anchor"] = anchor = next((e["evaluation_id"] for e in events if e.get("sig") and e.get("evaluation_id")), None)
    try:
        reachable = {current}
        for c in reversed([e for e in events if e.get("kind") == "idea_change" and not gf_ledger.signature_problem(e, key)]):
            if c["idea_sha"] in reachable:
                reachable.add(c["previous_idea_sha"])
        if len(reachable) > 1:
            out["warnings"].append("receipts carried across an idea change")
        adopting = {r["reattests"]: r for r in events if r.get("kind") == "reattestation" and r.get("legacy") and r.get("evaluation_id")
                    and not gf_ledger.signature_problem(r, key)}
        for e in receipts(events):
            if not e.get("evaluation_id") and e["id"] in adopting:  # W49: an adopted legacy event reads its binding from the adopter
                e = {**e, **{k: adopting[e["id"]][k] for k in ("evaluation_id", "run_slug", "idea_sha", "idea_text", "material", "result") if k in adopting[e["id"]]}}
            if not e.get("evaluation_id"):
                out["legacy"] = True
                out["warnings"].append(f"Legacy receipt {e['id']} has no evaluation binding: re-record it with `greenfield evidence add`")
            elif e["evaluation_id"] != anchor or e.get("run_slug") != folder.name:
                out["warnings"].append(f"Receipt {e['id']} belongs to another evaluation and does not count")
                continue
            elif e.get("idea_sha") not in reachable:
                out["warnings"].append(f"Receipt {e['id']}: receipt recorded for a different idea")
                continue
            out["counted"].append(e)
            if gf_ledger.trusted_artifact(events, e, key)[0]:
                out["signed"].append(e)
                if gf_ledger.verified_behavior(ledger_path, e["id"])[0]:
                    out["intact"].add(e["id"])
        for p in BASE:
            mine = [e for e in out["signed"] if p in e["pillar_ids"] and kind_fits(e["kind"], p)]
            usable = [e for e in mine if e.get("result") == "fail" or e["id"] in out["intact"]]
            if mine:
                out["best"][p] = max(ceiling(e) for e in mine)
                out["newest"][p] = max(e["recorded_at"] for e in mine)
            if usable:
                gov = max(usable, key=lambda e: (ceiling(e), e["recorded_at"]))
                out["governing"][p] = gov
                out["rubric"][p] = rubric(gov)
            out["backed"][p] = any(e["id"] in out["intact"] and e.get("result") in ("pass", "mixed") and e.get("evaluation_id") and ceiling(e) >= 3 for e in mine)
        out["injected"] = [e["id"] for e in events if e.get("confirm_via") == "injected" and e.get("evaluation_id") in (None, anchor)]
        if out["injected"]:
            out["warnings"].append(f"{len(out['injected'])} ledger event(s) were confirmed by code, not at a terminal (confirm_via: injected): "
                                   "re-record them with `greenfield evidence add`")
        first = next((e for e in events if e.get("sig") and e.get("kind") != "reattestation"), None)
        if first and key and first.get("key_id") != gf_ledger.key_id(key):
            out["warnings"].append(f"This machine's attestation key ({gf_ledger.key_id(key)}) is not the one that signed the first receipt "
                                   f"({first.get('key_id')}): restore that key from backup if you have it")
    except (KeyError, TypeError, AttributeError):  # a hand-written event with missing or wrong-typed fields
        out["warnings"].append("Could not read every ledger receipt: malformed event")
    return out
