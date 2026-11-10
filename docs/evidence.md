# Evidence, source checks and the ledger

A verdict is only as good as the evidence behind it. Greenfield keeps two kinds of record next to each evaluation: a **source check** for public claims, and an **experiment ledger** for what real customers did. Agents can fill in the first; only a person can sign off the second.

## Claims and sources

In `evaluation.json`, each consequential claim lists its `source_url`, `published_date`, whether it is an `independent_origin` (the original study, not a write-up of it), and a short `supporting_quote` copied from the source. Then check them:

```bash
greenfield start --idea "Route planning for independent laundries"
greenfield sources check
greenfield sources check --allow-network  # needs-network
```

Without `--allow-network`, the check stays offline and looks only at dates, duplicate origins and missing fields. With it, Greenfield fetches each public page (HTML or text only, with size, time and redirect limits, ports 80 and 443, no private addresses) and looks for the quoted text. The report goes to `source-verification.json` beside the evaluation.

A found quote means the text was retrieved, not that the claim is true. PDFs, paywalled and JavaScript-only pages need a person to read them. Sources older than two years are flagged (`--stale-days` changes that).

## Human source review

Before a pilot can be recommended, a person reads each source-dependent claim and records a review against the exact report. `greenfield evidence status` prints this command, filled in, for each unreviewed claim. Add `--gate G` when the claim closes a gate:

```bash
greenfield ledger record --kind source_review --project-name "Laundry routing" --hypothesis "Review claim C1" --claim-id C1 --outcome supported --attester "Your Name" --artifact source-verification.json --notes "Census table matches the quote"  # needs-terminal
```

`contradicted` and `unclear` are the other outcomes. If the report changes, its sha256 changes and the reviews must be redone.

## The experiment ledger

Each research folder has one append-only ledger, `experiment-ledger.jsonl`. Every event has a time, an id, the hash of the previous event and its own SHA-256, so editing or deleting one event breaks the chain.

```bash
greenfield ledger record --kind hypothesis --project-name "Laundry routing" --hypothesis "Owners pay to cut route planning time"
greenfield ledger verify
greenfield ledger summary
```

Hypotheses, notes and failures need no receipt. Real customer behavior does: a paid test, a signed letter of intent, a repeat purchase. Record each file with `greenfield evidence add`, one file per command, at a terminal:

```bash
greenfield evidence add research/greenfield/laundry-routing/materials/inbox/stripe-presale.redacted.csv --as presale --pillar value --pillar economics --gate paid_engagement --experiment EXP-2 --result pass --outcome '4 of 30 paid $49' --consent customer_terms --attester 'Your Name'  # needs-terminal
```

`--as` says what the file is (`greenfield evidence types` lists the types for your profile). It sets the ledger kind and the highest evidence the file can earn. `--result` is judged against the experiment's `success_threshold`, and you should record failures too. Put single quotes around text that contains `$`.

The command copies the file into `receipts/`, signs the event, and writes the behavior into each linked pillar of `evaluation.json`. It also links the gate when the result is `pass`. The `presale` example above lifts value and economics to evidence 4:

```json
{
  "behaviors": [{"kind": "paid_test", "description": "4 of 30 paid $49", "observed_at": "2026-12-02",
    "source_or_artifact": "receipts/2026-12-02-presale-stripe-presale.redacted.csv", "verified": true,
    "ledger_event_id": "EV-3f2a9c01b7de"}],
  "pilot_gates": {"paid_engagement": {"passed": true, "evidence_ids": ["EV-3f2a9c01b7de"]}}
}
```

It never changes quality. Ask the assistant to re-assess the pillars, then run `greenfield score`.

- **Where the file can be.** The path resolves against the current folder first, then the run folder. Originals that contain personal data go in `research/greenfield/<slug>/materials/raw/`, and you redact them into `materials/inbox/` with `greenfield evidence redact`. The tool refuses a `materials/raw/` that is not inside a run folder.
- **Reuse caps.** One file or experiment backs at most 2 core pillars and 3 pillars in all. The same file, or a CSV whose rows mostly overlap an earlier receipt, counts once. A file already recorded in a sibling run is shown as `reused_from`.
- **Allowed kinds.** Each `--as` type allows only certain pillars and gates, listed in the [founder journey](founder-journey.md#what-to-bring-and-what-it-earns). `feasibility_proof` backs execution only. `--kind` can't raise the ceiling above what the `--as` type allows. `greenfield ledger record` refuses behavior kinds and `feasibility_proof` and points you to `evidence add`.
- **Wrong-kind receipts from before this release.** An older event recorded with a kind that does not fit its pillar no longer counts there. Record the file again with `evidence add` and the right `--as`. For pre-signing ledgers, run `greenfield ledger reattest` once at a terminal.

An interview without an observed action is evidence 1.

## Why a person must be at the terminal

A receipt counts only if a person confirms it. `evidence add` (and `ledger record --attester`) shows a summary and a one-time code, reads the code back from the terminal (`/dev/tty`), and signs the event with a local key at `~/.config/greenfield/attest.key` (or `$GF_CONFIG_DIR/attest.key`). Agents have no terminal, so they are refused. The PreToolUse guard from `greenfield hooks install` also blocks agent attempts to run the command or touch the ledger and key files.

Receipts verify only where the key is. A teammate can point `GF_ATTEST_KEY_FILE` at a copy. Back the key up: it is printed on first use. Ledgers recorded before signing need a one-time `greenfield ledger reattest`, run by you in a terminal.

Signing raises the cost of forging evidence; it is not proof. Someone with full access to your files and key can rewrite a whole chain. Keep receipts and personal interview data out of public folders, and read [SECURITY.md](../SECURITY.md) for what is and is not defended.

## Changing your mind

When an experiment changes the verdict, record a `decision_revision` event that names the experiment, then re-score. Keep old decisions in the ledger rather than overwriting them.
