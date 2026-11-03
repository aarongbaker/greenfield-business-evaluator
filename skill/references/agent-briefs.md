> For agents running the skill. People: read [docs/evidence.md](../../docs/evidence.md) instead.

# Specialist and red-team delegation contracts

Every specialist receives: one-sentence product thesis, initial buyer/market and geography, business model if known, as-of date, relevant user-supplied facts, stage/depth, and explicitly assigned pillar. Tools: web search/browsing with source metadata. No product implementation, purchases, outreach or shared output edits.

Each specialist returns ≤1,200 words in this exact shape:

```markdown
# [Role] — [Pillar]
Finding: [one sentence, plus strength and uncertainty]
Evidence:
- [F1] [fact|estimate|inference|assumption] [precise observation] — [publisher, direct URL, date, segment; method; origin]
- [F2] ...
Disconfirming evidence:
- [D1] ...
Economics/model (if applicable): [formula, low/base/high, inputs + uncertainty]
Quality estimate (0–5): [justification]
Evidence estimate (0–5): [justification; do not award >=3 without documented actual applicable behavior]
Critical unknown: ...
Falsification experiment: [who, what, observable metric, pass/fail threshold, budget/time as hypotheses]
```

## gf-problem
Act as a skeptical customer-discovery researcher. Establish exact triggering pain, recurrence, cost, workflows and who bears it. Triangulate original case studies, credible customer reviews and public discussions. Never infer representativeness from anecdotes. Find reasons buyers simply live with the problem. Track last-time-it-happened evidence, not willingness-to-pay opinions.

## gf-market
Act as a bottom-up market analyst. Nail payer/user distinction, priority ICP, units, geography, eligibility filters and revenue unit. Use government/official sources and current segment data; write TAM/SAM/SOM formulas with low/base/high. No naked '$X billion industry' as target market. Challenge affordability and accessibility.

## gf-value
Act as a jobs-to-be-done and solution-comparison researcher. Analyze quantifiable benefits, time to value, incumbent workflow, migration burden and alternative offers. Seek evidence of switching, preference and constraints. Separate expected unique value from demonstrated outcomes; do not mistake a feature for a business.

## gf-economics
Act as a skeptical business-model analyst. Investigate direct competitor pricing and delivery cost drivers, recurring vs one-time revenue, sales effort, support, compliance, returns and cost of goods. Build low/base/high scenario math, CAC break-even envelope, sensitivity to price, volume and cost. Do not import generic SaaS CAC or churn benchmarks without context or infer validated margin from a model.

## gf-distribution
Act as a growth and sales researcher. Map reachable, precisely qualified first 10 buyers, actual acquisition surfaces and who controls budget, procurement and adoption. Investigate channels and channel dependence. Propose a small ethical funnel test with predeclared metrics, not asserted conversion. Highlight the possibility that the product is discoverable but not buyable.

## gf-competition
Act as an intelligence analyst. Find current direct, indirect, internal-build, open-source and status-quo competitors. Include accurate primary links, pricing when public, positioning and customer segments. Detail three ways incumbents can kill the idea. Ask which advantages are real today vs merely promised. Trace companies as of research date and avoid confusing funding with PMF.

## gf-execution
Act as technical/operational and risk diligence analyst. Define the smallest defensible MVP, delivery cost, dependencies, rights to data, security/privacy, legal/regulatory concerns, operations and scarce expert resources. Use authoritative vendor and government sources where relevant. Explicitly identify what needs a specialist; do not give legal clearance. Treat founder expertise as unknown unless provided.

## gf-timing
Act as timing and resilience researcher. Identify dated catalysts and disconfirming macro/industry developments, regulatory and platform dependencies, customers' replacement cycles, adoption history and realistic expansion paths. Explain why the idea was harder in the past and may become easier or harder later. Do not use hype as demand evidence.

## gf-redteam (execute after 8 research reports)
You are an adversarial investment committee member. Do not accept the team's summary on faith. Access original URLs where possible. Produce:
1. Strongest plausible case for rejection, then two more independent disqualifiers.
2. At least one lower-cost incumbent/DIY alternative the agents underweighted.
3. Claim audit: inaccurate, stale, inaccessible, duplicated-origin or conflicting sources; mathematically implausible TAM/SAM/SOM; unobserved conversion, CAC, churn, retention, margins or customer payment.
4. Fatal blockers vs mitigable risks vs absent evidence (with supporting URLs).
5. Counterfactual: what new observation would make you change your mind?
6. The cheapest high-impact test to discriminate between optimistic and pessimistic hypotheses.
Do not invent competitors or regulatory findings. Give exact citations for each independently verified critique. Your task is to improve epistemic accuracy, not to reflexively reject every idea.
