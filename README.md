# Greenfield Business Evaluator

Research-first due diligence for business ideas, run inside **Claude Code** or **Codex** before any code is written.

Greenfield Business Evaluator is an [Agent Skill](https://agentskills.io/specification) that turns your coding assistant into a structured diligence team. Eight independent specialists research the idea, a red team challenges their findings, and a deterministic scorer produces a go/no-go recommendation backed by an auditable evidence trail.

## Features

- **Multi-agent research.** Eight specialist roles plus an independent red team, run in parallel where the host supports subagents and sequentially otherwise.
- **Evidence-weighted scoring.** Every pillar is scored separately for *quality* and *strength of evidence*, so an attractive market estimate is never confused with proof that buyers will pay.
- **Business model profiles.** Weights and pilot gates tuned for general, bootstrapped SaaS, venture startup, marketplace, services, and regulated businesses.
- **Source verification.** Optionally fetches public sources to check quoted excerpts, publication age, and duplicate origins.
- **Experiment ledger.** Append-only, SHA-256-linked records of hypotheses, interviews, paid tests, and decision revisions.
- **Resumable runs.** Checkpointed specialist tasks with artifact checksums and freshness checks.
- **Portfolio comparison.** Rank multiple ideas with sensitivity analysis and input-driven 12-month scenarios.
- **Mission Control.** An optional local dashboard showing live specialist activity, sources, and warnings.

All scripts use the Python standard library only. No API keys, packages, or telemetry uploads.

## Requirements

- Python 3.11+
- macOS or Linux (the ledger and run controller use `fcntl` file locking)
- Claude Code or Codex, ideally with web search enabled

## Installation

```bash
git clone https://github.com/aarongbaker/greenfield-business-evaluator.git
cd greenfield-business-evaluator
```

Install into a project for both assistants:

```bash
python3 install.py --platform both --scope project --project /path/to/your/repo
```

Common variations:

```bash
# Personal install, available in every repository
python3 install.py --platform both --scope user

# Single assistant
python3 install.py --platform claude --scope project --project .
python3 install.py --platform codex --scope project --project .

# Skill only, without the specialist role definitions
python3 install.py --platform both --scope project --project . --no-agents

# Reinstall, overwriting only files owned by this package
python3 install.py --platform both --scope project --project . --force
```

| Platform | Skill | Specialist roles |
|---|---|---|
| Claude Code (project) | `.claude/skills/greenfield-business-evaluator/` | `.claude/agents/gf-*.md` |
| Codex (project) | `.agents/skills/greenfield-business-evaluator/` | `.codex/agents/gf-*.toml` |
| Claude Code (user) | `~/.claude/skills/greenfield-business-evaluator/` | `~/.claude/agents/gf-*.md` |
| Codex (user) | `~/.agents/skills/greenfield-business-evaluator/` | `~/.codex/agents/gf-*.toml` |

The installer never modifies `settings.json`, `config.toml`, API keys, approval settings, network permissions, or your product code.

## Usage

**Claude Code**

```text
/greenfield-business-evaluator Evaluate [your idea]. US market, B2B, deep research. Use parallel specialists and red-team the evidence. Do not write code.
```

**Codex**

```text
$greenfield-business-evaluator Evaluate [your idea]. Research the market live, challenge competitors and economics, and recommend whether to validate, pivot, or run a bounded pilot. No implementation.
```

You can pass a one-line idea or point the skill at a PRD or README. Choose a depth of `quick`, `standard` (default), or `deep`. If the skill does not appear, restart the assistant.

### Output

```
research/greenfield/<slug>/
├── DECISION.md          Investment memo, red-team dissent, and next bet
├── MARKET_RESEARCH.md   Pillar findings, competitors, sizing, business model
├── EVIDENCE.md          Every material claim with its source
├── EXPERIMENTS.md       Falsifiable tests with stop conditions
├── evaluation.json      Reproducible inputs and pillar scores
└── decision.json        Deterministic scorecard output
```

The skill proposes outreach and paid experiments but never spends money, contacts people, or launches anything on its own. Without web access it marks research as incomplete rather than inventing answers.

## How it works

### Specialist roles

| Role | Agent |
|---|---|
| Problem Discovery | `gf-problem` |
| Market & ICP | `gf-market` |
| Customer Value | `gf-value` |
| Unit Economics | `gf-economics` |
| Distribution & GTM | `gf-distribution` |
| Competitive Intelligence | `gf-competition` |
| Execution & Founder Fit | `gf-execution` |
| Timing & Survivability | `gf-timing` |
| Independent Red Team | `gf-redteam` |

By default the specialists run in two waves of up to four concurrent tasks, followed by the red team. The orchestrator writes all final files to avoid contention.

### Scoring

Default pillar weights (adjusted per business model profile):

| Problem | Market | Value | Economics | Distribution | Competition | Execution | Timing |
|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| 20 | 15 | 15 | 15 | 15 | 10 | 5 | 5 |

Each pillar receives a 0–5 quality score and a 0–5 evidence score. The result is one of:

| Decision | Meaning |
|---|---|
| `RESEARCH_INCOMPLETE` | Not enough evidence to decide |
| `NO_GO` | Fatal blocker or weak fundamentals |
| `PIVOT` | Promising signal, wrong shape |
| `VALIDATE_BEFORE_BUILD` | Run the proposed experiments first |
| `PROCEED_TO_BOUNDED_PILOT` | Build a limited, time-boxed pilot |

A confirmed fatal blocker overrides any score. Scores are heuristics, not probabilities of success.

## Command-line tools

Paths below assume a Codex project install. For Claude Code, use `.claude/skills/...`.

```bash
SKILL=.agents/skills/greenfield-business-evaluator
IDEA=research/greenfield/your-idea

# Score an evaluation
python3 $SKILL/scripts/score_project.py $IDEA/evaluation.json --output $IDEA/decision.json

# Verify cited sources (network access is opt-in)
python3 $SKILL/scripts/gf_evidence.py $IDEA/evaluation.json \
  --output $IDEA/source-verification.json --allow-network

# Plan, check, and resume a research run
python3 $SKILL/scripts/gf_runs.py --project . plan
python3 $SKILL/scripts/gf_runs.py --project . status
python3 $SKILL/scripts/gf_runs.py --project . resume

# Compare several ideas (start from skill/assets/portfolio-template.json)
python3 $SKILL/scripts/gf_portfolio.py portfolio.json \
  --output portfolio-ranking.json --markdown PORTFOLIO.md
```

## Mission Control

Mission Control is an optional local dashboard that displays specialist lifecycle events, tool usage, sources, and warnings in real time. It observes; it does not run agents, read their reasoning, or send data anywhere.

```bash
# Opt in to project-local lifecycle hooks
python3 configure_hooks.py install --platform both --project /path/to/repo

# Start a run and open the dashboard at http://127.0.0.1:8765
python3 $SKILL/scripts/gf_observe.py start --project . --idea "Your idea"
python3 $SKILL/scripts/gf_observe.py serve --project .
```

Telemetry is stored in `.greenfield-observe/` in your repository. `install.py` offers to add it to `.gitignore`, and its files are private (0600) by default. Codex project hooks must be reviewed and trusted via `/hooks`. Run `gf_observe.py demo` for a clearly labeled simulated session. See [OBSERVABILITY.md](OBSERVABILITY.md) for full setup and security notes.

## Enforcing diligence before new builds

To have your assistant run this evaluation whenever a new project is proposed, copy the relevant snippet into your repository:

- Codex: [`integration/AGENTS.snippet.md`](integration/AGENTS.snippet.md) → `AGENTS.md`
- Claude Code: [`integration/CLAUDE.snippet.md`](integration/CLAUDE.snippet.md) → `CLAUDE.md`

The installer does not do this for you, since it changes repository-wide agent behavior. The gate always yields to a user who explicitly asks to skip it.

## Development

```bash
python3 -m unittest discover -s tests -v
python3 skill/scripts/score_project.py skill/assets/evaluation-template.json   # expect RESEARCH_INCOMPLETE
```

The test suite covers installation layouts for both platforms, hook adapters, evidence checks, ledger tamper detection, scoring policies, portfolio ranking, and run resumption. Tests use synthetic fixtures and do not exercise live web research.

## Limitations

- Source checks are lexical, not semantic fact verification. PDFs and paywalled sources need human review.
- The experiment ledger detects tampering with individual records, but an attacker with full file access can replace an entire chain. Behavior receipts are HMAC-signed with a local key after a person types a confirmation code at a terminal; signing raises the cost of forgery, it is not proof.
- Native subagent support varies by host version and can be disabled. The skill falls back to sequential execution and says so.
- This tool structures and audits research. It does not replace talking to customers.

## Documentation

- [`skill/SKILL.md`](skill/SKILL.md): skill entry point
- [`skill/references/`](skill/references/): research protocol, scoring, sources, agent briefs, and output specs
- [`skill/references/v2-workflows.md`](skill/references/v2-workflows.md): end-to-end operational workflows
- [`OBSERVABILITY.md`](OBSERVABILITY.md): Mission Control setup

## License

[MIT](LICENSE)
