# Changelog

All notable changes to GreenField Business Evaluator are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the version follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Versioning rules:

- **Major**: a change to `evaluation.json` that older files fail, or a verdict that changes for the same input.
- **Minor**: new commands, new optional fields, new output fields.
- **Patch**: fixes with no output change.

`schema_version` ("2.0") is separate from the tool version and changes only on a major.

## [Unreleased]

### Security

- Behavior receipts and source reviews need a person at a terminal (`/dev/tty`) typing a one-time code, and are HMAC-signed with a local key at `$XDG_CONFIG_HOME/greenfield/attest.key` (override with `GF_CONFIG_DIR` or `GF_ATTEST_KEY_FILE`). Unsigned or hand-written receipts no longer verify.
- Every path read from an evaluation, ledger, manifest or task plan must stay inside its folder (no `..`, absolute paths or symlinks out). Run IDs are validated before the task manifest is written.

### Changed

- Ledger receipts store the artifact path relative to the ledger's folder, so a moved or copied evaluation folder still verifies. Legacy absolute paths still verify (inside the folder) with a warning for one release.

### Migration

- Ledgers recorded before signing: receipts show "receipt is unsigned" and evaluations that relied on them drop from `PROCEED_TO_BOUNDED_PILOT` to `VALIDATE_BEFORE_BUILD`. Run `python3 gf_ledger.py reattest --ledger PATH` yourself in a terminal; it walks each unsigned receipt, asks you to confirm it with a code and appends a signed `reattestation` event. Back up the key file printed on first use; receipts verify only where it is.

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
