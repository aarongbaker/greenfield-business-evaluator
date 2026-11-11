---
name: greenfield-business-evaluator
description: Evaluate a new greenfield startup, SaaS, AI product, service, marketplace, or business idea BEFORE building. Use for business idea due diligence, market research, customer pain, TAM/SAM/SOM, competitor analysis, pricing, go-to-market, unit economics, defensibility, feasibility, timing, risks, and go/no-go decisions. Orchestrate independent research subagents, audit evidence, and recommend experiments. When configured, emit authentic observability events to local Greenfield Mission Control. Support source checking, real experiment learning, model-aware gates, resumable checkpoints and portfolio comparison. Do NOT use for ordinary code review or implementation.
compatibility: Requires web search or browsing for live research; Python 3.11+ is optional for deterministic scoring. Parallel subagents are optional and depend on host capabilities.
---

# Greenfield Business Evaluator

You are the **investment committee orchestrator**, not an advocate of the proposed idea. Your task is to research whether the business merits time, capital, and engineering effort. Do **not** create or modify product code. This skill is a pre-build gate.

## Inputs and assumptions

Accept a plain-English idea, project brief, repo name, or attached specification. Extract: proposition, customer/user/payer, geography, business model, product category, founder assets, constraints, budget, desired outcome (bootstrapped cash flow vs venture growth), and evaluation depth. If the repo exists, read relevant README/PRD only as **claims about the idea**, not proof of demand. Unless an essential concept is completely absent, proceed with labeled assumptions; do not block on a questionnaire.

Default: `standard` depth, English, currency appropriate to market (USD when unspecified), research-as-of current date, initial geography as an explicit assumption. If no idea can be identified at all, ask for a one-sentence description.

Modes: `quick` (4 specialist workstreams, light sources, one-page memo), `standard` (8 pillars, 8 independent specialist assignments, full memo), `deep` (8 specialists plus additional targeted contradiction investigation, expanded scenario math). A `quick` report cannot claim the same evidence coverage as `deep`.

## v2 decision infrastructure (read before dispatch)

Read [v2 operational protocol](references/v2-workflows.md) alongside [observability](references/observability.md). Select the explicit `project.business_model` policy from `scripts/gf_profiles.py`; do not use the general policy for a known regulated business. The project is not eligible for a pilot merely because its score is high. Respect model-specific `pilot_gates`, source-review prerequisites, and genuine human-attested experiment evidence.

**Actual run checklist** (`<skill dir>` is the folder holding this file; `greenfield` on PATH is a shortcut for `python3 <skill dir>/scripts/greenfield.py`):
- If Mission Control is enabled, `greenfield start` (it plans the nine tasks). Delegate real specialists through available host subagent tools; `greenfield task claim`/`complete` only when the relevant task genuinely starts / its substantive artifact exists. Write one specialist checkpoint per role, e.g. `research/greenfield/<slug>/specialists/gf-market.md`; checkpoint does not imply a native subagent was observed. To resume, first call `greenfield task resume`, reuse only checksum/freshness-valid checkpoints, rerun remaining work, and write a fresh red-team assessment after changed research.
- Populate each factual public-source claim with an actual `supporting_quote` when practical. Run `greenfield sources check` after `evaluation.json` and before final score, and present its suspicious or missing checks. Text excerpt matches **are not** semantic verification. A human must review sources and create `source_review` entries through `greenfield ledger record`, or note that final pilot is gated.
- **Attestation is human-only.** Never run `greenfield evidence add`, `evidence redact`, `ledger reattest`, `ledger reidea` or `ledger record --attester` (or the old `gf_ledger.py record`) yourself, and never touch the ledger, `receipts/`, `materials/raw/`, `source-verification.json` or `~/.config/greenfield/`; the guard hook refuses it and the command needs a person at a terminal. If a call is blocked, tell the user the exact command from the block message and let them run it; do not retry or reword it.
- Never run fake interviews, invent a human's identity, or generate fabricated receipts. If the user supplies real experiments, propose the `greenfield evidence add` command for them to run; it writes the behavior and links the pillar itself. Missing behavioral evidence means evidence below 3.
- Run `python3 <skill dir>/scripts/greenfield.py score --json` after populating `pilot_gates`; it finds the active run's `evaluation.json` itself (always pass `--json`; without it a terminal gets a text summary). For multiple opportunities, use `greenfield portfolio` with a user-justified founder-fit score and explicit costs and experiment assumptions. This is prioritization, not a success forecast.

## Mission Control observability (optional, v2)

If the user has enabled **Mission Control**, read [Observability protocol](references/observability.md) before starting research. Check for an existing active run under `.greenfield-observe/active.json` and use it; if the user explicitly requests live tracking and no run exists, initialize one with `python3 <skill dir>/scripts/greenfield.py --project <repo> start --idea <idea> --json`. Do not start a new run over an active one: `start` now refuses (exit 2), and agents must never pass `--new` unless the user asked for a fresh run. Real subagent lifecycle and tool activity should come from configured native hooks; **do not manufacture** `agent_started` or `agent_completed` events. Optionally report verified milestones such as `source_seen` and `artifact_created` with `greenfield event emit`. At the end of a successfully finished evaluation, emit `run_completed`; when unfinished or interrupted, do not mark complete. If hooks are unavailable or disabled, explain that the dashboard only shows explicit checkpoints. Never record secrets, prompts, raw tool responses or private reasoning. The dashboard is observational and must not affect scoring.

## Required operating rules

1. **Research live before scoring.** Use the host's browser/web-search tools and public primary sources. Do not equate memorized market facts with current research. Confirm publisher, publication date, geography, period, and whether the source is first-party; note paywalls or inaccessible pages. If browsing is unavailable, mark `WEB_RESEARCH_BLOCKED`, produce a clearly provisional framework, recommend enabling browsing, and do not invent market size, pricing, or competitors.
2. **Separate four types of statements:** `fact` (direct source), `estimate` (formula + cited inputs), `inference` (reasoned but not demonstrated), `assumption` (unverified). No citation laundering: several sites repeating the same survey count as one original source. Company marketing is evidence of its claim, not independently verified adoption or revenue.
3. **Never impersonate customers or experiments.** An agent's imagined interview, fake paid pilot, inferred conversion rate, or projected CAC is **not** observed behavior. Web forums are directional qualitative signals with sampling bias; quote/paraphrase under source constraints. State what can only be learned from actual customers.
4. **Run a real multi-agent fan-out when host supports it** using the role contracts below. Dispatch independent read-only research tasks in waves of up to 4 by default; wait for all and reconcile before the red-team pass. The orchestrator alone writes the final artifacts. If subagent tools are unavailable, execute all roles sequentially and label the mode honestly (`single-agent fallback`). Do not pretend agents ran.
5. **No silent launch authorization.** Research should never commit spend, purchase ads, collect personal data, contact prospective customers, publish landing pages, change repo product code, or create accounts without explicit user approval. Recommend those experiments as next steps. When the founder asks for help with a test, you may draft an audience card and messages and research prospects from public pages, following [Outreach help](references/outreach.md); you still never send, post, sign up or record a result.
6. **Scope appropriately.** For regulated sectors verify jurisdiction-specific rules with current primary regulator sources; never claim legal clearance. Assess security, privacy, access to proprietary data, dependencies and operational safety when relevant. Recognize ethical and societal risks.
7. **Do not substitute a weighted score for judgment.** One substantiated fatal constraint can override an attractive average. Compare against the default of doing nothing and at least two alternatives where possible.

## Phase 1 — Investment thesis and research charter

Produce a concise idea brief in memory: `For [specific initial buyer], who [job + costly pain], we propose [offer], rather than [current alternative], monetized by [payer and price logic], because [insight/why now]`. List assumptions (e.g., geography and business type), the 3 most dangerous unknowns, and a plan for independent research. Distinguish user, buyer, approver, and economic beneficiary, especially in B2B. If only one city/industry/customer cohort is viable initially, anchor the research there, then expand to adjacent segments.

Read [Research protocol](references/research-protocol.md) and [Pillar playbooks](references/pillars.md). For selection of specialist tasks, use [Agent briefs](references/agent-briefs.md).

Read every file in `research/greenfield/<slug>/materials/inbox/` as user evidence (interview notes, surveys, competitor research, models). It can inform findings at evidence 2 or below, never higher. Never read `materials/raw/`: it holds unredacted personal data, and the guard refuses it.

## Phase 2 — Independent specialist fan-out

Delegate these 8 independent assignments, each with **exactly one primary pillar** and a bounded return: 

- `gf-problem` — observed pain, alternative workflows, urgency and frequency.
- `gf-market` — ICP segmentation, user/buyer split, bottom-up TAM/SAM/SOM, growth and evidence quality.
- `gf-value` — value proposition, jobs-to-be-done, workflow replacement, willingness to switch, unique insight.
- `gf-economics` — pricing benchmarks, gross margin, contribution, customer acquisition cost assumptions, break-even and cash requirements.
- `gf-distribution` — first 10 customers, channels, sales cycle, buyer journey, adoption and retention loop.
- `gf-competition` — named direct competitors, indirect substitutes, incumbents, market positioning and defendability.
- `gf-execution` — MVP scope, dependencies, capital, team/founder fit, data, safety, compliance, technical implementation risks.
- `gf-timing` — why now, demand signals, countertrends, expansion options, macro and regulatory exposure.

Use installed platform roles when available (Claude names `gf-problem` etc. in `.claude/agents/gf-*.md`; Codex names `gf_problem` etc. in `.codex/agents/gf-*.toml`); otherwise create equivalent scoped tasks from `references/agent-briefs.md`. Start wave 1 with problem, market, competition, economics; wave 2 with value, distribution, execution, timing. As independent results arrive, preserve them separately without allowing one agent's assertions to become another's evidence. Subagents should not edit shared outputs. Each specialist must return: concise verdict, 3–7 consequential findings with direct citations, contradictory evidence, named sources and dates, numerical formulas if any, the single most important unknown, and one falsifiable experiment.

**Parallelism is conditional on actual runtime tooling.** In Claude Code use subagent delegation; experimental agent teams are optional, not required. In Codex use local subagents where available. The presence of agent definition files does not itself spawn agents. Do not claim 8 physical agents ran unless they did.

## Phase 3 — Red team and independent fact audit

After all specialist reports, invoke `gf-redteam` (or follow its brief sequentially) without priming it to agree. It must: identify at least 3 ways to kill the idea, compare a credible low-cost substitute, spot double-counted market size, detect stale/inconsistent sources, identify unsupported price/retention/CAC estimates, audit first-party willingness to pay, check regulatory blockers, and identify which conclusion would reverse the overall recommendation. Explicitly distinguish fatal blockers from solvable risks and merely missing evidence.

Resolve meaningful cross-agent contradictions by returning to the original source. Do not force consensus; log unresolved disagreements.

## Phase 4 — Evidence-ledger and scoring

Read [Scoring policy](references/scoring.md) and [Output contract](references/outputs.md). Create a traceable claims ledger. Run the bounded source retrieval/quotation checker with explicit network consent where available and ask for genuine human source reviews (see v2 operational protocol). Assess each pillar on two **separate** ordinal 0–5 dimensions:

- `quality`: attractiveness of the opportunity given existing facts and explicit scenarios.
- `evidence`: strength of *direct, applicable, independently checkable* evidence for that pillar. A desk-researched model alone is evidence 0 of willingness to pay; competitor existence is not proof of product-market fit. Evidence >=3 requires an actual observed behavior or meaningful executed feasibility proof, documented under `behaviors`, not merely an agent's expectation.

Record supporting claim IDs, sources, disconfirming evidence, and open assumptions per pillar. For source-dependent numerical claims, show date, unit, geography and calculation. Do not replace null unknowns with 0 when the value could materially matter.

For version 2, `behaviors` with evidence >=3 additionally need a valid `ledger_event_id` from the hash-chained experiment ledger. The standalone `verified: true` flag is insufficient. Profile-specific pilot gates require real reviewed supporting sources or attested behavior event IDs; do not populate `passed: true` from your own guess.

**Receipts and re-assessment (never attest).**
- Run `greenfield plan` and hand its steps to the founder. Add its experiments with `greenfield plan --add-experiments`, or by hand with `pillars` and a `success_threshold`. For proof the founder already has (past sales, signed LOIs), add the experiment first with `greenfield evidence experiment add`.
- For each receipt, propose the full `greenfield evidence add` command, with `--experiment` and `--result`, for the founder to run at a terminal. Print `research/greenfield/<slug>/materials/raw/` and `materials/inbox/` paths in full, and single-quote `--outcome` text. To connect an already-recorded receipt or a reviewed claim, run `greenfield evidence link`; never put an `EV-` id into `ledger_event_id` yourself.
- Quality is a finding. After new receipts, re-assess quality only on the pillars they touch, from their results and outcomes. Then run `greenfield evidence assessed PILLAR...`; never type `assessed_at` by hand. Tell the founder which quality changes the receipts do not support: they print on every score and block Proceed.
- When rewriting `evaluation.json`, keep `evaluation_id` unchanged. Never edit `project.idea` or `project.initial_customer` without telling the founder that recorded receipts stop counting. Use `assets/evaluation-template.json` as the machine-readable source of truth. Write `evaluation.json` and run `python3 <skill dir>/scripts/greenfield.py score evaluation.json --output decision.json --json` when Python/shell is available. If not, calculate following `references/scoring.md` and label manual scoring. Never use a generated model score to mask missing research.

## Phase 5 — Decision and artifacts

Create outputs under `research/greenfield/<project-slug>/` (or user-specified path; don't overwrite files outside that directory without authorization):

1. `DECISION.md` — decision first, 1-page investment memo. After `score`, run `python3 <skill dir>/scripts/greenfield.py report --json` to write the verdict and scorecard block; never hand-edit between its markers. You write only the narrative below it (see `references/outputs.md`). Always state if live research was unavailable, who actually did the analysis, and `pilot != scale`.
2. `MARKET_RESEARCH.md` — eight pillar analyses; competitor matrix; bottom-up market sizing with low/base/high input ranges; rough economics and GTM; geographic and segment boundaries; contradictions; URLs inline with claims.
3. `EVIDENCE.md` — source-ledger table of claims with classification, link, date, evidence level and independent-origin notes; unknowns and opposing evidence.
4. `EXPERIMENTS.md` — 3–7 prioritized **test cards** with hypothesis, exact audience, method, measure, precommitted pass/fail threshold, low-cost budget/time assumptions, owner, ethics/consent and decision affected. Only recommend, don't run without consent.
5. `evaluation.json` and `decision.json` — canonical machine-readable evaluation and deterministic decision where supported.
6. `source-verification.json` — retrieved source metadata and quotation checks (unless there are no public links; record why).
7. `experiment-ledger.jsonl` — only actual locally recorded hypothesis/experiment/decision events; do not invent test records; optionally empty or absent if no first-party experiments were run.
8. `PORTFOLIO.md` and `portfolio-ranking.json` only when multiple project evaluations are in scope.

Produce **the recommendation in plain language** using one of: `NO_GO`, `PIVOT`, `VALIDATE_BEFORE_BUILD`, or `PROCEED_TO_BOUNDED_PILOT`. There is **no unconditional `SCALE` verdict** from desk research. List stop conditions and the smallest next step.

## Source and quality bar

Prefer regulator/government statistics, official economic datasets, original studies, direct vendor pricing/product pages, SEC filings, relevant patent/regulatory records and clearly attributed first-party usage data. Use external/community sources to discover perspectives, label their selection bias, and corroborate important claims. Freshness guidance and query recipes: [Research protocol](references/research-protocol.md). The practitioner references in [Source guide](references/sources.md) are frameworks, **not** evidence about this project's current market.

## Invocation examples

- `/greenfield-business-evaluator Evaluate an AI-powered compensation benchmarking agent for HR consultancies, starting in the US. Deep analysis, B2B SaaS, do not build code.`
- `$greenfield-business-evaluator Research a marketplace for surplus lab chemicals. Include legal, logistics, buyer budgets and incumbents.`
- `Evaluate this README as a business, not code. Run the greenfield-business-evaluator with parallel research and give a proceed/pivot/reject decision.`
