# Mission Control wave: detailed specs (W18 to W21)

Nov 3, 2026 · @Aaron

## Summary

This wave turns Mission Control from an agent activity monitor into the place a founder reads the verdict, and makes every number on it trustworthy. It covers the four items the [unified refactor plan](https://claude.ai/artifact/VniiAwzeSr8oS5mQhvFvXs) puts in its dashboard wave (plan Wave 3): W18 Decision panel, W19 render diffing, W20 status correctness and W21 visual polish. Aaron also approved two upgrades on 3 Nov: the verdict gap and the evidence drill-down (specced under Beyond the plan). Estimate: 2.5 to 3 days, one PR, gated by a Playwright smoke test.

The edge over every competitor is one sentence: **no other free tool shows a re-verified verdict next to the live research that produced it.** Idea validators (ValidatorAI, IdeaProof) hand you a report with no visible process and no way to check it. Agent dashboards (Langfuse, Phoenix, the open-source Claude Code hooks dashboard) show traces but never a decision. This wave closes that gap while staying one self-contained HTML file, standard library only, loopback only, with no account.

Each spec below gives the goal, design, files and functions, acceptance criteria, tests, edge cases and how it compares. Nothing here changes code; it is the brief for the PR.

| Item | What ships | Closes | Depends on |
| --- | --- | --- | --- |
| W18 | `/api/decision` (recomputed, never trusted) plus a Decision panel with four empty and error states | UI U1 | W1, W4, W6, W8, W9, W12 |
| W19 | ETag polling, keyed patching, append-only feed, focus and scroll kept, backoff and pause when hidden | UI U2 | W18 (shares the client store) |
| W20 | One reconciled agent status, true connection state, DEMO once, grouped feed with filter chips, run-scaled timeline | UI U5, U6, U7, U9, U10 | W4, W19 |
| W21 | Token-based light and dark themes, 4-tile run strip, `plural()`, 12px floor, no overflow at 390px | UI U12 to U15 | W19, W20 |

## Competitive landscape and the bar to beat

Two families of tools touch what Mission Control does, and each covers only half. The table lists what each shows today and what this wave copies or beats.

| Tool | Price | What it shows | Weakness this wave exploits |
| --- | --- | --- | --- |
| [ValidatorAI](https://validatorai.com/faq) | Free | Written report with verdict-style points | No sources, no visible process, verdict cannot be re-checked ([review](https://bigideasdb.com/blog/ai-idea-validator-tools-2026)) |
| [IdeaProof](https://ideaproof.io/compare/feature-matrix) | Freemium | Strengths, risks, market-size estimate | LLM reasoning, not checked data |
| [BigIdeasDB](https://bigideasdb.com/blog/ai-idea-validator-tools-2026) | Paid with free start | Verdict grounded in complaint and revenue data, CSV export with sources | No live progress view; vendor's own review |
| [Langfuse](https://langfuse.com/changelog/2024-06-12-timeline-view.md) | Open source, cloud tiers | Trace tree and timeline view per run | No business verdict; needs a server and database |
| [Arize Phoenix](https://arize.com/docs/phoenix/release-notes/08-2025/08-22-2025-new-trace-timeline-view.md) | Open source | Trace timeline view, spans, evals | Same: traces, not decisions |
| [Claude Code hooks observability](https://docsearch.algolia.com/mcp/docs/repo/disler/claude-code-hooks-multi-agent-observability) | Open source | WebSocket event stream, regex filter, live pulse chart, SQLite store | Needs Bun, Vue and SQLite; no verdict; no per-agent reconciliation |

The bar this wave sets, item by item:

- **Verdict with provenance (W18).** Validators show a verdict you must trust. We show the verdict recomputed from `evaluation.json` on every change, flag a forged or stale `decision.json`, and list the gates still open. No tool in the table does this.
- **Stable live view (W19).** Langfuse and Phoenix keep focus and scroll because they are SPA frameworks. We match that with about 150 lines of vanilla JS, no build step.
- **Honest status (W20).** The hooks dashboard shows raw events; we reconcile hook events with checkpoints into one status per specialist and say where it came from.
- **Zero-install polish (W21).** Light and dark themes, phone width, readable type, all inside one HTML file served by Python's standard library.

Caveat on sources: the validator comparison comes mostly from a review written by BigIdeasDB, a competitor of those tools, so read its judgments with that in mind.

## Shared foundations

Three small pieces underpin all four items and land first in the PR. None of them exist in the code today.

### 1. Link a run to its research folder

Today a run (`.greenfield-observe/runs/<id>/meta.json`) records only the idea, provider and time. Nothing says which `research/greenfield/<slug>/` folder it produces, so the dashboard cannot find `evaluation.json`. Analogy: the run is a shipment and the research folder is the warehouse shelf; right now the shipping label has no shelf number.

- `meta.json` gains an optional `research_dir`, stored relative to the project root.
- It is set three ways, first match wins: `gf_observe.py start --research-dir <path>`; a new `gf_observe.py link --research-dir <path> [--run]`; or automatically when `gf_runs.py coverage --evaluation <path>` runs, which already knows the evaluation path.
- Every read and write goes through `resolve_inside(project, path)` from W1. An escaping path or symlink is rejected with exit 2 and the W1 error helper.
- Writes to `meta.json` use the W1 atomic, permissioned writer (0600, per W15).
- Wave 4's `greenfield start` (W24) will set it when it scaffolds the folder; this wave only provides the field and the setters.

### 2. One verdict label table

A new `VERDICTS` dict in `score_project.py` (next to W12's canonical verdict) maps each decision to a display label, tone and one-line meaning. `/api/state` and `/api/decision` both send it, so the dashboard, scorer text output (W12) and DECISION.md (W29) never drift.

| Decision | Label | Tone | Meaning shown under the badge |
| --- | --- | --- | --- |
| `PROCEED_TO_BOUNDED_PILOT` | Proceed to bounded pilot | good | Core gates met. Pilot only, not scale. |
| `VALIDATE_BEFORE_BUILD` | Validate before build | warn | Run the next experiment before writing code. |
| `PIVOT` | Pivot | warn | Evidence shows a severe core weakness. |
| `NO_GO` | No go | bad | A confirmed fatal blocker overrides the score. |
| `RESEARCH_INCOMPLETE` | Research incomplete | neutral | Not a launch decision yet. |
| `INVALID` (dashboard only) | Can't score | bad | `evaluation.json` has input errors. |

### 3. Design tokens

All colors move to CSS custom properties on `:root`, with a dark set under `@media (prefers-color-scheme: dark)` guarded by `:root:not([data-theme="light"])`, and again under `:root[data-theme="dark"]`. Token names follow the [mockup](https://claude.ai/artifact/SEwPzhUYjF2hcydytzQzY8): `--bg --surface --raised --line --fg --muted --accent --good --warn --bad` plus `-bg` tints and `--q`/`--e` for the quality and evidence bars. W21 owns the values; W18 to W20 only use the names, so they can merge in any order.

## W18: Decision panel and /api/decision

**Goal.** The first thing on the dashboard is the verdict, recomputed from the evidence, never read on trust. A founder should know in five seconds what was decided, why, and what to do next.

### Endpoint design

`GET /api/decision?run=<id>` in the `Handler` class of `gf_observe.py`. It runs behind W9's Host, Origin and Sec-Fetch-Site checks like every API route.

1. Validate `run` with `VALID_RUN`, read `meta.json`, take `research_dir`. Missing → state `no_research_dir`.
2. `resolve_inside(project, research_dir)`; reject escapes and symlinks that leave the project (W6) with state invalid\_path. Then look for `evaluation.json` there. Missing → state `no_evaluation`.
3. Call W8's shared function, proposed name `recompute_decision(eval_path, project_root) -> (decision | None, errors, warnings)`. It loads with W1's size-limited loader, runs W7's never-throwing `validate()`, then `score()`. Errors → state `invalid` with the first 10 messages.
4. If `decision.json` exists beside it, load it the same safe way and compare its `decision` field to the recomputed one. Different → `stored.matches = false`. Older than `evaluation.json` (or than the ledger and verification report the validator reads) → `stale = true`.
5. Return only computed fields, never raw file contents.

Response shape:

```json
{
  "state": "ok",
  "research_dir": "research/greenfield/comp-bench",
  "etag": "9f2c41",
  "verdict": {"decision": "VALIDATE_BEFORE_BUILD", "label": "Validate before build", "tone": "warn",
              "headline": "Buyers feel the pain, but nobody has paid yet", "reason": "..."},
  "scores": {"weighted_quality": 61.0, "evidence_average": 2.12, "profile": "bootstrapped_saas"},
  "pillars": [{"key": "problem", "name": "Problem discovery", "weight": 20, "quality": 4, "evidence": 3}],
  "attention": {"confirmed_fatal": [], "plausible_fatal": ["B2"], "missing_pilot_gates": ["pricing_test"],
                "source_review_open": true, "warnings": ["..."], "warning_count": 7},
  "next_bet": {"id": "X1", "text": "5 paid pilot offers at $400/month..."},
  "next_step": {"text": "Record X1 results in the ledger, then re-score", "command": "gf_ledger.py record ..."},
  "stored": {"present": true, "decision": "VALIDATE_BEFORE_BUILD", "matches": true},
  "stale": false,
  "errors": []
}
```

**Caching.** Re-scoring is cheap but not free, and the client polls every 1.5 s. Cache the result in memory keyed by `(mtime_ns, size)` of `evaluation.json`, `decision.json`, the ledger and the verification report. The key's hash is the `etag`. `/api/state` carries `decision_etag`, so the client only fetches `/api/decision` when it changes (see W19). The endpoint also honours `If-None-Match` with a 304.

**Pillar names and weights** come from W4's `ROLES` table and the active profile in `gf_profiles.py`, not from hard-coded strings.

**`next_step` rules** (one line plus a copyable command):

| State | Next step shown |
| --- | --- |
| `no_research_dir` | Link this run to its research folder: `gf_observe.py link --research-dir research/greenfield/<slug>` |
| `no_evaluation` | Specialists still running, or write `evaluation.json` from the template |
| `invalid` | Fix the listed errors, then re-run the scorer with `--json` |
| `ok`, stale or mismatch | Re-run the scorer to refresh `decision.json` |
| `ok`, `RESEARCH_INCOMPLETE` | Name the unassessed pillars, for example "3 of 8 pillars unassessed: economics, distribution, timing" |
| `ok`, other verdicts | First open pilot gate, else the first planned experiment (`next_bet`) |

### Panel design

Follow the mockup's verdict band: two columns above 900px, stacked below.

- **Left:** "Decision" label, verdict badge in its tone, headline (24px), reason (muted), three KPIs (weighted quality /100, evidence average /5, fatal blockers), then a "Next bet" box with the copyable command.
- **Right:** pillar scorecard, one row per pillar with name, weight, a quality bar and an evidence bar (two colors, legend above), and `Q4 · E3` in mono. Under it, "Needs attention": up to 3 pills (plausible blocker, open gate, "N more warnings").
- **Integrity banner** above the band, only when needed: red for a mismatch ("decision.json says Proceed to bounded pilot; recomputed from evaluation.json: Validate before build. Showing the recomputed verdict."), amber for stale ("decision.json is older than evaluation.json").
- **Empty states** replace the band with one card: a muted title, one sentence, the command in a copy box. Never an empty or zero-filled scorecard.
- **Unassessed pillars** show a dashed outline bar and "Not assessed" instead of a zero bar, because zero quality and missing quality mean different things.
- Accessibility: badge text carries the meaning (never color alone); each bar pair has `aria-label="Quality 4 of 5, evidence 3 of 5"`; the panel is a `section` with `aria-labelledby`; a verdict change is announced once through the shared polite live region (W19).

### Files and functions

- `skill/scripts/gf_observe.py`: `decision_view(project, run_id)`, `_decision_cache`, `Handler` route, `link` subcommand, `--research-dir` on `start`, `decision_etag` in `current_state()`.
- `skill/scripts/gf_runs.py`: `coverage()` records `research_dir` when unset.
- `skill/scripts/score_project.py`: `VERDICTS` table; consumes W8's `recompute_decision()` and W12's `headline`.
- `skill/assets/mission-control.html`: `renderDecision(view)`, empty-state templates, banner.

### Acceptance criteria

1. With a filled fixture, the panel shows the same verdict, score and evidence average as `score_project.py --json` on that file.
2. A hand-edited `decision.json` claiming `PROCEED_TO_BOUNDED_PILOT` over a fixture that scores `VALIDATE_BEFORE_BUILD` shows the red banner and the recomputed verdict. This is the security review's H3 exploit, replayed against the dashboard.
3. `research_dir` of `../outside` or a symlink out of the project returns state `invalid_path` with HTTP 200 and no file content; the server log has no traceback.
4. A malformed `evaluation.json` (wrong types, 20 MB, invalid UTF-8) returns `invalid` or a size error, never a 500.
5. Each of the four non-ok states (no\_research\_dir, no\_evaluation, invalid, invalid\_path) renders its own card with a working copy button.
6. Two polls with no file change return 304 for `/api/decision`; touching `evaluation.json` changes the etag within one poll.

### Tests

- `tests/test_observability.py`: `test_decision_endpoint_states` (all five states, including ok), `test_decision_mismatch_flagged`, `test_decision_stale_flagged`, `test_decision_path_escape_rejected` (dotdot, absolute, symlink), `test_decision_etag_304`, `test_decision_matches_scorer_cli`.
- Fuzz: reuse W7's never-throws fuzz corpus through `decision_view()`.
- Playwright: the demo fixture with a linked research folder shows the badge text and 8 pillar rows.

### Edge cases

- Run with no `research_dir` but exactly one `research/greenfield/*/evaluation.json` in the project: do not guess. Show `no_research_dir` and suggest that path in the command. Guessing would show the wrong idea's verdict.
- Demo run (approved): link it to the bundled sample folder skill/assets/demo-research/, labelled as sample data, so the panel is visible in the demo and in the README screenshot (W28).
- Business model profile unknown: W7 already reports it; show `invalid`.
- Very long headline or warning: clamp to 2 lines with a title tooltip.
- `decision.json` present but `evaluation.json` missing: show `no_evaluation`, never the stored verdict.

### How it compares

ValidatorAI and IdeaProof give a verdict with no audit trail; a pasted or edited report looks identical to a real one. Here the verdict is recomputed on the founder's machine every time the inputs change, and tampering is called out on screen. The quality-versus-evidence split per pillar is also rare: most validators collapse it into one score, which hides the difference between "attractive market" and "someone actually paid".

## W19: Render only what changed

**Goal.** The page never loses keyboard focus, feed scroll, hover or a text selection on refresh, and does no work when nothing changed. Today `render()` rebuilds every panel with `innerHTML` every 1.5 s, and the UI review confirmed focus jumps to `<body>` after one tick.

Analogy: today the dashboard repaints the whole wall every 1.5 seconds. After this item it touches up only the tiles that changed, and skips the visit entirely when nothing did.

### Design

**Server: skip unchanged polls.**

- `/api/state` computes `rev` = short hash of `(event_count, last event id, task-manifest mtime_ns, decision_etag, agent quiet flags)` and sends it as an `ETag`. A request with a matching `If-None-Match` gets `304` with no body. Quiet flags are in the hash because an agent turns quiet with no new event.
- Optional `since=<event id>` returns only events after that id (`events_delta`) plus the full small parts (meta, agents, stats). Falls back to the last 300 when the id is unknown, with `reset: true`.

**Client: one store, small patchers.** The inline script is reorganized into named functions inside the same HTML file (no build, no dependency, CSP unchanged):

- `store` holds the last state, the decision view and UI state (selected agent, filter, theme).
- `poll()` fetches with `If-None-Match`; on 304 it only updates the "updated Ns ago" clock.
- `patchAgents(agents)`: builds the 9 rows once, keyed by role id (`data-agent`), then on each change sets only the `textContent`, `className` or attribute that differs. A helper `setText(el, value)` skips the write when equal, so the DOM stays untouched.
- `appendEvents(delta)`: the feed is newest-first. New items are created and prepended in one `DocumentFragment`. Existing nodes are never re-created. A `Set` of seen ids prevents duplicates. The list is capped at 500 nodes, trimming the oldest.
- `patchMetrics`, `patchTimeline`, `renderDecision` follow the same rule: build once, patch fields.
- Rows and chips use event delegation (one listener on the container), so patching never loses handlers.

**Scroll and focus.**

- If the feed is scrolled to the top, new items appear in place. If the user has scrolled down, keep their position by adding the inserted height to `scrollTop`, and show a "3 new events" pill at the top of the feed that jumps back up.
- Because nodes are reused, focus and `aria-pressed` survive automatically. The test proves it rather than code restoring it.

**Polling hygiene.**

- Pause when `document.hidden`, resume with an immediate poll on `visibilitychange`.
- Back off on errors: 1.5 s, 3 s, 6 s, capped at 15 s, reset on the first success. W20 shows this state in the header.
- Use `AbortController` with a 5 s timeout so a hung request cannot stack up behind the next tick.

**Announcements.** One visually hidden `aria-live="polite"` region. Only these are announced, at most one per 10 s: an agent finished or failed, the run finished, the verdict changed. Tool calls are never announced.

### Files and functions

- `skill/scripts/gf_observe.py`: `state_rev()`, ETag and 304 handling in `Handler._json`, `since` support in `current_state()`.
- `skill/assets/mission-control.html`: `store`, `poll`, `setText`, `patchAgents`, `appendEvents`, `patchMetrics`, `patchTimeline`, `announce`.

### Acceptance criteria

1. Focus an agent row with Tab, wait for two state changes: `document.activeElement` is still that row.
2. Scroll the feed to 400px, emit 5 events: the first visible item is the same node, and the "5 new events" pill shows.
3. With no new events, 10 polls cause zero DOM mutations (counted with a `MutationObserver`) and the server answers 304.
4. Feed never holds more than 500 nodes after 2,000 events.
5. Stop the server: polling backs off to 15 s; restart it: the next poll succeeds and the interval resets.
6. CPU while idle on a finished run is effectively zero (no layout or paint per tick in a Chrome performance trace).

### Tests

- Playwright smoke test `tests/test_dashboard_browser.py` (this is the wave's gate): start `gf_observe.py serve` on a free port with the demo run, click an agent row, emit events from the test, assert criteria 1 to 3. Skips cleanly locally when Playwright is not installed; the W3 CI job installs it, and because CI is required on main, a skip there counts as a failure (the job sets GF\_REQUIRE\_BROWSER=1).
- `tests/test_observability.py`: `test_state_etag_304`, `test_state_since_delta`, `test_state_since_unknown_resets`, `test_rev_changes_when_agent_turns_quiet`.

### Edge cases

- Run switch in the picker: clear the store and the seen-id set, rebuild once. This is the only full rebuild.
- Events file truncated or rotated so `since` points nowhere: server sends `reset: true`, client rebuilds the feed.
- Two tabs open: each polls independently; 304s keep the cost negligible.
- Event ids are uuid4 hex, so they are safe as DOM keys after `esc()`.
- `EVENT_LIMIT` (10,000) reached: the server stops reading at the cap today, so `rev` stops changing. Fix by reading the tail for the delta and showing "Showing the latest 10,000 events".

### How it compares

Langfuse and Phoenix get stable views from React and a backend. The Claude Code hooks dashboard pushes over WebSockets from a Bun server. We get the same stability with ETag polling and keyed patching on Python's standard library, which keeps the tool installable with zero dependencies. Pausing when hidden and the 304 path make it cheaper to leave open all day than any of them.

## W20: Status you can trust

**Goal.** Every status, label and bar on the page means exactly one thing and says where it came from. Five fixes, one per UI finding.

### 1. DEMO shown once (U5)

Today the pill reads "DEMO · RUNNING · demo" and the picker "DEMO · DEMO · B2B…", because the demo idea text starts with "DEMO ·" and the provider is "demo".

- `demo` subcommand stores the idea without a prefix ("B2B compensation benchmarking AI"); `meta.demo = true` is the only marker.
- One client function `runLabel(meta)` builds every label from fields: picker option `Demo · <idea> · 3 Nov 02:05`, header pill `Running · Claude Code + Codex`.
- Provider display names: `claude` → Claude Code, `codex` → Codex, `both` → Claude Code + Codex; `demo` and `manual` are hidden.
- DEMO appears only as the amber notice bar and one badge on the picker option. Old runs whose idea already starts with "DEMO ·" get the prefix stripped at display time.

### 2. One agent status (U6)

Today a card can say COMPLETED while its checkpoint line says "queued". `current_state()` gains a reconciled `display` object per agent; the raw `status` stays for existing tests and tools.

| Hook status | Checkpoint | Shown | Source note |
| --- | --- | --- | --- |
| failed, or any | failed | Failed | which one failed, with its summary |
| completed | completed | Done | Checkpointed |
| completed | queued or running | Done | Not checkpointed (amber) |
| completed | not planned | Done | none |
| running | any but failed | Running | current activity |
| quiet | any but failed | Quiet | No activity for 5 min; not a failure |
| queued | running | Claimed | Claimed in checkpoints, no hook events yet |
| queued | completed | Done | From checkpoint (reused or hooks off) |
| queued | queued or not planned | Queued | Red team: "Waits for all 8 specialists" |

**Hooks-off detection.** If checkpoints show claimed or completed tasks but the run has zero specialist hook events, show one muted line above the list: "Live hooks not detected, so statuses come from checkpoints only. Turn them on with `configure_hooks.py install`." This replaces silent disagreement with an explanation.

### 3. Real connection state (U7)

The header's green "LOCAL OBSERVABILITY" dot is static today, and "Connection lost" reuses the amber DEMO style. One header pill, driven by `store.lastOk` and the W19 backoff:

| Condition | Pill | Tone |
| --- | --- | --- |
| Last success under 5 s ago | Live · updated 2s ago | good |
| 5 to 30 s since success, no error | Updated 18s ago | neutral |
| Request failing | Disconnected · retrying in 6s | bad, with a Retry now button |
| Tab hidden | Paused | neutral |
| Run completed or failed | Finished · 02:41 | neutral; polling slows to 10 s |

The seconds tick from a local 1 s timer that only rewrites the pill text. On disconnect, the rest of the page stays visible but dims to 70% opacity with "Showing data from 02:39".

### 4. Grouped feed with filters (U9)

Today nine "Task Planned" events bury real activity, and every tool call shows twice (started and completed).

- **Grouping**, done client-side in `appendEvents()` so it works with deltas: consecutive `task_planned` events collapse into "Run planned: 9 specialist tasks"; `tool_completed` never gets its own row and marks its matching started row with a check; repeated same-agent same-tool calls within 60 s collapse into "Searched the web ×4". A group is keyed by its first event id and updated in place.
- **Filter chips**: All, Agents (`agent_*`, `task_*`, `run_*`), Tools (`tool_*`), Sources (`source_seen`), Warnings (`warning`, `*_failed`). Each chip shows a count. Chips combine with the selected agent (AND), and the agent filter gets its own clearable chip. `role="group"` with `aria-pressed` buttons.
- Chip and agent state live in the URL hash (`#run=...&f=warn&agent=gf-market`) so a refresh or a shared link keeps the view. Runs are local, so the hash never leaves the machine.
- Empty filter result: "Nothing matches this filter yet" with a Clear button.

### 5. Run-scaled timeline (U10)

Today the scale is `max(now, ...)`, so bars shrink to dots on a long or finished run, and labels are first words ("Unit", "Independent").

- Domain: start = `meta.created_at`; end = the `run_completed` or `run_failed` timestamp if present, else now. The scale freezes when the run ends.
- Bars merge into the agent rows, as in the mockup: one track under each specialist, so the name is the full W4 display name and there is no separate label column.
- Axis: 4 tick labels; `HH:MM` for runs under 24 h, `3 Nov 14:00` beyond. Minimum bar width 4px so a short task stays visible.
- Queued agents show an empty track; quiet agents show a hatched tail from last activity to now; failed agents end in a red cap.

### Files and functions

- `gf_observe.py`: `reconcile(agent, task_status)`, `hooks_detected`, provider names in `ROLES`-adjacent constants, demo idea text, `run_window` (start, end) in `current_state()`.
- `mission-control.html`: `runLabel`, `connectionPill`, `groupEvent`, `chipCounts`, hash state, `patchTimeline`.

### Acceptance criteria

1. No string on the page or in the picker contains "DEMO" twice.
2. For every row of the reconciliation table, a fixture produces exactly that label and note.
3. Killing the server turns the pill red within one failed poll; the green dot never shows while disconnected.
4. A freshly planned run shows one "Run planned" row, not nine.
5. On a finished 3-hour run, every completed agent's bar is at least 4px wide and the axis spans the run, not the time since.

### Tests

- `tests/test_observability.py`: `test_reconcile_matrix` (table-driven over all rows), `test_hooks_off_detected`, `test_demo_idea_has_no_prefix`, `test_run_window_frozen_after_completion`.
- Playwright: kill the server mid-test and assert the pill text and tone; click the Warnings chip and assert only warning rows remain and the hash updated; reload and assert the filter persisted.

### Edge cases

- Clock skew between event writers: sort by timestamp but clamp bars to the run window.
- An agent started twice (retry): the bar spans the latest attempt; the row shows "2 attempts" from the checkpoint `attempts` field.
- Manifest missing (no `gf_runs.py plan`): checkpoint column is simply absent, no "not planned" noise.
- Unknown event types from a newer writer: shown under All with a generic label, never crash.

### How it compares

The Claude Code hooks dashboard shows raw hook events with a regex filter; it cannot tell you that an agent finished but never saved its work. Langfuse and Phoenix timelines scale to the trace, which we now match. Reconciling two independent signals (hooks and checkpoints) into one honest status with its source is something none of them do.

## W21: Visual polish

**Goal.** The dashboard looks finished in light and dark, on a laptop and a phone, and every number reads correctly. Four fixes, all CSS and small helpers in `mission-control.html`.

### 1. Four-tile run strip (U12)

Today 8 tiles sit in a 6-column grid, leaving an orphan row of 2, and unknowns show as a large "0" or "Unknown". The Decision panel (W18) now carries the KPIs that matter, so the strip shrinks to four grouped tiles, as in the mockup:

| Tile | Big number | Small line |
| --- | --- | --- |
| Specialists | 6 | of 9 done · 2 running · 1 warning |
| Tool calls observed | 143 | none |
| Sources recorded | 38 | 27 excerpts located |
| Reported cost | $1.84, or muted "Not reported" | "Set a rate with `gf_runs.py set-rate`" when unknown; token count when known |

Checkpoints move into the Specialists tile and agent rows; warnings link to the Warnings filter chip. Grid: 4 columns above 900px, 2 below, never an orphan.

### 2. `plural()` (U13)

`plural(n, 'source')` returns "1 source" or "2 sources" with `toLocaleString()` for the number; an optional third argument handles irregulars ("1 attempt", "activity"/"activities"). Every count string in the file goes through it; a test greps the HTML for template literals that put a number before a hard-coded plural noun.

### 3. Type floor of 12px (U14)

- Raise every 9 to 11px style (`.status`, `.small`, `.feed-meta`, `.overline`, footer, legend) to 12px minimum; body stays 14px.
- Statuses become pills (text plus dot), as in the mockup, instead of 9px uppercase letter-spaced text.
- Numbers use `font-variant-numeric: tabular-nums` so counts do not jitter as they tick.

### 4. Light theme and phone width (U15)

- **Theme:** tokens from the shared foundations. Default follows `prefers-color-scheme`; a small sun/moon toggle in the header sets `data-theme` on `<html>` and remembers it in `localStorage`, wrapped in `try/catch` so a blocked storage still renders. `color-scheme` is set per theme so form controls and scrollbars match.
- **Contrast:** every text token pair meets WCAG AA (4.5:1 for body text, 3:1 for the bar fills against their track) in both themes. Status never relies on color alone.
- **Phone:** the run picker gets `max-width: 100%` and the header wraps; side gutters 16px; agent rows go to one column; the Decision band stacks; pillar rows put bars on their own line under 520px, as in the mockup. Remove `backdrop-filter`, which is costly on low-end phones and adds little.
- **Motion:** bar width transitions only under `prefers-reduced-motion: no-preference`.
- **Print** (small addition): a `@media print` rule hides the feed and header controls and prints the Decision band and scorecard in light colors, so the page doubles as a one-page summary.

### Files and functions

- `skill/assets/mission-control.html` only: `:root` tokens, dark overrides, `plural()`, `applyTheme()`, CSS for strip, pills, breakpoints and print.

### Acceptance criteria

1. At 1440px, the run strip is one row of 4; at 390px, two rows of 2. No orphan tile at any width from 320 to 1920px.
2. No text node on the page computes below 12px (checked in the browser).
3. At 390px, `document.documentElement.scrollWidth <= innerWidth` in both themes and with the longest demo idea.
4. Light and dark both pass an automated contrast check on all token pairs.
5. No "1 sources", "1 tool calls" or "1 specialists" anywhere.
6. With `localStorage` throwing, the page renders in the system theme with no console error.

### Tests

- Playwright: render demo at 1440 and 390 in both color schemes; assert criteria 1 to 3 and 6; save four screenshots as CI artifacts (also handy for W28's README screenshot).
- `tests/test_observability.py`: `test_contrast_tokens` parses the `:root` blocks and computes WCAG ratios in pure Python (a few lines of math, no dependency); `test_no_hardcoded_plurals` greps the HTML.

### Edge cases

- Very long idea text: clamp to 2 lines in the header with the full text as a `title`.
- Cost when tokens are reported but no rate: show tokens, cost stays "Not reported".
- High-contrast mode (`forced-colors: active`): bars get a 1px border so they stay visible.

### How it compares

Langfuse and Phoenix offer light and dark themes; the open-source hooks dashboard does not document one. Few local dev dashboards work at phone width or print a usable summary. Doing all of it in one dependency-free HTML file is the differentiator: it opens instantly and works offline on a plane.

## Beyond the plan: upgrades that would make it best in class

The four items fix what the UI review found. These five go further, and the first three are what no competitor offers. All keep the zero-dependency, local-only rules. Aaron approved the first two for this wave on 3 Nov; the other three remain proposals for a follow-up.

| Upgrade | What the founder gets | Effort | Why it beats the field |
| --- | --- | --- | --- |
| **What would change the verdict** | Under the badge: "To reach Proceed to bounded pilot: economics evidence 1 → 3, distribution evidence 1 → 3, close gate `pricing_test`, review 4 sources." | 0.5 day | Validators say "risky"; this names the exact, checkable gap, derived from the same rules as the score |
| **Evidence drill-down** | Click a pillar row: its claims with source link, publication date, excerpt found or not (from `source-verification.json`), and ledger receipts | 0.5 day | The top complaint about AI validators is "no sources"; this puts every source one click from the score |
| **Shareable snapshot** | `gf_observe.py snapshot --run <id>` writes one offline HTML file with the state embedded, to send a cofounder or investor | 0.5 day | Langfuse and Phoenix need an account or server to share; this is a file |
| **Verdict history** | Each recompute appends `(time, verdict, score, evidence)` to the run; a small line shows how evidence grew across re-scores | 0.25 day | Shows learning over time, which is the point of the experiment ledger |
| **Keyboard and tab title** | `j`/`k` move between specialists, `f` cycles filters, `?` shows keys; tab title reads "Done · Validate before build" | 0.25 day | Lets the page sit in a background tab and still say when it is done |

Design notes for the top two:

- **Verdict gap** is a pure function `verdict_gap(data, profile) -> list[Requirement]` in `score_project.py`, next to `score()`. It reads the same thresholds (`total >= 75`, core pillars quality and evidence at least 3, no plausible fatal blockers, gates passed, source review closed) and returns each unmet one with its current and needed value. Test: for every fixture, applying the listed requirements and re-scoring yields the target verdict. W12's scorer text output can print the same list, so the terminal and dashboard agree.
- **Evidence drill-down** adds `GET /api/evidence?run=<id>&pillar=<key>`, which returns only claim id, short text, URL (passed through `safe_url`), published date, `fetch_status`, `excerpt_check` and linked ledger event ids. Never page content. Same path confinement and caching as W18.

**Acceptance for the two approved upgrades.** (1) For every scorer fixture, applying the requirements `verdict_gap()` lists and re-scoring reaches the target verdict, and the dashboard and W12 terminal output show the same list. (2) Clicking a pillar row opens its claims within one poll; every link passes `safe_url`, an escaping `research_dir` returns `invalid_path`, and no page text is ever returned. Tests: `test_verdict_gap_reaches_target`, `test_verdict_gap_empty_when_proceed`, `test_evidence_endpoint_fields_only`, `test_evidence_path_escape_rejected`, plus a Playwright click-through. Edge cases: `RESEARCH_INCOMPLETE` lists unassessed pillars first; a confirmed fatal blocker makes the gap say "Resolve blocker B1" rather than listing scores; a missing `source-verification.json` shows claims with "Not checked yet".

## Dependencies, sequencing and gate

This wave cannot start until waves 0 to 2 merge, because it calls their functions. The contracts below are what it assumes; sibling threads own the specs.

| Needs | From | Contract this wave assumes |
| --- | --- | --- |
| `resolve_inside()`, size-limited JSON load, atomic 0600 write, error helper | W1 (wave 0) | Raises a typed error on escape or oversize; never returns a path outside the root |
| `ROLES` table | W4 (wave 0) | Python dict with display name per role; `/api/state` sends it as `roles` and the HTML drops its own copy |
| Playwright in CI | W3 (wave 0) | Required CI check on main (approved); the job can `pip install playwright` for the browser test only; runtime stays standard library |
| Path confinement on runs | W6 (wave 1) | Symlinks out of the project are rejected |
| Never-throwing `validate()` | W7 (wave 1) | Returns `(errors, warnings)` for any JSON value |
| Re-scoring function | W8 (wave 1) | `recompute_decision(eval_path, project_root)` exposed for reuse, not private to the portfolio |
| Host, Origin, Sec-Fetch-Site checks | W9 (wave 1) | Applied to every `/api/*` route, including the new ones |
| Canonical verdict and `headline` | W12 (wave 2) | `score()` returns `headline`; `memo_label` kept one release |
| File permissions | W15 (wave 2) | `meta.json` writes stay 0600 |

Later waves depend on this one: W22 and W24 (wave 4) should set `research_dir` from `greenfield start` and expose `greenfield serve` and `greenfield link`; W28 (wave 5) uses the W21 screenshots; W29 reuses the `VERDICTS` table so DECISION.md matches the badge.

Aligned with Wave 0 decisions (3 Nov): Python 3.11 is the minimum, so the new code may use `datetime.fromisoformat` with any ISO form and `except*` is not needed; the single role name is "Execution & founder fit" everywhere, taken from W4's `ROLES`, never typed in the HTML.

### Order inside the wave

1. Shared foundations: `research_dir` and `link`, `VERDICTS`, token names (half a day).
2. W19 server side (ETag, 304, `since`) and the client store and patchers, with the Playwright harness, because W18 and W20 build on the store (half a day).
3. W18 endpoint and panel (half a day).
4. W20, five fixes, each its own commit (half a day).
5. W21 polish and screenshots (a quarter day).
6. Verdict gap and evidence drill-down, approved (1 day).

### Gate for merging

- Full unittest suite green, including the new tests listed under each item.
- Playwright smoke test green: demo run loads, Decision panel shows, focus and feed scroll survive two refreshes, filter persists across reload, no overflow at 390px in both themes.
- The H3 replay (forged `decision.json`) shows the red banner.
- A manual pass with the keyboard only (Tab, Enter, Space) reaches every control.

### Open questions

- Resolved: the verdict gap and evidence drill-down join this wave (Aaron, 3 Nov).
- Resolved: the demo ships with a bundled sample research folder (skill/assets/demo-research/), clearly labelled as sample data, so the demo and README screenshot show a full Decision panel (Aaron, 3 Nov).
- Polling stays at 1.5 s while running. Server-sent events would be smoother, but `ThreadingHTTPServer` would hold one thread per open tab; not worth it now.
