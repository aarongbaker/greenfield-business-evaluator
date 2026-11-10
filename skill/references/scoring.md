> For agents running the skill. People: read [docs/how-scoring-works.md](../../docs/how-scoring-works.md) instead.

# Decision policy v2.0 — transparent heuristics, not an empirical success predictor

The default `general` weights sum to 100. **Business-specific profiles override these weights**; consult `scripts/gf_profiles.py` and [v2 workflows](v2-workflows.md).

| Pillar | Weight |
|---|---:|
| problem | 20 |
| market | 15 |
| value | 15 |
| economics | 15 |
| distribution | 15 |
| competition | 10 |
| execution | 5 |
| timing | 5 |

These weights and thresholds are **design choices** for triage, not a validated predictive scoring model. Allow contextual commentary; do not imply score 80 = 80% success probability.

## Opportunity quality (0–5)

- 0 = compelling negative evidence or structurally unattractive.
- 1 = serious weaknesses outweigh opportunity; may need a pivot.
- 2 = marginal / narrow / unfavorable economics or distribution.
- 3 = plausible, with meaningful unresolved questions.
- 4 = strong and defensible conditional thesis.
- 5 = unusually compelling on tested criteria; not a guarantee.

Quality is a finding, held to the evidence by a rubric (new in this release). A pillar's quality should not exceed its **rubric level**, which its receipts set:

| Receipt kind | Highest evidence | Rubric level: `pass` / `mixed` / `fail` |
| --- | --- | --- |
| `customer_action` | 3 | 4 / 3 / 2 |
| `paid_test`, `signed_commitment` | 4 | 5 / 4 / 2 |
| `feasibility_proof` (execution only) | 4 | 5 / 4 / 2 |
| `repeat_purchase` | 5 | 5 / 5 / 2 |
| no receipt (interviews, surveys, reviewed sources) | 2 | 3 |

The rubric level comes from the newest receipt at the highest evidence level on the pillar, read from the signed ledger whether linked or not, so a newer `fail` caps it at 2. The scorer warns "quality above evidence" for every pillar over its rubric level, and Proceed requires every pillar at or below it, re-assessed (`greenfield evidence assessed PILLAR`) after its newest receipt. Label assumptions. An unknown dimension is `quality: null`, not an arbitrary 3. Scoring only runs when quality has an integer 0–5 for all pillars. If incomplete, set `quality: null` and return `RESEARCH_INCOMPLETE` plus gaps without a misleading weighted total.

## Evidence (0–5) — inspired by Strategyzer (Sept 2026), operationalized for this skill

- 0 = no real applicable evidence; founder conjecture, slide deck, internally fabricated model.
- 1 = credible interview / survey self-reports or anecdotes, plus contextual market desk research; not behavioral proof.
- 2 = verifiable reactions to a real artifact, pricing comparison, original statistics that directly substantiate the market constraint; **still insufficient to prove this product's adoption**.
- 3 = observed, verifiable low-stakes target-customer action, or executed operational proof directly tied to pillar; an independently cited statistic about incumbents alone isn't this behavior.
- 4 = executed meaningful commitment, e.g., real nonbinding signed LOI from a budget holder, actual paid pre-sale (with caveats), formal procurement step, or verifiable delivery economics.
- 5 = relevant real-market behavior under natural conditions, e.g., completed sales and renewals, repeat purchasing, or repeated operational results in representative conditions.

For EVERY pillar with `evidence >=3`, `behaviors` must contain at least one concrete entry with `description`, `source_or_artifact`, `observed_at`, `kind` and `verified: true`. In schema 2.0, `ledger_event_id` must also refer to a checksum-valid, named-human-attested real behavior receipt in `evidence_ledger`. This checks local artifacts and attestation, **not independent proof** the event happened; the reviewer must inspect it. A bare `verified: true` is insufficient. Market size government counts can score 2, but not 3 for the behavior of adopting the new product. The skill can't perform customer validation purely by browsing.

## Formula and decisions

`weighted_quality_0_to_100 = sum(weight_i * quality_i / 5)` (only if all quality values known). `evidence_average_0_to_5 = arithmetic mean(evidence_i)`; present separately, never multiply scores into a faux precision success chance.

Mandatory `hard_blockers` objects have fields `status` (`confirmed`, `plausible`, `resolved`), `fatal` (boolean), `finding`, `source_ids`, `mitigation`. A confirmed fatal blocker with no credible remedy triggers `NO_GO`, regardless of scores. A plausible fatal blocker is not proven; it blocks any pilot until investigated.

Decision rule (for transparent conservative triage):

1. `NO_GO` if a sourced and **confirmed** fatal blocker remains unmitigated. A blocker without a source should be `plausible`, not `confirmed`.
2. `RESEARCH_INCOMPLETE` if browsing unavailable or pillar quality is unknown. This is an internal machine-state, displayed in the user memo as `VALIDATE_BEFORE_BUILD (research incomplete)`.
3. `PIVOT` if weighted score <50 AND a *core* pillar (problem, market, value, economics or distribution) has quality <=1 with evidence >=3. The evidence must support a weakness, not be positive by default.
4. `PROCEED_TO_BOUNDED_PILOT` only if: weighted score >=75; all five core pillars have quality >=3; all five core pillars have evidence >=3 from documented directly relevant observed behavior; no confirmed or plausible unresolved fatal blocker; live research performed. This is permission to **consider** a bounded pilot, not to spend money automatically and not to scale.
5. Otherwise `VALIDATE_BEFORE_BUILD`.

`PROCEED_TO_BOUNDED_PILOT` should be rare for genuinely unbuilt greenfield products without customer trials; this is intentional. Users may still rationally build small prototypes to obtain missing evidence after seeing the experimental plan. The decision should distinguish a prototype-as-test from a committed full product build.

## Assumptions, ranges, and confidence

Add sensitivity scenarios and list assumptions separately. Never infer conversion or churn from unrelated benchmarks. A high quality score with low evidence is an **attractive speculation**, not an investment-ready venture. Include `top_reversal_observation` in the memo.

## Fatality and source checks

Fatal blockers include clearly established insurmountable legal prohibitions, unavailability of the essential asset without remedy, impossible contribution economics with real observations, or safety obligations that cannot be reasonably satisfied. Normal competition, lack of uniqueness, and unvalidated demand are serious challenges, not automatic fatal blockers. The red team should recommend independent legal/compliance review where needed.

## v2 additional pilot gates

Business-specific profiles (SaaS, venture, marketplace, services, regulated) require their named `pilot_gates` to have `passed: true` backed by supporting human-reviewed claim IDs or attested ledger receipt event IDs. Any absent, unsupported or failed gate means **VALIDATE_BEFORE_BUILD** at best. For public factual claims linked to pillars, a retrieved source report and human source-review entries are required to approve a bounded pilot; matching a quotation is not automatic truth verification. Source reports should remain at the `verification_report` path relative to evaluation. Source review entries must match its exact SHA-256 digest. Absence of first-party behavioral evidence means a greenfield desk-only evaluation cannot silently progress to pilot.

The policy creates conservative triage decisions. Thresholds and weights are not calibrated using real business outcomes. Scores must **not** be described as launch probabilities.
