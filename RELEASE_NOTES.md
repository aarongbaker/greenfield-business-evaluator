# Greenfield Business Evaluator — v2 complete release

Release date: October 23, 2026

## Scope delivered

1. Public source checker (`gf_evidence.py`): explicit opt-in public HTTP(S) fetch, text quotation matching, duplication by reported origin, stale publication flags and JSON reports. Human-reviewed source receipt events (`gf_ledger.py` source_review) are matched against the exact report hash before a pilot decision.
2. Append-only experiment learning (`gf_ledger.py`): hypotheses, interviews, behavioral actions, paid tests, signed commitments, repeat purchases, feasibility proofs, failures, experiment results, decision revisions, and human source reviews. Human-attested strong behavior requires a local artifact whose checksum remains unchanged. Honest limitation: human attestations can be dishonest; a local SHA-256 chain can be rewritten by someone with full file control.
3. Business-aware scoring (`gf_profiles.py`, `score_project.py`): explicit profiles for general, bootstrap SaaS, venture, marketplace, services, regulated; different weights and mandatory model-specific gates. Still non-predictive heuristic.
4. Real run checkpoints (`gf_runs.py`, `gf_observe.py`, HTML dashboard): native hooks monitor actual specialists when supported; separate task manifest safely resumes completed fresh artifacts, prevents early red team, checksums outputs, records sourced claim counts and reports optional user-rated token cost. It does not itself launch native subagents.
5. Portfolio comparison (`gf_portfolio.py`): explicit founder-fit, test-learning assumptions and budgets, three sensitivity weighting cases, deterministic 12-month revenue/contribution scenarios (only with supplied inputs), blocking NO_GO/PIVOT/RESEARCH_INCOMPLETE from next-experiment ranking.

## Verification

Automated tests exercise schemas, both native role installations, observable hooks via representative fixtures, checkpoint reuse, tampering, source checks, score gates, and portfolio math. Run `python3 -m unittest discover -s tests -v` after extraction. **Not an end-to-end real-money or live browser benchmark:** no real autonomous agents were launched, no external payment was made, no actual customer was contacted, and most remote sources cannot be independently verified by code alone.

## Privacy/security

- Keep private research, interviews and paid receipts outside the repository or in an ignored folder. Files are local; no telemetry uploader is included.
- `gf_evidence.py` has bounded downloads, no cookies or proxy, host/IP checks, but should only be used against public URLs and is not a fully isolated downloader for untrusted inputs.
- `gf_observe.py` binds to `127.0.0.1`; avoid exposing local URLs through reverse proxies.
- Hooks are explicitly opt-in, and may execute scripts with local user permissions. Review them before trusting.
