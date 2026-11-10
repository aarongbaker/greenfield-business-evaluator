# From idea to Proceed: the founder journey

This guide takes one idea from install to an honest verdict. The tool steps take an afternoon. The experiments take weeks, and they are what move the score. **Interviews shape findings; receipts move the score.**

Throughout, `<slug>` is your run's folder name under `research/greenfield/`. If you installed from a clone without pipx, use `python3 .claude/skills/greenfield-business-evaluator/scripts/greenfield.py` (Codex-only installs: `.agents/skills/...`) wherever this guide says `greenfield`.

## The journey

| # | Stage | Who | What to run or do | Time |
| --- | --- | --- | --- | --- |
| 1 | Get the tool | Founder | `pipx install git+https://github.com/aarongbaker/greenfield-business-evaluator`, or the clone route in [install.md](install.md). Check that `python3 --version` reports 3.11 or later. On Windows, use WSL | 10 min |
| 2 | Install into your repo | Founder | `greenfield install --platform both --gitignore`, then restart the assistant | 5 min |
| 3 | Check | Founder | `greenfield doctor`. A missing signing key is fine: it is created on your first `sources check`, `evidence add` or `ledger record`. Back it up with the research folder | 1 min |
| 4 | Pick a profile and start | Founder with assistant | `greenfield profiles compare general services`, then `greenfield start --idea 'Bookkeeping for dental offices' --model services` | 15 min |
| 5 | Research | Assistant | `/greenfield-business-evaluator <idea>` (Claude Code) or `$greenfield-business-evaluator <idea>` (Codex). Watch it with `greenfield dashboard --open` | 1 to 3 h |
| 6 | First verdict and plan | Founder | `greenfield score`, `greenfield plan`, then `greenfield plan --add-experiments`. Each experiment gets a `success_threshold`, the bar you judge `--result` against later. Edit it now, not after the test | 10 min |
| 7 | Bring existing materials | Founder, then assistant | Put files containing personal data in `research/greenfield/<slug>/materials/raw/` and redact them first. Put only redacted or PII-free files in `research/greenfield/<slug>/materials/inbox/`, then ask the assistant to "re-assess with my materials" | 1 h to 1 day |
| 8 | Review sources | Assistant, then founder | `greenfield sources check --allow-network`, then `greenfield evidence status` lists each unreviewed claim with a ready review command. Open the URL before you type `supported` | 30 to 90 min |
| 9 | Run experiments | Founder | The steps from `greenfield plan`: a waitlist, a pre-sale, a paid pilot, LOIs, a channel test, gate materials | 1 to 4 weeks each |
| 10 | Record and attest | Founder at a terminal | Run `greenfield evidence redact`, then `greenfield evidence add` on each file and type back the code. Record failed tests too, with `--result fail` | 5 min per file |
| 11 | Re-assess findings | Assistant, then founder | Ask the assistant to "re-assess findings with my new receipts". It changes quality only on pillars the receipts touch, then stamps them with `greenfield evidence assessed problem value` | 30 min |
| 12 | Re-score | Either | `greenfield score`, `greenfield report`, `greenfield plan`. New claims need review: repeat stage 8 for them only | 5 min |
| 13 | Proceed, or stop or reframe | Founder | See [Both exits](#both-exits) | |
| 14 | Toward 100 | Founder | Get money or signatures on every pillar, then repeat purchases. See [The ladder to 100](#the-ladder-to-100) | 3 to 9 months |

An honest 75 typically takes **4 to 8 weeks** for general, bootstrapped_saas and services. Venture_startup and marketplace take **6 to 12 weeks**, because they need commitments from both sides or from several sub-segments. Regulated takes **8 to 16 weeks**, because it needs memos from counsel and other professionals.

The main path at a terminal, with fixture values:

```bash
greenfield start --idea 'Bookkeeping for dental offices' --model services --customer 'dental office managers' --geography US  # needs-research
greenfield plan --add-experiments  # needs-research
greenfield evidence experiment add --id EXP-4 --pillar value --pillar economics --hypothesis 'Dental offices pay for monthly books' --success-threshold '3 of 10 pay'  # needs-research
greenfield evidence redact research/greenfield/bookkeeping-for-dental-offices/materials/raw/stripe-presale.csv --drop-column email  # needs-research
greenfield evidence add research/greenfield/bookkeeping-for-dental-offices/materials/inbox/stripe-presale.redacted.csv --as presale --pillar value --pillar economics --gate paid_engagement --experiment EXP-4 --result pass --outcome '4 of 30 paid $49' --consent customer_terms --attester 'Ana Ruiz'  # needs-terminal
greenfield evidence assessed value economics  # needs-research
greenfield score  # needs-research
```

Put single quotes around any text that contains `$`. In double quotes, the shell would expand `$49` to nothing.

## Both exits

- **Proceed to bounded pilot.** The score must be 75 or more, and every gate must be met by a `pass` receipt or a reviewed claim. Every quality must be at or below what the pillar's receipts support (see [the rubric](how-scoring-works.md#the-quality-rubric)), and the pillar must have been re-assessed after its newest receipt. This verdict is permission for **one** bounded pilot with pass and fail thresholds set in advance. It is not permission to scale, hire, or raise money on the number.
- **Stop or reframe.** It appears as the headline on Validate before build in three cases:
  1. **A core assumption failed.** On a core pillar, the newest receipt at the highest evidence level (3 or more) came back `fail`.
  2. **A gate failed.** The newest receipt on an open gate came back `fail`. Change the plan and test again, or stop.
  3. **Findings cap the score.** Every core pillar has evidence 3 or more and nothing else is outstanding (re-assessment, reviews, gates, blockers), but no route reaches 75. The experiments did their job.

  Reframing starts a new run (`greenfield start --new --idea '<new framing>'`) with its own ledger. Old receipts stay as history. To count in the new run, they must be recorded again there.

Editing `project.idea` or `project.initial_customer` in place has the same effect as reframing. Earlier receipts show `receipt recorded for a different idea` and stop counting. `greenfield ledger reidea` carries receipts across a typo-sized fix only.

## What to bring, and what it earns

| Material | `--as` | Evidence up to | Pillars it can back | Gates it can close |
| --- | --- | --- | --- | --- |
| Interview notes, transcripts | none: leave in `materials/inbox/` | 1 | informs problem, value | none |
| Survey export | none: leave in `materials/inbox/` | 1 to 2 | informs problem, value, market | none |
| Competitor research | none: leave in `materials/inbox/` | 2, after the source review | informs competition, value | none |
| Public report, regulator page | a claim with `source_review` | 2 | informs market, timing, competition | `jurisdiction_review`, `venture_scale_market` |
| Landing-page or product analytics | `analytics` | 3 | problem, market, distribution, value, economics, competition, timing | `repeatable_channel`, `credible_growth_channel`, `liquidity_model` |
| Waitlist or double opt-in export | `signups` | 3 | problem, market, value | `repeatable_channel`, `credible_growth_channel`, `liquidity_model` |
| Ad or outreach report with cost | `channel` | 3 | distribution, market | `repeatable_channel`, `credible_growth_channel` |
| Stripe or checkout export, deposits | `presale` | 4 | problem, market, value, economics, distribution, competition, timing | `pricing_test`, `demand_commitments`, `paid_engagement` |
| Paid invoice, paid pilot contract | `invoice` | 4 | value, economics, problem, distribution, competition, timing | `paid_engagement`, `pricing_test`, `transaction_margin` |
| Signed LOI | `loi` | 4 | problem, value, market, competition | `demand_commitments`, `supply_commitments`, `funding_runway` |
| Supplier signed terms | `supplier-loi` | 4 | distribution, market | `supply_commitments` |
| Renewals, second orders | `repeat` | 5 | any pillar | `repeatable_channel`, `paid_engagement`, `pricing_test` |
| Prototype run, compliant delivery record | `prototype` | 4 | execution | `delivery_capacity`, `owner_dependence`, `professional_review` |
| Financial model, cost sheet, runway or SAM workbook | `model`, no `--pillar` | gate only | none | `delivery_margin`, `transaction_margin`, `funding_runway`, `liquidity_model`, `venture_scale_market` |
| Hours log, SOP with delivery by someone other than the founder | `ops-record` | 4 | execution | `delivery_capacity`, `owner_dependence` |
| Lawyer, clinician or compliance memo | `memo` | 4 | execution | `jurisdiction_review`, `compliance_path`, `data_and_safety`, `professional_review` |

`greenfield evidence types` prints this table for your profile. One file backs at most 2 core pillars and 3 pillars in all. One receipt closes one gate.

## Routes to 75

The planner (`greenfield plan`) picks the cheapest route from where you are. These are the typical routes for each profile. **Route A** puts an observed action (quality 4) on each core pillar and reviewed desk research (quality 3) on the rest. **Route B** puts money or signatures on the heaviest pillars.

| Profile | Route A | Route B | Receipts |
| --- | --- | --- | --- |
| general | 76.0 | 77.0 | A: `signups` → problem, market; `presale` → value, economics; `channel` → distribution |
| bootstrapped_saas | 77.0 | 80.8 | A: `signups`; `presale` closes `pricing_test`; two-cohort `channel` closes `repeatable_channel`; a cost-to-serve `model` closes `delivery_margin` |
| venture_startup | 75.0 (no slack; the planner recommends B) | 81.0 | B: `loi` from two sub-segments; a paid-pilot `invoice`; `channel` closes `credible_growth_channel`; SAM and runway `model` files close the other gates |
| marketplace | 75.8 | 78.8 | `supplier-loi` closes `supply_commitments`; buyer `presale` closes `demand_commitments`; `invoice` closes `transaction_margin`; liquidity `model` |
| services | 76.6 | 82.8 | A: booked calls (`analytics`); `invoice` closes `paid_engagement`; referral `channel`; two `ops-record` files close `delivery_capacity` and `owner_dependence` |
| regulated | 71.6 ✗ | R1 81.6, R2 78.6 | Execution carries 25 points, so route A fails. R1 adds a `prototype` compliant delivery record for execution at evidence 4. R2 leads with a regulated buyer's paid `invoice`. Each of the four gates needs its own item (a reviewed regulator claim, a counsel `memo`, a data-review `memo`, the signed-off `prototype`) |

`greenfield demo --proceed` scores a fictional services run that follows route A to Proceed at 76.6.

## The ladder to 100

A score of 100 means all eight pillars are at quality 5. Getting there honestly takes evidence 4 (money, signatures or proven delivery) on every pillar. The ideal is evidence 5 (repeat purchases) on the core pillars. DECISION.md says which kind of 100 you have.

| Pillar | Quality 3 (evidence 2) | Quality 4 (evidence 3) | Quality 5 (evidence 4) | Ideal (evidence 5) |
| --- | --- | --- | --- | --- |
| problem | Reviewed sources plus 5+ interviews | Cold visitors sign up or book (`signups`) | 3+ buyers pay or sign (`presale`, `loi`) | They renew (`repeat`) |
| market | Bottom-up count from reviewed sources | Conversion from a list of the sized segment (`channel`) | Commitments from 2+ sub-segments | Repeat across segments |
| value | Price reactions beat the alternative | Real use or demo requests (`analytics`) | Paid at the intended price (`presale`, `invoice`) | Renewal at that price |
| economics | Reviewed price and cost | Checkout starts at the tested price (`analytics`) | Paid price exceeds measured cost (`invoice`) | Retention-driven lifetime value |
| distribution | Named channel with benchmarks | Signups at a known cost (`channel`) | The channel produced payers (`presale`) | A second cohort repeats |
| competition | Teardown of 3+ alternatives | Buyers chose you side by side (`analytics`) | A switcher pays or signs | A switcher renews |
| execution | Reviewed delivery plan | A prototype works (`prototype`) | Compliant delivery, signed off (`prototype`, `memo`) | Repeat delivery to payers |
| timing | Reviewed "why now" sources | Buyers act citing the trigger (`analytics`) | Buyers pay citing the trigger (`presale`) | Repeat purchases |

The scores are uncalibrated triage. A 100 does not mean the business will work, and a 75 is not a 75% chance. The score tells you which assumption to test next and when a bounded pilot is defensible.

## When a receipt is rejected

`evidence add` changes nothing when it refuses, and it prints the allowed values. The usual causes:

- **More than 2 core pillars or 3 pillars in all.** Split the claim across separate experiments and files.
- **The pillar or gate is not allowed for that `--as` type.** Check `greenfield evidence types`.
- **No `--experiment`, or the experiment doesn't cover the pillar.** The error prints a ready `greenfield evidence experiment add` command.
- **Personal data found.** Run the printed `greenfield evidence redact` command, then record the redacted copy. If you have a reason to keep the data, use `--keep-pii REASON`.
- **The file was already recorded, or most of its rows overlap an earlier receipt.** It counts once.
- **`interviews`, `survey` or `competitor-research`.** These are not receipts. Leave them in `materials/inbox/`.

A receipt edited after it was recorded shows `✕` in Mission Control and stops counting. Don't edit files in `receipts/`.

## If you recorded personal data by mistake

1. Record a redacted copy with the same kind, pillars and result, adding `--replaces EV-old`.
2. Relink it with `greenfield evidence link`.
3. Delete the old file from `receipts/`.

The old id is retired. Without `--replaces`, its signed result still counts. Hypothesis, outcome and attester text are stored in the ledger in plain text and can't be removed later, so keep customer data out of them.

The tool finds emails, phone numbers, card numbers and named CSV columns. **It does not find person names in free text.** Remove names from interview notes and transcripts by hand. Everything in `materials/inbox/` is read by the assistant and sent to your AI provider.
