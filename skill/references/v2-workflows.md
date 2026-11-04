# v2 operational protocol: evidence, experiments, models, checkpoints, portfolio

**Every command is optional to perform only when the host has shell access and the user authorized file changes.** Core research may still proceed if these scripts cannot run, but a machine-backed pilot decision must not be claimed without required evidence. Python 3.10+, macOS/Linux (the append-only ledger and run controller use `fcntl`). No extra packages.

## A. Source inspection (P0)

1. In `evaluation.json`, record each consequential factual claim, direct `source_url`, `published_date`, `independent_origin` (original study/report), and a short `supporting_quote` **only if actually visible in the source**. Do not invent quotations or copy excess source text. A source URL is not independent corroboration.
2. From the project research directory, run:

```bash
python3 <skill>/scripts/gf_evidence.py evaluation.json --output source-verification.json --allow-network
```

Without `--allow-network`, the script only checks publication date/origin metadata. `--allow-network` reads **public HTTP(S) HTML/text only**, with download/time/redirect bounds, no authenticated sessions, and a conservative private-host filter. Do not run it against confidential URLs or internal services. PDFs, JavaScript-only sites, unavailable and paywalled sources require manual review. DNS-rebinding and external websites mean this is not a hardened universal SSRF boundary.

3. Treat `excerpt_check=found` as **text retrieval success only**. It is not factual proof or semantic entailment. A human can read the source and record a review against the exact report bytes:

```bash
python3 <skill>/scripts/gf_ledger.py record --ledger experiment-ledger.jsonl \
  --kind source_review --project 'Example idea' --hypothesis 'Review claim C1' \
  --claim-id C1 --outcome supported --attester 'Actual reviewer name' \
  --artifact source-verification.json --notes 'Why the specific claim is supported'
```

`contradicted` and `unclear` are also valid. Do not simulate a human reviewer or silently mark sources verified. The scorer checks reviewed public claims in the exact current report against the ledger and blocks pilot approval for unreviewed source-dependent claims.

## B. Real experiment history (P0)

Use one append-only ledger per greenfield project. Every record has a UTC time, ID, previous-hash pointer and SHA-256 checksum. **Hash chaining is edit-evident, not cryptographic nonrepudiation or independent confirmation**: someone with file access can rewrite the whole history. Preserve private receipts securely and exclude the folder from source control.

```bash
# Hypothesis and failure need no behavioral receipt
python3 <skill>/scripts/gf_ledger.py record --ledger experiment-ledger.jsonl \
  --kind hypothesis --project 'Example idea' --hypothesis 'Buyers pay to avoid manual audits'

# After a real customer action, a real human must sign off and supply local receipt
python3 <skill>/scripts/gf_ledger.py record --ledger experiment-ledger.jsonl \
  --kind paid_test --project 'Example idea' --hypothesis 'Price accepted' \
  --outcome 'Actual observed result' --attester 'Human reviewer' \
  --artifact ./private-receipts/test.txt --pillar problem --pillar economics

python3 <skill>/scripts/gf_ledger.py verify --ledger experiment-ledger.jsonl
python3 <skill>/scripts/gf_ledger.py summary --ledger experiment-ledger.jsonl
```

Behavior receipts and source reviews must be recorded by a person at a terminal: the command shows a summary and a one-time code to type back, then signs the event with a local key (`~/.config/greenfield/attest.key`, or `$GF_CONFIG_DIR/attest.key`). Agents have no terminal and are refused. Receipt and report paths must sit inside the ledger's folder and are stored relative, so the folder can be moved or shared. Receipts verify only where the key is; a teammate can point `GF_ATTEST_KEY_FILE` at a copy. Ledgers recorded before signing need a one-time `gf_ledger.py reattest --ledger experiment-ledger.jsonl`.

The resulting `EV-...` event ID must be put into a pillar behavior's `ledger_event_id` to qualify for evidence 3+. The behavioral observation must also have `kind`, `description`, `observed_at`, `source_or_artifact`, and `verified: true` in `evaluation.json`. A customer interview without an observed action is normally evidence 1, not 3. Do not place secret receipts or personally identifying interview data in public research folders. Store consent and retention rules separately where necessary.

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

Start Mission Control first (see top-level OBSERVABILITY.md), then:

```bash
python3 <skill>/scripts/gf_runs.py --project . plan
python3 <skill>/scripts/gf_runs.py --project . claim --role gf-problem
# Orchestrator actually delegates to runtime agent; write an authentic specialist summary.
python3 <skill>/scripts/gf_runs.py --project . complete --role gf-problem --artifact research/greenfield/idea/specialists/gf-problem.md
python3 <skill>/scripts/gf_runs.py --project . resume --freshness-hours 72
python3 <skill>/scripts/gf_runs.py --project . coverage --evaluation research/greenfield/idea/evaluation.json --verification-report research/greenfield/idea/source-verification.json
python3 <skill>/scripts/gf_runs.py --project . status --usd-per-million-tokens 5
```

No task is automatically launched. The skill orchestrator must actually invoke supported Claude or Codex delegation tools; the plan records claims/completions and resumes based on checksums + age. The red team task is blocked until the other eight have checkpointed. `--usd-per-million-tokens` is a user-supplied **blended illustrative rate**, and costs are approximate **only for reported tokens**; no official invoiced spend is inferred. The dashboard shows the number of artifact checkpoints and explicit claim coverage, not invented research percentages. Emit native lifecycle hooks rather than faking them.

## E. Portfolio analysis and transparent forecasting (P2)

Prepare a portfolio manifest following `assets/portfolio-template.json`. Reference **actual** `evaluation.json` files within the manifest directory; the portfolio re-scores each one, and an optional `decision.json` that disagrees leaves that idea unranked. Supply human founder-fit rationale; estimated build costs/weeks; one measurable next test with a precommitted threshold; estimated test cost, time, expected decision learning (ordinal 0–5); and optional financial scenario inputs.

```bash
python3 <skill>/scripts/gf_portfolio.py portfolio.json \
  --output portfolio-ranking.json --markdown PORTFOLIO.md
```

Results show a *heuristic priority index* under three sensitivity weighting sets (`balanced`, `capital_constrained`, `learning_first`). `NO_GO` and `RESEARCH_INCOMPLETE` cannot win a build ranking. Missing mandatory inputs are surfaced as an error, not replaced by synthetic values. Forecast low/base/high uses only user-provided buyer counts, 12-month per-buyer revenue, variable cost and fixed cost; outputs are deterministic arithmetic, **not predictive probabilities**. Never infer future customers, churn or margins absent evidence.

## Reproducible decision command

```bash
python3 <skill>/scripts/score_project.py evaluation.json --output decision.json
```

For v2, core evidence ≥3 must reference intact real ledger receipts, source-dependent claims must be reviewed before bounded pilot authorization, and model-specific gates must have supported evidence. A passing score is not permission to spend, ship, process personal data or ignore regulation.

To surface an explicitly assumed token-cost estimate in the dashboard, run `gf_runs.py --project . set-rate --usd-per-million-tokens <YOUR_BLENDED_RATE>`. If there are no provider-reported tokens, cost must remain unknown.
