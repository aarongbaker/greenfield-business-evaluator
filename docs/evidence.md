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

Before a pilot can be recommended, a person reads each source-dependent claim and records a review against the exact report:

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

Hypotheses, notes and failures need no receipt. Real customer behavior does: a paid test, a signed letter of intent, a repeat purchase. Record it with the receipt file, which must be inside the research folder:

```bash
greenfield evidence add stripe-export.csv --as presale --result pass --consent customer_terms --attester "Your Name" --pillar problem --pillar economics  # needs-terminal
```

Put the event id it prints (`EV-...`) into that pillar's behavior `ledger_event_id` in `evaluation.json`. Only then can the pillar's evidence score reach 3 or more. An interview without an observed action is evidence 1.

## Why a person must be at the terminal

A receipt counts only if a person confirms it. `ledger record --attester` shows a summary and a one-time code, reads the code back from the terminal (`/dev/tty`), and signs the event with a local key at `~/.config/greenfield/attest.key` (or `$GF_CONFIG_DIR/attest.key`). Agents have no terminal, so they are refused. The PreToolUse guard from `greenfield hooks install` also blocks agent attempts to run the command or touch the ledger and key files.

Receipts verify only where the key is. A teammate can point `GF_ATTEST_KEY_FILE` at a copy. Back the key up: it is printed on first use. Ledgers recorded before signing need a one-time `greenfield ledger reattest`, run by you in a terminal.

Signing raises the cost of forging evidence; it is not proof. Someone with full access to your files and key can rewrite a whole chain. Keep receipts and personal interview data out of public folders, and read [SECURITY.md](../SECURITY.md) for what is and is not defended.

## Changing your mind

When an experiment changes the verdict, record a `decision_revision` event that names the experiment, then re-score. Keep old decisions in the ledger rather than overwriting them.
