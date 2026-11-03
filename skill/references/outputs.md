# Output contracts

Do not invent artifacts that do not exist. `evaluation.json` is the canonical handoff for deterministic scoring; do not duplicate different scores in different documents. Source IDs, not invented citations, link the artifacts.

## `DECISION.md` — read this first

```markdown
# [Idea] — Greenfield investment memo
As of: [ISO date] | Target: [ICP/geography] | Depth: [...] | Execution: [parallel N actual / sequential fallback] | Web: [live / blocked]
**Decision:** NO_GO / PIVOT / VALIDATE_BEFORE_BUILD / PROCEED_TO_BOUNDED_PILOT
**Nature of decision:** [desktop only / first-party data included]; a pilot is not a scaling endorsement.

## In one paragraph
For [buyer] with [problem], [idea] is [compelling / unclear / weak] because [2-3 evidence-backed points]. The most important unresolved assumption is [...].

## Pillar scorecard
| Pillar | Quality (0–5) | Evidence (0–5) | Core finding | Claim IDs |
...
Quality weighted score: [...] or not available. Evidence average: [...].

## Market opportunity, economics, competition
3–5 most decision-relevant findings with URLs, dates and caveats.

## Dissent and red-team findings
[strongest negative case, where evidence conflicts]

## Must-be-true assumptions and stop conditions
...

## Decision and next bet
[one smallest test, budget/time estimate explicitly assumptions, pass/fail outcome, owner]
```

## `MARKET_RESEARCH.md`

- Brief and research charter; target geography/segment, buyer/user/payer roles.
- 8 sections matching the 8 pillars. In each: positive case, contrary case, numerical proof and exact sources, evidence gap, one falsification experiment.
- Competitor alternatives matrix: name, segment, primary URL, public pricing with units/date or 'not verified', critical differentiator and switching issue.
- Market size TAM/SAM/SOM **bottom up**, including low/base/high assumptions and double-counting caveats; zero unsupported headline figures.
- Unit economic contribution and cost sensitivity with assumptions, not magical CAC or churn.
- Distribution funnel and compliance/operations.
- Timing and explicit 'why not now'.
- Contradictory sources and limits.

## `EVIDENCE.md`

A table with claim ID, pillar, exact statement, class `fact|estimate|inference|assumption`, origin and independence, primary URL or 'none', publisher, publication and access date, geographic scope and limitations. Distinguish linked direct field observations from agent inference. List competing evidence and unanswered questions. Each consequential quantitative statement in the other documents should point here and cite a source inline.

## `EXPERIMENTS.md`

3–7 test cards, ordered by **severity of assumption × uncertainty × expected learning / cost** (a qualitative heuristic). Fields: unique ID, hypothesis, evidence so far, stakeholder with recruiting channel, minimal intervention, measurable observable output, numeric target chosen *before* test (labeled decision heuristic), failure/stop threshold, proposed duration and spending cap, consent/compliance concerns, and exact decision it affects. Interviews support problem discovery, not demonstrated revenue. Nonbinding LOI weaker than paid and delivered purchase. Never promise results.

## `evaluation.json` machine contract (v2)

Copy `assets/evaluation-template.json`, populate from original evidence. Minimum keys:

- `schema_version`: `2.0`. `project` object with `name`, `idea`, `initial_customer`, `geography`, `business_type`, `goal`, `business_model` (one of six profiles).
- `as_of`: ISO date.
- `execution`: `web_used` boolean, `subagents_actual` integer >=0, `mode` string, `customer_validation_performed` boolean.
- `pillars`: object with **exactly** `problem`, `market`, `value`, `economics`, `distribution`, `competition`, `execution`, `timing`. For each: `quality`: null or 0–5 integer, `evidence`: 0–5 integer, `finding` string, `claim_ids` string array, `behaviors` array.
- `claims`: array of unique `id`, `pillar`, `statement`, `classification` (`fact|estimate|inference|assumption`), `source_url` (empty string if unverified), `source_title`, `published_date`, `accessed_date`, `independent_origin`, `notes`. A public `fact` must have an HTTP(S) source, and estimates must explain formulas in notes and reference source IDs.
- `hard_blockers`: array of `id`, `status` (`confirmed|plausible|resolved`), `fatal` boolean, `finding`, `source_ids` (claim IDs), `mitigation`.
- `experiments`: array of proposed experiments with ID, hypothesis, measure, pass/fail, proposed budget/time.
- `market_model`: optional modeled TAM/SAM/SOM ranges, explicitly hypothetical, each with units/currency/inputs/sources.
- `evidence_ledger`: local relative path to append-only experiment history; behavior scores of 3+ require verified `ledger_event_id` matching the pillar, and actual local receipt checksum and human attestation.
- `verification_report`: local relative path to source retrieval/quotation output, with matching human `source_review` records for material public claims before a bounded pilot.
- `pilot_gates`: policy-specific named objects `{ "passed": true|false, "evidence_ids": ["EV-...", "C1"] }` where affirmative gates must link to valid receipts or human-reviewed source claims.

Run `python3 <skill dir>/scripts/greenfield.py score <evaluation.json> --output <decision.json> --json` (always pass `--json`: without it, a terminal gets a text summary instead). The command validates the shape and writes decision plus warnings. `decision.json` carries `decision` (the code), `verdict_label`, a deterministic `headline` (at most 90 characters) and `next_step`, and `source_review_pending` (true while public citations still need a human source review). `memo_label` and `source_review_gate_open` (which reads true when no review is pending) are deprecated, listed in `deprecated_fields`, and removed in 3.0. run `greenfield sources check` separately to check public source accessibility, excerpts, age and origins, then human review. The scorer checks source review / behavioral ledgers but does not itself fetch URLs or determine factual truth.

## v2 additional artifacts

See [v2 workflows](v2-workflows.md) for `source-verification.json`, `experiment-ledger.jsonl`, `task-manifest.json`, and optional `portfolio-ranking.json`/`PORTFOLIO.md`. The dossier must mark source evidence, verified local receipts and independent human judgments separately. No agent should author a fictitious receipt or human approval.
