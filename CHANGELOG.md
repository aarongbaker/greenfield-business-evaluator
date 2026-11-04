# Changelog

All notable changes to GreenField Business Evaluator are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the version follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Versioning rules:

- **Major**: a change to `evaluation.json` that older files fail, or a verdict that changes for the same input.
- **Minor**: new commands, new optional fields, new output fields.
- **Patch**: fixes with no output change.

`schema_version` ("2.0") is separate from the tool version and changes only on a major.

## [Unreleased]

### Fixed

- Portfolio ranking accepts a `root` folder given through a symlink (macOS temp folders).
- Installs no longer copy `__pycache__`, `.pyc` or other build leftovers into the skill folder.

### Added

- `--version` flag on every script and on `install.py`.
- `.greenfield-version` file written into each installed skill folder.
- GitHub Actions CI: tests on Python 3.11 to 3.14 on Linux and macOS, plus a clean-install check.

## [2.0.0] - 2026-10-23

### Added

- Public source checker (`gf_evidence.py`): opt-in public HTTP(S) fetch, quotation matching, duplicate-origin detection, stale publication flags and JSON reports.
- Append-only experiment learning (`gf_ledger.py`): hypotheses, interviews, behavioral actions, paid tests, signed commitments, repeat purchases, feasibility proofs, failures, experiment results, decision revisions and human source reviews.
- Business-aware scoring (`gf_profiles.py`, `score_project.py`): general, bootstrap SaaS, venture, marketplace, services and regulated profiles with different weights and model-specific gates.
- Real run checkpoints (`gf_runs.py`, `gf_observe.py`): native hook monitoring, a task manifest that resumes completed artifacts, checksummed outputs and sourced-claim counts.
- Portfolio comparison (`gf_portfolio.py`): founder fit, test-learning assumptions, budgets, three sensitivity cases and 12-month scenarios from supplied inputs only.
