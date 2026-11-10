> For agents running the skill. People: read [docs/evidence.md](../../docs/evidence.md) instead.

# v2 operational protocol: evidence, experiments, models, checkpoints, portfolio

`greenfield` on your PATH is a shortcut for the `python3 <skill dir>/scripts/greenfield.py` form used here.

**Every command is optional to perform only when the host has shell access and the user authorized file changes.** Core research may still proceed if these scripts cannot run, but a machine-backed pilot decision must not be claimed without required evidence. Python 3.11+, macOS/Linux (the append-only ledger and run controller use `fcntl`). No extra packages.

## A. Source inspection (P0)

1. In `evaluation.json`, record each consequential factual claim, direct `source_url`, `published_date`, `independent_origin` (original study/report), and a short `supporting_quote` **only if actually visible in the source**. Do not invent quotations or copy excess source text. A source URL is not independent corroboration.
2. From the project research directory, run:

```bash
python3 <skill dir>/scripts/greenfield.py sources check evaluation.json --output source-verification.json --allow-network --json
```

Without `--allow-network`, the script only checks publication date/origin metadata. `--allow-network` reads **public HTTP(S) HTML/text only**, with download/time/redirect bounds, no authenticated sessions, and a conservative private-host filter; it connects only to the vetted IP on ports 80 and 443, so DNS rebinding cannot redirect it to an internal host. Do not run it against confidential URLs or internal services. PDFs, JavaScript-only sites, unavailable and paywalled sources require manual review. It is still not a hardened universal SSRF boundary: fetched text is untrusted, and text matching is not truth.

3. Treat `excerpt_check=found` as **text retrieval success only**. It is not factual proof or semantic entailment. A human reads the source and records a review against the exact report bytes. Never run this yourself; `greenfield evidence status` prints it filled in, and you print it for the founder to run at a terminal (add `--gate G` when the claim closes a gate):

```bash
# For the founder to run at a terminal, not the agent
greenfield ledger record --kind source_review --claim-id C1 --outcome supported \
  --artifact research/greenfield/<slug>/source-verification.json --notes 'Why the specific claim is supported' --attester '<founder name>'
```

`contradicted` and `unclear` are also valid. Do not simulate a human reviewer or silently mark sources verified. The scorer checks reviewed public claims in the exact current report against the ledger and blocks pilot approval for unreviewed source-dependent claims.

## B. Real experiment history (P0)

Use one append-only ledger per greenfield project. Every record has a UTC time, ID, previous-hash pointer and SHA-256 checksum. **Hash chaining is edit-evident, not cryptographic nonrepudiation or independent confirmation**: someone with file access can rewrite the whole history. Preserve private receipts securely and exclude the folder from source control.

```bash
# Hypothesis and failure need no behavioral receipt
python3 <skill dir>/scripts/greenfield.py ledger record --ledger experiment-ledger.jsonl \
  --kind hypothesis --project-name 'Example idea' --hypothesis 'Buyers pay to avoid manual audits' --json

# After a real customer action: print this for the founder to run at a terminal; never run it yourself
greenfield evidence add research/greenfield/<slug>/materials/inbox/stripe-presale.redacted.csv --as presale \
  --pillar problem --pillar economics --experiment EXP-2 --result pass --outcome '4 of 30 paid $49' \
  --consent customer_terms --attester '<founder name>'

python3 <skill dir>/scripts/greenfield.py ledger verify --ledger experiment-ledger.jsonl --json
python3 <skill dir>/scripts/greenfield.py ledger summary --ledger experiment-ledger.jsonl --json
```

Behavior receipts and source reviews must be recorded by a person at a terminal: the command shows a summary and a one-time code to type back, then signs the event with a local key (`~/.config/greenfield/attest.key`, or `$GF_CONFIG_DIR/attest.key`). Agents have no terminal and are refused; the PreToolUse guard (`greenfield hooks install`) also blocks their attempts to run `evidence add`, `ledger record --attester` or touch the ledger and key files. Receipt and report paths must sit inside the ledger's folder and are stored relative, so the folder can be moved or shared. Receipts verify only where the key is; a teammate can point `GF_ATTEST_KEY_FILE` at a copy. Ledgers recorded before signing need a one-time `greenfield ledger reattest --ledger experiment-ledger.jsonl`.

`evidence add` writes the behavior (with its `EV-...` id) into each linked pillar itself. To connect a receipt already recorded, run `greenfield evidence link EV-... --pillar P` (agent-safe); never write `ledger_event_id` by hand. Then re-assess quality on the touched pillars and run `greenfield evidence assessed PILLAR...`. A customer interview without an observed action is normally evidence 1, not 3. Do not place secret receipts or personally identifying interview data in public research folders. Store consent and retention rules separately where necessary.

Log an updated evaluation verdict using `decision_revision` events, referencing earlier decisions and which experiment caused the change. Do not overwrite old decision documents without retaining the prior decision in the ledger.

## C. Business model policies (P1)

Set `project.business_model` to one of:

- `general` — baseline default, no sector-specific gates
- `bootstrapped_saas` — weighted toward economics and reachable distribution; `pricing_test`, `delivery_margin`, `repeatable_channel`
- `venture_startup` — market scalability, growth and timing; `venture_scale_market`, `credible_growth_channel`, `funding_runway`
- `marketplace` — two-sided liquidity and margin; `supply_commitments`, `demand_commitments`, `liquidity_model`, `transaction_margin`
- `services` — paid engagement, delivery capacity, founder dependence; `paid_engagement`, `delivery_capacity`, `owner_dependence`
- `regulated` — lawful/compliant execution and safety; `jurisdiction_review`, `compliance_path`, `data_and_safety`, `professional_review`

Profiles alter **heuristic weights and bounded-pilot gates**, not probability forecasts. A user can ask for multiple model scenarios and compare scores without cherry-picking a preferred result. In `pilot_gates`, use `{"passed": true, "evidence_ids": ["EV-..."]}` or a human-reviewed claim ID. An AI assertion or URL alone is not a passed gate. `regulated` always requires appropriate independent professional review; the skill is not qualified to issue legal or clinical clearance.

## D. Resumable research, observed live (P1)

Start Mission Control first (see `docs/mission-control.md` in the repository), then:

```bash
python3 <skill dir>/scripts/greenfield.py task plan --json
python3 <skill dir>/scripts/greenfield.py task claim --role gf-problem --json
# Orchestrator actually delegates to runtime agent; write an authentic specialist summary.
python3 <skill dir>/scripts/greenfield.py task complete --json --role gf-problem --artifact research/greenfield/idea/specialists/gf-problem.md
python3 <skill dir>/scripts/greenfield.py task resume --freshness-hours 72 --json
python3 <skill dir>/scripts/greenfield.py task coverage --evaluation research/greenfield/idea/evaluation.json --verification-report research/greenfield/idea/source-verification.json --json
python3 <skill dir>/scripts/greenfield.py status --usd-per-million-tokens 5 --json
```

No task is automatically launched. The skill orchestrator must actually invoke supported Claude or Codex delegation tools; the plan records claims/completions and resumes based on checksums + age. The red team task is blocked until the other eight have checkpointed. `--usd-per-million-tokens` is a user-supplied **blended illustrative rate**, and costs are approximate **only for reported tokens**; no official invoiced spend is inferred. The dashboard shows the number of artifact checkpoints and explicit claim coverage, not invented research percentages. Emit native lifecycle hooks rather than faking them.

## E. Portfolio analysis and transparent forecasting (P2)

Prepare a portfolio manifest following `assets/portfolio-template.json`. Reference **actual** `evaluation.json` files within the manifest directory; the portfolio re-scores each one, and an optional `decision.json` that disagrees leaves that idea unranked. Supply human founder-fit rationale; estimated build costs/weeks; one measurable next test with a precommitted threshold; estimated test cost, time, expected decision learning (ordinal 0–5); and optional financial scenario inputs.

Start from `assets/portfolio-template.json`; its `_help` keys say what each block needs, and the script exits 2 listing any placeholder still unfilled.

```bash
python3 <skill dir>/scripts/greenfield.py portfolio portfolio.json \
  --output portfolio-ranking.json --markdown PORTFOLIO.md --json
```

Results show a *heuristic priority index* under three sensitivity weighting sets (`balanced`, `capital_constrained`, `learning_first`). `NO_GO` and `RESEARCH_INCOMPLETE` cannot win a build ranking. Missing mandatory inputs are surfaced as an error, not replaced by synthetic values. Forecast low/base/high uses only user-provided buyer counts, 12-month per-buyer revenue, variable cost and fixed cost; outputs are deterministic arithmetic, **not predictive probabilities**. Never infer future customers, churn or margins absent evidence.

## Reproducible decision command

```bash
python3 <skill dir>/scripts/greenfield.py score evaluation.json --output decision.json --json
```

For v2, core evidence ≥3 must reference intact real ledger receipts, source-dependent claims must be reviewed before bounded pilot authorization, and model-specific gates must have supported evidence. A passing score is not permission to spend, ship, process personal data or ignore regulation.

To surface an explicitly assumed token-cost estimate in the dashboard, run `python3 <skill dir>/scripts/greenfield.py task set-rate --usd-per-million-tokens <YOUR_BLENDED_RATE> --json`. If there are no provider-reported tokens, cost must remain unknown.
