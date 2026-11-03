# Mission Control operational protocol

Mission Control is passive observability. Consult the bundle's `OBSERVABILITY.md` for installation; its CLI is `scripts/gf_observe.py` inside the installed skill. Use this CLI only if a local shell is available and the user enabled observability.

1. Resolve the repository root. Prefer the existing `.greenfield-observe/active.json` run. Do not replace an active run just to create events. If no run exists and user asked for tracking, initialize: `python3 <skill>/scripts/gf_observe.py start --project <repo> --idea "<short idea>"`. Never include confidential personal information in the run title.
2. Platform hooks (installed with `configure_hooks.py`) detect genuine `SubagentStart`, `SubagentStop`, and tool lifecycle events. No agent should emit a fake lifecycle event. `queued` means only a defined role is displayed, not a real task enqueued. CLI `ingest-codex` accepts official Codex `--json` events, with unattributed items recorded against the orchestrator.
3. After encountering a source which is actually used and has a safe public URL, optionally emit `source_seen` against the corresponding specialist with the URL. This is **not** a source verification claim; market research still needs a provenance ledger.
4. After actually writing a report, emit `artifact_created` with a short filename. Never log report contents or private customer data.
5. When all reports, red-team review and scoring finish successfully, emit `run_completed` for the active run. If research is interrupted, emit `run_failed` only for confirmed failures, and never claim a finished evaluation.
6. If hooks or web tooling are unavailable, tell the user what was really observed; don't infer token costs, progress %, parallelism, citations verified, or customer validation.
7. Never use the dashboard as a reason to collect credentials, enable unrestricted execution, upload evidence, or bypass approvals. Telemetry must stay local-only.

Dashboard: `python3 <skill>/scripts/gf_observe.py serve --project <repo> --port 8765`; then browse `http://127.0.0.1:8765`. Revert opt-in hooks with `python3 configure_hooks.py remove --platform both --project <repo>` from the bundle.
