# How scoring works

The scorer is a small, deterministic program: `greenfield score` reads `evaluation.json` and writes `decision.json`. The same input always gives the same verdict, so anyone can re-run it and check the result. The research agents fill in `evaluation.json`; they never decide the verdict themselves.

## Eight pillars

Every idea is researched and scored on eight pillars, one research role each:

| Pillar | Question it answers | Role |
|---|---|---|
| Problem | Is the pain real, frequent and costly for a specific buyer? | Problem Discovery |
| Market | How many such buyers exist, and can you reach the first ones? | Market & ICP |
| Value | Is your offer clearly better than what they do today? | Customer Value |
| Economics | Do price, cost to serve and cost to acquire leave a margin? | Unit Economics |
| Distribution | Is there a channel that reaches buyers repeatably? | Distribution & GTM |
| Competition | Who else solves this, and why would buyers switch? | Competitive Intelligence |
| Execution | Can this team build and run it, legally and safely? | Execution & Founder Fit |
| Timing | Why now, and what could close the window? | Timing & Survivability |

An independent red team then challenges the findings before anything is scored.

## Quality and evidence are separate

Each pillar gets two scores from 0 to 5:

- **Quality**: how attractive the pillar looks, based on what the research found.
- **Evidence**: how strong the proof behind that view is.

Think of buying a house. Quality is how good the house looks in the listing; evidence is whether you have had it inspected. A beautiful listing with no inspection is an attractive speculation, not a safe purchase. Greenfield never multiplies the two into one number.

| Evidence | What it takes |
|---|---|
| 0 | Founder belief, a slide deck, a made-up model |
| 1 | Interviews, surveys or anecdotes, plus desk research |
| 2 | Reactions to a real artifact, price comparisons, original statistics |
| 3 | A target customer took a real low-stakes action, recorded in the ledger |
| 4 | A meaningful commitment: a signed letter of intent, a paid pre-sale |
| 5 | Real sales, renewals or repeat purchases under normal conditions |

Evidence 3 and above needs a behavior receipt in the experiment ledger, signed off by a person at a terminal. Browsing alone can never get a pillar past 2. See [Evidence and the ledger](evidence.md).

An unknown pillar is left as `null`, not guessed. The weighted quality score is only computed when all eight pillars have a quality score.

## Weights and business-model profiles

Weighted quality is `sum(weight × quality / 5)` across the pillars, out of 100. The weights depend on the business model you set in `project.business_model` (or with `greenfield start --model`):

| Profile | Problem | Market | Value | Economics | Distribution | Competition | Execution | Timing | Pilot gates |
|---|---|---|---|---|---|---|---|---|---|
| `general` | 20 | 15 | 15 | 15 | 15 | 10 | 5 | 5 |  |
| `bootstrapped_saas` | 20 | 8 | 15 | 22 | 20 | 7 | 5 | 3 | `pricing_test`, `delivery_margin`, `repeatable_channel` |
| `venture_startup` | 18 | 21 | 14 | 9 | 13 | 9 | 5 | 11 | `venture_scale_market`, `credible_growth_channel`, `funding_runway` |
| `marketplace` | 16 | 15 | 13 | 15 | 20 | 10 | 7 | 4 | `supply_commitments`, `demand_commitments`, `liquidity_model`, `transaction_margin` |
| `services` | 20 | 8 | 18 | 20 | 17 | 8 | 7 | 2 | `paid_engagement`, `delivery_capacity`, `owner_dependence` |
| `regulated` | 13 | 10 | 10 | 15 | 10 | 6 | 25 | 11 | `jurisdiction_review`, `compliance_path`, `data_and_safety`, `professional_review` |

```bash
greenfield profiles
greenfield profiles show marketplace
greenfield profiles compare bootstrapped_saas venture_startup
```

Pilot gates are extra conditions a profile needs before it can recommend a pilot, such as a real pricing test for a bootstrapped SaaS. Each passed gate must point at a ledger receipt or a human-reviewed source. `regulated` always needs independent professional review; the tool cannot give legal or clinical clearance.

## Verdicts

The scorer applies these rules in order and stops at the first that matches:

1. **No go** if a sourced, confirmed fatal blocker has no credible remedy, whatever the scores.
2. **Research incomplete** if there was no live web research or any pillar's quality is unknown.
3. **Pivot** if weighted quality is below 50 and a core pillar (problem, market, value, economics or distribution) has quality 1 or less backed by evidence 3 or more.
4. **Proceed to bounded pilot** only if weighted quality is at least 75, all five core pillars have quality 3+ and evidence 3+ from recorded behavior, no fatal blocker is open, every profile gate passed, and every source-dependent claim has a human review.
5. **Validate before build** otherwise.

| Verdict | Meaning |
|---|---|
| Research incomplete | Not a launch decision yet |
| No go | A confirmed fatal blocker overrides the score |
| Pivot | Evidence shows a severe core weakness |
| Validate before build | Run the next experiment before writing code |
| Proceed to bounded pilot | Core gates met. Pilot only, not scale |

Proceed to bounded pilot is meant to be rare for an idea with no customers yet. It is permission to consider a small, time-boxed pilot, not to spend money or scale. A plausible but unconfirmed fatal blocker also blocks a pilot until someone investigates it.

These weights and thresholds are design choices for triage. They have not been calibrated against real business outcomes, and a score of 80 does not mean an 80% chance of success.

## A worked example

The bundled demo evaluation (route planning for independent commercial laundries, under `skill/assets/demo-research/`) has these pillar scores:

| Pillar | Weight | Quality | Evidence | Contribution |
|---|---|---|---|---|
| Problem | 20 | 4 | 2 | 16 |
| Market | 15 | 4 | 2 | 12 |
| Value | 15 | 4 | 2 | 12 |
| Economics | 15 | 3 | 2 | 9 |
| Distribution | 15 | 3 | 2 | 9 |
| Competition | 10 | 4 | 2 | 8 |
| Execution | 5 | 4 | 2 | 4 |
| Timing | 5 | 3 | 2 | 3 |

Weighted quality is 73 out of 100 and the evidence average is 2. The idea looks reasonable in the listing, but nobody has inspected it: no core pillar has evidence 3. The verdict is **Validate before build**, and `decision.json` names what would change it: a problem quality of 5, and evidence 3 on the five core pillars from real customer behavior.

## Read the result

`greenfield score` prints a one-screen summary on a terminal and JSON when piped. `greenfield report` writes the same verdict and scorecard at the top of `DECISION.md`, between generated markers, so the memo can never disagree with `decision.json`. Every warning in the output names the missing field or evidence, and `next_step` says what to do first.
