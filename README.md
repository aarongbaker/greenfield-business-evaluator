# Greenfield Business Evaluator v2 Complete (Claude Code + Codex)

**Research-first due diligence for a business idea before you build, with optional live local Mission Control.** One shared [Agent Skills](https://agentskills.io/specification) workflow, optional native multi-agent roles in each coding assistant, independent adversarial review, and a deterministic (non-predictive) investment decision tool.

**Verified against published Claude Code and Codex skill/subagent documentation on October 23, 2026.** This is a packaged skill, not an autonomous commercial-data provider or a substitute for talking to customers.


## Complete v2 capabilities (all five roadmap pillars)

| Feature | Working implementation | Limits |
|---|---|---|
| Public evidence inspector | `skill/scripts/gf_evidence.py` fetches public HTML/text when explicitly enabled, checks excerpts and publication age, records duplicate reported origins | Lexical excerpt checks are not semantic fact verification; PDFs/paywalls require a person |
| Append-only experiment learning | `skill/scripts/gf_ledger.py` creates SHA-256-linked hypothesis, interview, paid test, failure, decision revision, and human source-review records | File-access attackers can replace whole chains; named attestation is not proof of real payment |
| Six business model profiles | `skill/scripts/gf_profiles.py` + `score_project.py` model weights and auditable pilot gates | Heuristic weights are not predictive probabilities |
| Resume + Mission Control | `skill/scripts/gf_runs.py` checkpoints 9 real specialist tasks, verifies artifact checksums/freshness, shows claim coverage and optional estimated usage in the dashboard | It does not spawn agents; token-derived cost requires actual usage and user-supplied rate |
| Portfolio scenarios | `skill/scripts/gf_portfolio.py` creates cross-idea ranking, sensitivity analysis and input-driven 12-month contribution scenarios | Does not predict sales or fabricate probabilities |

**Start with** [v2 operational instructions](skill/references/v2-workflows.md). Python 3.10+ is required for these scripts. Mac and Linux are supported; the experiment ledger/task controller depend on `fcntl` file locking. Agent hooks remain opt-in and cannot bypass host sandbox controls.

### Quick usage after installing in your repository

```bash
SKILL=.agents/skills/greenfield-business-evaluator
# Start a real research run and checkpoint manifest
python3 "$SKILL/scripts/gf_observe.py" start --project . --idea "Your idea"
python3 "$SKILL/scripts/gf_runs.py" --project . plan
python3 "$SKILL/scripts/gf_observe.py" serve --project .
# In your normal Claude Code / Codex session, invoke the skill and delegate real agents.
# Afterwards (from a populated research/greenfield/<idea> folder):
python3 "$SKILL/scripts/gf_evidence.py" research/greenfield/<idea>/evaluation.json --output research/greenfield/<idea>/source-verification.json --allow-network
python3 "$SKILL/scripts/score_project.py" research/greenfield/<idea>/evaluation.json --output research/greenfield/<idea>/decision.json
# For multiple ideas, prepare a portfolio manifest based on skill/assets/portfolio-template.json.
python3 "$SKILL/scripts/gf_portfolio.py" portfolio.json --output portfolio-ranking.json --markdown PORTFOLIO.md
```

**Do not copy the literal `<idea>` path into a shell:** replace it with your actual project slug. Fetched pages and all attested behavioral experiments must be genuine. The tests use synthetic fixtures, not real customers. The project is not autonomous market validation: substantial research still requires internet-enabled Claude/Codex agents and real human approval for stronger evidence.

## New in v2: Mission Control (working local dashboard)

The optional `gf_observe.py` dashboard shows actual specialist lifecycle, short tool-type metadata, source records, warnings, and execution timelines. It does **not** run the subagents, invent their activity, read their internal reasoning, or upload telemetry. For complete installation, live-event hook setup, usage, Codex JSONL streaming, data-security notes, and clear remaining gaps, see [OBSERVABILITY.md](OBSERVABILITY.md).

```bash
# First install the shared skill, then opt in to project-local lifecycle hooks
python3 install.py --platform both --scope project --project /path/to/repo
python3 configure_hooks.py install --platform both --project /path/to/repo

# In the repo, using the installed Codex-side copy (either copy works):
python3 .agents/skills/greenfield-business-evaluator/scripts/gf_observe.py start --project . --idea "Your business idea"
python3 .agents/skills/greenfield-business-evaluator/scripts/gf_observe.py serve --project .
# Open http://127.0.0.1:8765
```

Hooks are **not** enabled by the ordinary installer. Codex project hooks must be reviewed/trusted in `/hooks`. A demo is available with the `demo` command and is explicitly labeled simulated. Local telemetry is stored at `<repo>/.greenfield-observe/` (gitignore it for private ideas).

## Install (Python 3.10+, no packages or API keys required for installer)

From the extracted `greenfield-business-evaluator/` folder:

```bash
# Install both into the current project, including platform subagent definitions
python3 install.py --platform both --scope project --project /path/to/your/repo

# Optional: personal skill across all repos (run only if wanted)
python3 install.py --platform both --scope user

# Install just one provider
python3 install.py --platform claude --scope project --project .
python3 install.py --platform codex --scope project --project .

# Re-install a revised package, overwriting ONLY this package's owned files
python3 install.py --platform both --scope project --project . --force
```

| Platform | Installed skill | Installed specialist role definitions |
|---|---|---|
| Claude Code (project) | `.claude/skills/greenfield-business-evaluator/SKILL.md` | `.claude/agents/gf-*.md` |
| Codex (project) | `.agents/skills/greenfield-business-evaluator/SKILL.md` | `.codex/agents/gf-*.toml` |
| Claude Code (personal) | `~/.claude/skills/greenfield-business-evaluator/SKILL.md` | `~/.claude/agents/gf-*.md` |
| Codex (personal) | `~/.agents/skills/greenfield-business-evaluator/SKILL.md` | `~/.codex/agents/gf-*.toml` |

The basic installer does not touch `config.toml`, `settings.json`, API keys, approval settings, product code, or internet permissions. Native subagent availability varies by version/environment and can be disabled. Skill instructions explicitly fall back to honest sequential execution. A file called `gf-market.toml` **defines** an agent role but doesn't itself spawn a parallel process.

## Invoke

**Claude Code:**

```text
/greenfield-business-evaluator Evaluate [your business idea]. Start in the US, B2B, deep market research; use parallel independent specialists and red-team the evidence. Do not code.
```

**Codex:**

```text
$greenfield-business-evaluator Evaluate [your business idea]. Perform live market research, challenge competitors and economics, fan out specialists when available, and decide whether to validate, pivot, or proceed to a bounded pilot. No implementation.
```

If the skill doesn't show up, restart the coding assistant and use the full invocation. Enable the host's **web browsing/search** tool when available; a valid skill file by itself cannot grant internet access. In Codex, local subagents are currently generally available; agents can be configured with `[agents]` in user config if desired, but a configuration change is not required by this installer. Claude Code supports normal subagents; **experimental agent teams** are optional and not required (teams use `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`).

## Optional: require diligence before a greenfield build

To trigger research reliably when a new project is proposed, copy `integration/AGENTS.snippet.md` into the repo’s `AGENTS.md` (Codex), and/or `integration/CLAUDE.snippet.md` into `CLAUDE.md` (Claude Code). This is deliberately **not** done by the installer: it changes repository-wide agent behavior and should be a conscious choice. These instructions defer to a user who explicitly says to skip the gate.

## Inputs and outputs

You can supply a one-line idea or a PRD/README in a repository. The skill infers assumptions and marks them as such; it does not assume the repo represents market validation. Choose `quick`, `standard` (default), or `deep`. At the end, expect:

```
research/greenfield/<slug>/
├── DECISION.md             investment memo, red-team dissent, next bet
├── MARKET_RESEARCH.md      8 pillars, competitors, sizing, business model
├── EVIDENCE.md             each material claim and source provenance
├── EXPERIMENTS.md          falsifiable tests with stop conditions
├── evaluation.json         reproducible inputs and pillar scores
└── decision.json           validated, deterministic scorecard output
```

The skill proposes outreach and paid experiments; it never autonomously spends money, contacts people or launches a product. For a no-web environment it should mark research incomplete, not fabricate answers.

## The eight roles

1. Problem Discovery (`gf-problem` / `gf_problem`)
2. Market & ICP (`gf-market` / `gf_market`)
3. Customer Value (`gf-value` / `gf_value`)
4. Unit Economics (`gf-economics` / `gf_economics`)
5. Distribution & GTM (`gf-distribution` / `gf_distribution`)
6. Competitive Intelligence (`gf-competition` / `gf_competition`)
7. Execution & Founder Fit (`gf-execution` / `gf_execution`)
8. Timing & Survivability (`gf-timing` / `gf_timing`)

An independent `gf-redteam` / `gf_redteam` critiques the specialist findings afterward. Default runtime plan: 4 concurrent subagent tasks at a time in two waves, then red team. The orchestrator writes final files to avoid contention. When delegation isn't available, all nine roles run sequentially, with transparent reporting.

## Score (heuristic, not success probability)

The weights are: problem 20, market 15, customer value 15, economics 15, distribution 15, competition 10, execution 5, timing 5. Each has separate 0–5 **quality** and 0–5 **evidence** scores. Distinguish an attractive market estimate from evidence a buyer will purchase *this product*.

Decision labels: `RESEARCH_INCOMPLETE`, `NO_GO`, `PIVOT`, `VALIDATE_BEFORE_BUILD`, and `PROCEED_TO_BOUNDED_PILOT`. A confirmed fatal blocker can veto a high score; proposing a safe experiment is not authorization to perform it. A pilot is not an endorsement to scale.

Run the scorer on an evaluation result:

```bash
python3 .agents/skills/greenfield-business-evaluator/scripts/score_project.py \
  research/greenfield/your-idea/evaluation.json \
  --output research/greenfield/your-idea/decision.json
# (Change .agents to .claude/skills for a Claude-only install.)
```

## Validate installation and score policy

```bash
python3 -m unittest discover -s tests -v
python3 skill/scripts/score_project.py skill/assets/evaluation-template.json
```

The template test should report `RESEARCH_INCOMPLETE`, not fabricate research. All scripts use the standard library and do not make network requests; live research is performed by the host coding assistant with browsing enabled.

## Design references

- Skill format: https://agentskills.io/specification
- Claude Code skills and subagents: https://code.claude.com/docs/en/skills ; https://code.claude.com/docs/en/sub-agents
- Codex skills and subagents: https://learn.chatgpt.com/docs/build-skills ; https://learn.chatgpt.com/docs/agent-configuration/subagents
- Problem/problem validation: https://www.ycombinator.com/library/7x-how-to-get-and-test-ideas
- Evidence scale and assumption tests: https://www.strategyzer.com/library/business-project-succcess
- Industry/customer data and competition: https://www.sba.gov/counseling/plan-your-business/

For the full researcher protocol, source guidance, score gates, and deliverable specs, see `skill/references/`.

## Validate this release

```bash
python3 -m unittest discover -s tests -v
```

Tests exercise both providers' install structures, existing real-event hook adapters (using fixtures), evidence URL/quotation behavior, hash-chain tamper detection, human receipt gates, portfolio scoring, model policies, resuming interrupted runs, and source coverage. **They are not a live end-to-end test of autonomous research quality or web reliability in your local environment.**

## Upgrading from the original v1 / earlier Mission Control v2

```bash
python3 install.py --platform both --scope project --project /path/to/repo --force
# This deliberately overwrites this skill's owned folders and gf-* role definitions only.
# If you previously installed optional hooks, confirm they point to the same skill location.
python3 configure_hooks.py install --platform both --project /path/to/repo
```

Do not overwrite personal experiments or `.greenfield-observe` by reinstalling; they reside outside the managed skill directories. Copy your old evaluation files and migrate manually (add `schema_version: "2.0"`, business model and ledger/report references) rather than asserting earlier `verified: true` fields are trustworthy.
