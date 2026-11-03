# Refactor plan and wave specs

Planning docs for the GreenField Evaluator refactor, exported from the Claude Docs versions on 3 Nov 2026, including each doc's Decisions section. Start with the unified plan, then read the wave you are implementing. Each wave ships as its own PR.

| Doc | Work items | Scope |
| --- | --- | --- |
| [Unified refactor plan](00-unified-plan.md) | W1 to W30 | All 30 work items, conflicts, wave order, file collision map, decisions |
| [Wave 0: foundation](wave-0-foundation.md) | W1 to W4 | Shared helpers, packaging hygiene, CI, one `ROLES` table |
| [Wave 1: close the trust exploits](wave-1-trust-exploits.md) | W5 to W11 | Read-only agents, path confinement, never-throwing validator, portfolio re-scoring, dashboard Host check, hook platform flag, attestation |
| [Wave 2: output and guardrails](wave-2-output-guardrails.md) | W12 to W17 | Scorer verdict and text output, portfolio labels, active-run guard, file permissions, fetcher hardening, README fixes |
| [Wave 3: Mission Control dashboard](wave-3-mission-control.md) | W18 to W21 | Decision panel, render diffing, status correctness, visual polish |
| [Waves 4 and 5: CLI and docs](waves-4-5-cli-docs.md) | W22 to W30 | `greenfield` CLI, doctor, install/uninstall, Windows, `tools/` move, README quickstart, DECISION.md, SECURITY.md |

Links to `claude.ai/artifact/...` inside these docs point to the original reviews and docs, which are private to the project owner.
