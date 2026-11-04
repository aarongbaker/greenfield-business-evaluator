> For agents running the skill. People: read [docs/mission-control.md](../../docs/mission-control.md) instead.

# Mission Control operational protocol

Mission Control is passive observability. Setup for people is in the repository's `docs/mission-control.md`; its CLI is `scripts/greenfield.py` inside the installed skill (`<skill dir>` below). Use this CLI only if a local shell is available and the user enabled observability.

1. Resolve the repository root. Prefer the existing `.greenfield-observe/active.json` run. Do not replace an active run just to create events: `start` refuses while a run is active, and agents must never pass `--new` unless the user asked for a fresh run. If no run exists and user asked for tracking, initialize: `python3 <skill dir>/scripts/greenfield.py --project <repo> start --idea "<short idea>" --research-dir research/greenfield/<slug> --json`; the Decision panel reads `evaluation.json` from that folder (link an existing run with `python3 <skill dir>/scripts/greenfield.py link --research-dir <folder> --json`). Never include confidential personal information in the run title.
2. Platform hooks (installed with `greenfield hooks install`) detect genuine `SubagentStart`, `SubagentStop`, and tool lifecycle events. No agent should emit a fake lifecycle event. `queued` means only a defined role is displayed, not a real task enqueued. CLI `ingest-codex` accepts official Codex `--json` events, with unattributed items recorded against the orchestrator.
3. After encountering a source which is actually used and has a safe public URL, optionally emit `source_seen` against the corresponding specialist with the URL. This is **not** a source verification claim; market research still needs a provenance ledger.
4. After actually writing a report, emit `artifact_created` with a short filename. Never log report contents or private customer data.
5. When all reports, red-team review and scoring finish successfully, emit `run_completed` for the active run. If research is interrupted, emit `run_failed` only for confirmed failures, and never claim a finished evaluation.
6. If hooks or web tooling are unavailable, tell the user what was really observed; don't infer token costs, progress %, parallelism, citations verified, or customer validation.
7. Never use the dashboard as a reason to collect credentials, enable unrestricted execution, upload evidence, or bypass approvals. Telemetry must stay local-only.

Dashboard: `python3 <skill dir>/scripts/greenfield.py --project <repo> dashboard --port 8765`; then browse `http://127.0.0.1:8765`. Revert opt-in hooks with `python3 <skill dir>/scripts/greenfield.py --project <repo> hooks remove --platform both --json`.
