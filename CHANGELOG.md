# Changelog

All notable changes to GreenField Business Evaluator are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the version follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Versioning rules:

- **Major**: a change to `evaluation.json` that older files fail, or a verdict that changes for the same input.
- **Minor**: new commands, new optional fields, new output fields.
- **Patch**: fixes with no output change.

`schema_version` ("2.0") is separate from the tool version and changes only on a major.

## [Unreleased]

### Changed

- **Verdicts can change.** Proceed now needs signed, distinct receipts: one file or experiment backs at most 2 core pillars and 3 in all, each receipt must belong to this evaluation and idea and fit its pillar, and quality above 3 needs a receipt behind it, re-assessed after the newest one.
- A failed core receipt or failed gate now says to stop or reframe; `ledger record` no longer takes behavior receipts (use `greenfield evidence add`).
- `evidence_ledger` and `verification_report` must be `experiment-ledger.jsonl` and `source-verification.json` beside `evaluation.json`.
- `greenfield install` and `install.py` add the guard hook by default (`--no-guard` opts out); it now also covers intake commands, signed files and `materials/raw/`.
- Source reviews bind to their claim's signed entry in `source-verification.json`, so re-running `sources check` voids only reviews whose entry changed.
- Receipts sign `confirm_via`; one confirmed by code rather than at a terminal, or a ledger shorter than an earlier score saw, blocks Proceed.
- A fatal blocker leaves only through `resolved` with `resolved_by` ids; deleting it or setting `fatal: false` without them is an error.
- `ledger reattest` touches only this evaluation's events and adopts pre-wave events only in a run that `evidence init` marked legacy, asking for `--as` and `--result`.
- `greenfield report` recomputes the score and refuses a `decision.json` that disagrees.
- Plain `greenfield demo` no longer makes itself the active run when any real run exists.
- `doctor` reports a missing signing key as info, not a warning, and prints the script-path fallback when `greenfield` is not on PATH.
- `start` stores `execution.depth`, gives Claude Code the same next step as Codex, and asks for a profile on a terminal when `--model` is not given.
- The skill proposes `evidence add` commands for the founder instead of attesting, links with `evidence link`, keeps `evaluation_id`, and stamps re-assessment with `evidence assessed`. `scoring.md` replaces "quality can be speculative" with the rubric.

### Added

- `greenfield evidence` (`init`, `add`, `link`, `redact`, `status`, `types`, `assessed`, `experiment add`) for bringing your own materials, with a PII scan and a preview before you sign.
- `greenfield ledger reidea` carries receipts across a typo-sized edit of the idea.
- `greenfield plan` finds the cheapest receipts that reach 75, 90 or 100 with Proceed (`--add-experiments` writes them in); score names the next experiment and stops with "stop or reframe" when findings, not missing evidence, hold the score.
- Every score of a run prints a cumulative change log from `quality-history.jsonl`, and warns when a quality is above what its evidence supports.
- [docs/founder-journey.md](docs/founder-journey.md): the clone-to-Proceed guide, with what each material earns, routes for each profile and the ladder to 100. `docs/evidence.md` and `docs/how-scoring-works.md` cover `evidence add`, the rubric and gate bindings.
- `greenfield demo --proceed` scores a bundled worked example that reaches Proceed (DEMO data, valid only in its own folder).
- Mission Control and DECISION.md show each receipt, each gate and the planner's route.
- `profiles show` prints a `pilot_gates` block to paste; `start --model` pre-fills it.
- `greenfield uninstall --scope all` removes both the project and user installs.
- `greenfield report` warns on stderr, naming the lines, when it overwrites a hand-edited generated block.
- `fetch_public` stops after 20 seconds of wall-clock time per URL across all redirects.
- `greenfield demo --replay` writes the sample run in real time (about 100 seconds) so the dashboard can be watched live.

### Changed

- Mission Control is redesigned as a quiet instrument: the verdict and the live specialists share the first screen. The verdict shows a quality-against-proof map and what is missing to proceed; specialists are timeline lanes with tool, source and error marks; pillars and the log open a details drawer; column headings explain quality and proof on hover; keyboard shortcuts (`?`) cover navigation. The default demo is now a mid-run snapshot.
- `/api/decision` pillars carry `core`, and `next_bet` carries the `pillar` it tests.

### Fixed

- `uninstall` reports a path it cannot remove and carries on, exiting 1, instead of a traceback.
- The "could not validate source review ledger/report" warning now says what failed, not just the error type.
- The shipped template's terminal summary is back to 25 lines.

## [2.2.0] - Unreleased

### Added

- `greenfield report` writes the verdict callout, scorecard and "what would change this verdict" at the top of `DECISION.md` from `decision.json` and `evaluation.json`, between generated markers (with the `decision.json` sha256; `--ascii`). Re-running replaces only the block, refuses a stale `decision.json`, and inserts the block on top of a memo without markers. The agent writes the narrative below it.
- `SECURITY.md`: threat model, what is and is not defended, and how to report a vulnerability.
- User docs in `docs/`: install, command reference, how scoring works, Mission Control, evidence and the ledger, comparing ideas, troubleshooting. `docs/cli.md` and `docs/troubleshooting.md` are generated by `tools/gen_cli_docs.py` (`--check` in CI); `tools/screenshot.py` captures the README's Mission Control screenshot from `greenfield demo` (`--check` fails when the dashboard HTML changed since).
- `tests/test_docs.py` runs every shell command in the README and `docs/` in a fresh git repository with the network blocked, and checks every relative link and anchor. A weekly workflow checks external links and opens an issue for broken ones.

### Changed

- The README is a five-minute quickstart with `greenfield` commands, badges and a dashboard screenshot; install variations, the command reference and Mission Control setup moved to `docs/`.
- Each file in `skill/references/` starts with a line saying it is for agents, linking its human page in `docs/`.

### Removed

- `RELEASE_NOTES.md` (it only pointed here). `OBSERVABILITY.md` is now a one-line pointer to `docs/mission-control.md`, removed in 3.0.

## [2.1.0] - Unreleased

### Added (CLI)

- One `greenfield` command (`pipx install .`, `uvx --from . greenfield`, or `python3 <skill>/scripts/greenfield.py`): `install`, `hooks`, `start`, `status`, `task`, `dashboard`, `demo`, `event emit`, `sources check`, `ledger`, `score`, `portfolio`, `completion`. Global `--project`, `--json`, `--quiet`, `--no-color`, `--version` work before or after the command; JSON when piped; errors as `{"error": {...}}` on stderr with `--json`; exit codes 0/1/2/3/130.
- `pyproject.toml` (standard library only at runtime); the version lives in `skill/scripts/_version.py`.

- `greenfield doctor` runs grouped checks (environment, install, hooks, privacy, attestation, run) and prints one fix command per problem; `--json`, `--fix` (permissions and `.gitignore` only), `--network` (the only mode that opens sockets); exit 0/1, or 3 on an unsupported platform. `greenfield profiles [show NAME | compare A B]` explains the six business-model profiles, their weights and pilot gates.

### Added (agents and guard)

- `greenfield hooks install` also installs a PreToolUse self-attestation guard (`greenfield hook guard`; `--guard-only` installs just it). It refuses agent Bash calls that run a ledger `record --attester` in any spelling (old `gf_ledger.py`, `greenfield ledger record`, `bash -c`, `&&`, env prefixes) and Write/Edit/MultiEdit/NotebookEdit or shell access to ledger files and `~/.config/greenfield/`, and tells the human the command to run themselves. Defense in depth: the TTY prompt and HMAC key remain the real lock. `hooks remove` and `uninstall` take it out without touching other hooks.
- `tools/make_agents.py --check` (CI) fails when the 18 generated agent files drift; a unit test also asserts the read-only tool limits.

### Changed (agents and docs)

- `make_agents.py` moved to `tools/`. Agent briefs no longer hardcode skill paths. `SKILL.md` and the references now use `python3 <skill dir>/scripts/greenfield.py <command> --json`, and a test parses every such line with the real parser.

### Deprecated (CLI)

- Running `score_project.py`, `gf_observe.py`, `gf_runs.py`, `gf_ledger.py`, `gf_evidence.py`, `gf_portfolio.py` or `configure_hooks.py` directly prints one stderr note naming the `greenfield` command (`GREENFIELD_NO_DEPRECATION=1` silences it). They keep working until 3.0. `install.py` stays as the no-dependency install path.

### Changed (observe/install)

- `gf_observe.py start` refuses to replace a running run (exit 2) unless `--new`; `demo` no longer displaces a real run.
- `.greenfield-observe/` is 0700/0600 (older trees are tightened on `start`/`serve`); `install.py` offers `.gitignore` lines (`--gitignore`, `--no-gitignore`).
- The event log no longer stops at 10,000 lines, so status and counts follow the newest events.

### Security

- Behavior receipts and source reviews need a person at a terminal (`/dev/tty`) typing a one-time code, and are HMAC-signed with a local key at `$XDG_CONFIG_HOME/greenfield/attest.key` (override with `GF_CONFIG_DIR` or `GF_ATTEST_KEY_FILE`). Unsigned or hand-written receipts no longer verify.
- Every path read from an evaluation, ledger, manifest or task plan must stay inside its folder (no `..`, absolute paths or symlinks out). Run IDs are validated before the task manifest is written.

### Changed

- Ledger receipts store the artifact path relative to the ledger's folder, so a moved or copied evaluation folder still verifies. Legacy absolute paths still verify (inside the folder) with a warning for one release.
- `score_project.py` prints a one-screen text summary (verdict, headline, pillar bars, grouped warnings, next step) when stdout is a terminal. Piped output, or `--json`, stays JSON with `WARNING:` lines on stderr. New flags: `--json`, `--all-warnings`, `--no-color` (also `NO_COLOR`, `TERM=dumb`).
- Portfolio Markdown escapes every cell (no broken tables, links or HTML from crafted names), shows readable verdict labels and a "Why unranked" column. Running the shipped `portfolio-template.json` lists its unfilled placeholders and exits 2.

### Migration

- Ledgers recorded before signing: receipts show "receipt is unsigned" and evaluations that relied on them drop from `PROCEED_TO_BOUNDED_PILOT` to `VALIDATE_BEFORE_BUILD`. Run `python3 gf_ledger.py reattest --ledger PATH` yourself in a terminal; it walks each unsigned receipt, asks you to confirm it with a code and appends a signed `reattestation` event. Back up the key file printed on first use; receipts verify only where it is.

### Fixed

- Portfolio ranking accepts a `root` folder given through a symlink (macOS temp folders).
- Installs no longer copy `__pycache__`, `.pyc` or other build leftovers into the skill folder.

### Added

- `--version` flag on every script and on `install.py`.
- `.greenfield-version` file written into each installed skill folder.
- GitHub Actions CI: tests on Python 3.11 to 3.14 on Linux and macOS, plus a clean-install check.
- `decision.json` fields `verdict_label`, `headline`, `next_step`, `source_review_pending` and `deprecated_fields`; portfolio JSON gains `verdict_label`.

### Deprecated

- `decision.json` `memo_label` and `source_review_gate_open` (which reads true when no source review is pending; use `source_review_pending`). Both stay populated through 2.x and are removed in 3.0.

## [2.0.0] - 2026-10-23

### Added

- Public source checker (`gf_evidence.py`): opt-in public HTTP(S) fetch, quotation matching, duplicate-origin detection, stale publication flags and JSON reports.
- Append-only experiment learning (`gf_ledger.py`): hypotheses, interviews, behavioral actions, paid tests, signed commitments, repeat purchases, feasibility proofs, failures, experiment results, decision revisions and human source reviews.
- Business-aware scoring (`gf_profiles.py`, `score_project.py`): general, bootstrap SaaS, venture, marketplace, services and regulated profiles with different weights and model-specific gates.
- Real run checkpoints (`gf_runs.py`, `gf_observe.py`): native hook monitoring, a task manifest that resumes completed artifacts, checksummed outputs and sourced-claim counts.
- Portfolio comparison (`gf_portfolio.py`): founder fit, test-learning assumptions, budgets, three sensitivity cases and 12-month scenarios from supplied inputs only.
