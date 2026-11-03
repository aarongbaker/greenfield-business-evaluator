# GreenField Wave 2 spec: output and guardrails

Nov 3, 2026 · @Aaron

## Summary

Wave 2 turns a correct-but-raw engine into one that speaks plainly and fails safe: the scorer prints a one-screen verdict with a headline and a next step, the portfolio report can't be broken by a crafted name, `start` stops clobbering live runs, private idea text stops being world-readable, the source fetcher closes its last SSRF gaps, and the README stops saying false things. Six work items, W12 to W17, about one day, shipped as one PR per Aaron's decision.

Analogy: Wave 1 changed the locks; Wave 2 fixes the doorbell, the mailbox and the sign on the door. Nothing here changes how a verdict is computed, only how it is shown and what can go wrong around it.

| Order | Item | Main files | Waits for |
| --- | --- | --- | --- |
| 1 | W12 scorer verdict, headline, text output | `score_project.py`, `SKILL.md`, `references/outputs.md`, `references/v2-workflows.md` | W7 (validator), W8 (portfolio reads scorer fields) |
| 2 | W13 portfolio escaping, labels, placeholder check | `gf_portfolio.py`, `portfolio-template.json` | W8, W12 (shared verdict label table) |
| 3 | W15 private file permissions, `.gitignore` offer | `gf_observe.py`, `gf_runs.py`, `gf_ledger.py`, `score_project.py`, `gf_evidence.py`, `gf_portfolio.py`, `install.py` | W1 (`write_private()` helper) |
| 4 | W14 active-run guard | `gf_observe.py` | W15 (same file, land second to avoid conflicts) |
| 5 | W16 fetcher hardening | `gf_evidence.py` | none inside the wave |
| 6 | W17 README factual fixes | `README.md` | W15 (README should mention the new `.gitignore` offer) |

W16 can be built in parallel with everything else. All new code stays standard library only, matching the project rule and Aaron's packaging decision.

New findings while speccing, folded in below: `score()` reports `source_review_gate_open: true` precisely when there is *no* open source-review problem (the name is inverted, see W12), and `gf_observe.py demo` also replaces the active run, so it gets the same guard as `start` (W14).

## Competitive bar

The free AI idea validators give a score from what you typed; the paid ones add sources but leave the call to you or bury it in a 100-page report. Nobody separates *how attractive* an idea is from *how well evidenced* it is, and nobody gates a go verdict on proof that a human saw a real customer act. That gap is GreenField's moat, and Wave 2 is about making it visible in one screen.

| Tool | Price | What you get | Where GreenField wins after Wave 2 |
| --- | --- | --- | --- |
| [ValidatorAI](https://preuve.ai/blog/best-startup-validation-tools-2026) | Free | Score plus advice, no sources | Sourced claims, quality vs evidence split, verdict gated on receipts |
| [IdeaProof](https://preuve.ai/blog/best-startup-validation-tools-2026) | 1 free validation, then credit packs from €19.99 | Viability score with GO / NO-GO, mostly unlinked figures | Same one-word verdict, but every gate is auditable and offline-reproducible |
| [DimeADozen](https://preuve.ai/blog/best-startup-validation-tools-2026) | Free score, $129 full report | 100+ page report with linked claims, no build verdict | One-screen verdict, headline and next experiment instead of a long read |
| [Preuve AI](https://preuve.ai/blog/best-startup-validation-tools-2026) | Free check, $59 per report | Score, blockers, linked claims, build verdict, pivots | Free, local, no idea text leaves the machine, portfolio ranking across ideas |
| [WorthBuild](https://preuve.ai/blog/best-startup-validation-tools-2026) | Free score, $5 per report | Go / Pivot / Stop verdict, complaint mining | Verdict cannot be reached on AI say-so (human-attested ledger) |
| ChatGPT deep research | Free tier, Plus $20/mo | Linked answer, verdict only if prompted | Fixed, testable gates instead of a prompt-dependent opinion |

The comparison above comes from a roundup written by Preuve's founder and a [second tester's write-up](https://dev.to/marketoracle/i-tested-7-free-ai-startup-idea-validators-most-are-useless-3-are-worth-your-time-15fd); treat their claims about rivals as approximate. The second piece's sharpest complaint about weak tools is an answer like "This could work but do more research", which is exactly what an unexplained `VALIDATE_BEFORE_BUILD` reads like today. W12's headline and next step are the fix.

For the CLI itself, the bar is the [Command Line Interface Guidelines](https://cdn.jsdelivr.net/npm/@hacxy/skills@0.1.0/skills/create-cli/references/cli-guidelines.md): human output by default on a TTY, `--json` for machines, results on stdout and messages on stderr, colour off under `NO_COLOR` or a non-TTY, no stack traces, prompt only when stdin is a TTY, and a dry run or confirmation before anything scary. Every Wave 2 item below is checked against that list.

## W12. Scorer: one verdict, a headline, readable output

Closes UI U3, U4 and UX8 (scorer part). Today the scorer prints 68 lines of JSON on stdout and then 11 `WARNING:` lines on stderr for the shipped template, and `decision.json` carries two labels for one verdict (`RESEARCH_INCOMPLETE` next to `memo_label: "VALIDATE_BEFORE_BUILD (research incomplete)"`).

**Goal.** A person running the scorer in a terminal sees the verdict, why, and what to do next on one screen. Agents and the portfolio keep getting exactly the JSON they get today, plus three new fields.

### Design

1. **One verdict table.** Add `VERDICTS` to `score_project.py`, keyed by the five existing codes. Each entry has `label` ("Validate before build"), `tone` (good, warn, bad, neutral) and `meaning` (one sentence). The codes and the decision logic in `score()` do not change. W13, W18 and W29 import this table, so labels are defined once.
2. **New `decision.json` fields**, all deterministic and template-built, never model-written:
   - `verdict_label`: the human label from `VERDICTS`.
   - `headline`: at most 90 characters, built by `headline(result, data)`. Rules: NO\_GO names the first confirmed fatal blocker ("Fatal blocker confirmed: B1 payroll data cannot be shared"); RESEARCH\_INCOMPLETE says what is missing ("Research incomplete: 8 of 8 pillars unassessed, no live web research"); PIVOT names the weak core pillar; PROCEED says "All five core pillars clear the evidence gates: run a bounded pilot"; VALIDATE names the weakest core pillars by evidence ("Evidence is thin on economics and distribution: test these before building").
   - `next_step`: one imperative sentence chosen by rule, for example "Record a paid-test result for economics with gf\_ledger.py, then re-score" or "Fill pillar quality scores and run live web research". The first experiment in `data["experiments"]` is used when present.
   - `source_review_pending`: boolean, true when public citations still need a human source review. This replaces `source_review_gate_open`, whose value is currently `not source_risk`, so it reads `true` when the gate is in fact clear. Keep the old key for one release with its current value and list it as deprecated.
   - `deprecated_fields: ["memo_label", "source_review_gate_open"]`. Both stay populated for one release (2.x), then are removed in 3.0 per the plan's conflict resolution.
3. **Output modes**, decided in `main()`:

| Invocation | stdout | stderr |
| --- | --- | --- |
| stdout is a TTY, no flags | Text summary | Nothing (warnings are inside the summary) |
| Piped, or `--json` | Decision JSON, unchanged shape plus new fields | `WARNING:` lines as today |
| `--output FILE` on a TTY | Text summary plus "Saved decision.json to FILE" | Nothing |
| `--output FILE` piped, or with `--json` | Nothing (JSON goes to the file) | `WARNING:` lines |
| Validation fails | Nothing | Grouped error list from W7's helper, exit 2 |

Add `--json` (force JSON), `--all-warnings` (show every warning in text mode) and `--no-color`. Colour is also off when `NO_COLOR` is set, `TERM=dumb`, or stdout is not a TTY. SKILL.md, `references/outputs.md` and `references/v2-workflows.md` are updated to always pass `--json`, so agents never depend on TTY detection.

4. **Text summary layout**, rendered by a pure function `render_text(result, *, color, width=80, glyphs="unicode")`, matching the [mockup's terminal panel](https://claude.ai/artifact/SEwPzhUYjF2hcydytzQzY8):

```text
● VALIDATE BEFORE BUILD   Compensation benchmarking · as of 2026-11-03
Evidence is thin on economics and distribution: test these before building

Weighted quality 61/100   Evidence avg 2.1/5   Fatal blockers 0   Profile bootstrap_saas

Pillar         Wt  Quality      Evidence
problem        20  ████░ 4      ███░░ 3
...
! 3 warnings (top 5 shown; --all-warnings for every one)
  • Plausible fatal blocker B2 unresolved
Next: Record a paid-test result for economics with gf_ledger.py, then re-score.
Heuristic triage, not a probability of commercial success.
```

Weights shown are the active profile's weights, not `BASE`. Bars fall back to `#####` / `.....` when `sys.stdout.encoding` cannot encode the block glyphs. A null quality shows as "— not assessed".

5. **Warning grouping.** `summarize_warnings(warnings)` collapses repeats by pattern, so eight "pillars.X: no claims linked" lines become "8 pillars have no linked claims: competition, distribution, …". Order: fatal or plausible blockers, unmet pilot gates, source review, research gaps, then the rest. The raw list in JSON is untouched.

### Files and functions

- `skill/scripts/score_project.py`: add `VERDICTS`, `headline()`, `next_step()`, `summarize_warnings()`, `render_text()`, `bar()`; extend `score()` return; rework `main()` output branch. `bar()` is reused by W29's DECISION.md template.
- `skill/SKILL.md`, `skill/references/outputs.md`, `skill/references/v2-workflows.md`: add `--json` to every scorer call; document the new fields and the deprecations.
- `tests/test_skill.py` (or a new `tests/test_scorer_output.py`): snapshot and mode tests below.

### Acceptance criteria

- [ ] On a TTY, scoring the shipped template prints at most 25 lines, leads with the verdict line, and writes nothing to stderr.
- [ ] `score_project.py template.json | python3 -m json.tool` succeeds, and every key present before W12 is present after with the same value.
- [ ] `headline` is never empty, never over 90 characters, and contains no newline for any reachable verdict.
- [ ] `source_review_pending` is true exactly when the existing `source_risk` condition is true.
- [ ] `NO_COLOR=1` and piped output contain no ANSI escape bytes.
- [ ] Exit codes unchanged: 0 scored, 2 unreadable or invalid input.

### Tests

- Snapshot tests of `render_text()` for the template and for a filled fixture that reaches VALIDATE\_BEFORE\_BUILD, stored under `tests/snapshots/`, with colour off. These are the wave gate.
- One fixture per verdict asserting `headline` and `next_step` text and length.
- Mode matrix: patch `sys.stdout.isatty` to True and False, with and without `--json` and `--output`, and assert which stream gets what.
- JSON compatibility: load a decision produced before W12 (checked into fixtures) and assert its keys are a subset of the new output's keys.
- ASCII fallback: render with `glyphs="ascii"` and assert only ASCII bytes.

### Edge cases

- `weighted_quality_0_to_100` is null (any pillar unassessed): show "— / 100 (incomplete)".
- A project name with emoji or right-to-left text: truncate by characters, never split a surrogate pair; strip control characters before printing.
- More than five warning groups: show five, then "+N more".
- Windows consoles with cp1252: covered by the ASCII fallback, even though W26 makes Windows fail clearly elsewhere.
- A user who scripts on the old behaviour with `| jq`: unaffected, because piped output stays JSON.

### Compared with the best tools

IdeaProof and WorthBuild give a one-word verdict; DimeADozen gives depth but no call. W12 gives both in one screen: a one-word verdict, a sentence of why, the pillar-by-pillar split between quality and evidence, and the single next experiment. The text output follows CLI guidelines that none of the web tools need to meet, and it runs offline in under a second.

## W13. Portfolio: safe Markdown, readable labels, placeholder check

Closes Sec L2, UI U16 and UX10. Today `to_markdown()` escapes only `|` in `next_test`; opportunity names and the recommendation (which embeds a name) go in raw, verdicts print as `VALIDATE_BEFORE_BUILD`, and running the shipped `portfolio-template.json` fails with a bare file-not-found on `relative/path/evaluation.json`.

**Goal.** The portfolio report renders correctly whatever the opportunity names contain, reads like a memo, and the template tells a new user exactly which fields still need filling.

### Design

1. **`md_cell(value, limit=120)`** in `gf_portfolio.py` (or in `gf_common.py` if W1 wants a shared home). It converts `None` to an em dash, replaces CR, LF and tab with a space, strips other control characters, backslash-escapes ` \ | * _  ` \[ \] < > # \~` , and truncates with an ellipsis at  `limit`characters. Every interpolated value in`to\_markdown()\` goes through it: rank, name, verdict label, scores, range, next test, unranked reason, and the recommendation sentence (escaped once as a whole, not per name).
2. **Readable labels.** The Decision column shows `VERDICTS[code]["label"]` from W12 ("Validate before build"). The JSON output keeps the raw code in `decision` and adds `verdict_label`. An unknown or missing code prints "Unknown verdict".
3. **New report columns.** Add "Why unranked" (from `unranked_reason`), and, once W8 lands, show its mismatch flag as "Stored decision disagrees with re-score" so the H3 defence is visible to the reader, not just enforced.
4. **Placeholder validation.** Before any file is opened, `find_placeholders(manifest)` walks the manifest and collects JSON paths whose value is a string starting with `REPLACE_`, the literal template paths `relative/path/evaluation.json` or `relative/path/decision.json`, or `null` where `evaluate_portfolio` needs a number. If any exist, exit 2 with one message: "portfolio.json still has 9 placeholders to fill: opportunities\[0\].name, opportunities\[0\].founder\_fit\_0\_to\_5, … See the \_help notes in the template." This runs before path resolution so the user sees the real problem, not a file error.
5. **Template help.** JSON has no comments, so add `"_help"` string keys to `portfolio-template.json` next to each block ("Founder fit 0 to 5, with proof in founder\_fit\_rationale"). The loader ignores any key starting with `_`. Mention the template in `references/v2-workflows.md`.

### Files and functions

- `skill/scripts/gf_portfolio.py`: add `md_cell()`, `find_placeholders()`; call the latter at the top of `evaluate_portfolio()`; rewrite `to_markdown()` cell building; add `verdict_label` and mismatch display.
- `skill/assets/portfolio-template.json`: `_help` keys.
- `tests/test_v2.py`: new tests below.

### Acceptance criteria

- [ ] A name of `x | [click](javascript:alert(1)) <img src=x>` produces a table whose every row has the same number of cells as the header, and the rendered Markdown contains no live link or HTML tag.
- [ ] Running the shipped template prints the placeholder list and exits 2, with no Python traceback and no file-not-found message.
- [ ] No raw verdict code appears in the Markdown report; all codes still appear in the JSON.
- [ ] Names that contain no special characters render byte-for-byte as before (aside from the label column change).

### Tests

- `md_cell` table test: pipe, backslash, newline, tab, backticks, brackets, angle brackets, `None`, a 500-character string, an emoji.
- Injection test: build a report with the hostile name above, parse the table rows by splitting on unescaped pipes, assert constant cell count.
- Placeholder test: load the shipped template, assert exit code 2 and that every `REPLACE_` path appears in the message.
- Label test: one opportunity per verdict code, assert the Markdown shows labels and the JSON keeps codes.

### Edge cases

- Two opportunities whose names differ only by escaped characters: names are still checked for uniqueness on the raw value.
- A legitimate name containing `REPLACE_` mid-string ("Auto-REPLACE\_parts"): only a value that *starts* with `REPLACE_` counts.
- A manifest with `_help` keys removed: still valid.
- Very long `next_test` text: truncated in Markdown, full in JSON.

### Compared with the best tools

No free validator ranks several ideas against each other with explicit cash and time constraints; DimeADozen sells a three-report bundle but no comparison. W13 makes that unique feature safe to share: the Markdown can be pasted into a GitHub issue, a Notion page or a cofounder email without a crafted name breaking it, and a first-time user gets a to-do list instead of a stack trace.

## W14. `start` refuses to replace an active run

Closes UX3. Reproduced again while speccing: two `gf_observe.py start` calls in a row printed two run ids with no warning, and the second silently became active. SKILL.md tells agents "Do not start a new run over an active one", but nothing enforces it. `gf_observe.py demo` has the same flaw: it calls `new_run()` and so also hijacks `active.json`.

**Goal.** A live run can only be replaced on purpose, and the old run is left in an honest state.

### Design

1. **Guard in `new_run()`.** Add a `replace: bool = False` parameter. If `active_run(project)` returns an id, its `meta.json` exists, and `current_state()` reports status `running`, raise `ActiveRunError(run_id, idea, created_at)` unless `replace` is true. A run whose status is `completed` or `failed` does not block.
2. **CLI.** `start` gains `--new`. On refusal it exits 2 with W1's error helper: "Run 20261103T022957Z-1fbe98 ('B2B comp benchmarking') has been active since 02:29 UTC. Keep using it, or run `start --new` to replace it." The run id still goes to stdout on success, so existing scripts parse it unchanged.
3. **Superseding.** With `--new`, before switching `active.json`, emit a `warning` event on the old run with summary "Superseded by run \<new id>". No new event type is added, so the dashboard and `VALID_EVENTS` need no change. The old run is not marked failed, because nothing failed.
4. **Stale pointers.** If `active.json` names a run whose folder is missing or unreadable, `start` proceeds and prints a one-line notice to stderr. A corrupt pointer must never block work.
5. **Demo.** `demo` creates its run but only sets it active when no run is currently running. Otherwise it prints "Demo run created but not activated; open it from the run picker" so a real run is never displaced by sample data.
6. **Race safety.** The check-then-write happens under an exclusive lock on `.greenfield-observe/.active.lock`, reusing the `fcntl` pattern already in `gf_runs.transact()`. Per Aaron's Windows decision, W26 adds the clear startup error, so no portable lock is needed here.

### Files and functions

- `skill/scripts/gf_observe.py`: `ActiveRunError`, `new_run(..., replace=False)`, lock helper, `start --new`, demo branch.
- `skill/SKILL.md` and `skill/references/observability.md`: one line saying `start` now refuses and agents must never pass `--new` unless the user asked for a fresh run.
- `tests/test_observability.py`: tests below.

### Acceptance criteria

- [ ] Second `start` without `--new` exits 2, leaves `active.json` byte-identical, and creates no new run folder.
- [ ] `start --new` switches the active run and the old run's events end with the "Superseded" warning.
- [ ] `start` after `emit --event run_completed` succeeds without `--new`.
- [ ] `demo` while a real run is running leaves `active.json` unchanged.
- [ ] Two `start` processes launched together produce exactly one new active run.

### Tests

- Refusal, `--new`, completed-run and failed-run cases as unit tests on `new_run()` plus one CLI test through `main()` checking exit code and stderr text.
- Stale pointer: write `active.json` naming a missing run, assert `start` succeeds.
- Concurrency: two `multiprocessing` workers call `new_run()` at once; assert one succeeds and one raises.
- Demo isolation test.

### Edge cases

- A run that is "quiet" (no heartbeat for 5 minutes) still counts as running; quiet is not failure, matching existing semantics.
- A user who genuinely wants parallel evaluations of two ideas: supported via `--new` plus `--run` on later commands; W24's scaffolded `start` revisits this.
- `active.json` with an invalid run id: treated as stale.

### Compared with the best tools

Web validators have no notion of a run; each report is a fresh form. GreenField's resumable runs are an advantage only if they can't be clobbered by an over-eager agent. This follows the CLI-guideline rule of confirming before destructive actions, with `--new` as the explicit override, the same pattern `git` uses for `branch -D`.

## W15. Private by default: permissions and `.gitignore`

Closes Sec L1 and UX4. Verified while speccing under `umask 022`: `.greenfield-observe/` is created `0755`, `active.json` and `meta.json` (which hold the idea text) are `0644`, and only `events.jsonl` is `0600`. Scorer, evidence and portfolio outputs and the experiment ledger also use the default umask. The installer never offers to ignore private folders, even though the repo's own `.gitignore` already lists `.greenfield-observe/` and `research/greenfield/`.

**Goal.** Nothing GreenField writes about an idea is readable by other local users, and a user installing into a git repo is offered, once, the ignore lines that keep private research out of commits.

### Design

1. **One write path.** Every file GreenField writes goes through W1's permissioned atomic write (call it `write_private(path, text)`): create the temp file with `os.open(..., O_CREAT|O_EXCL|O_WRONLY, 0o600)`, write, `fsync`, `os.replace`. Directories are made with `mkdir(mode=0o700)` and, because `mkdir` honours umask and ignores mode on existing folders, followed by `chmod(0o700)` for folders GreenField owns. Appends (`events.jsonl`, ledger, run lock) open with mode `0o600`.
2. **Tighten existing installs.** On `gf_observe.py start` and `serve`, if `.greenfield-observe/` exists with group or other bits set, chmod it to `0700` and its files to `0600`, and print one stderr line saying so. This fixes runs created before the upgrade.
3. **Call sites to switch:**

| File | Writes today | Change |
| --- | --- | --- |
| `gf_observe.py` | `atomic_json` (meta, active), `emit` (already 0600) | `atomic_json` delegates to `write_private`; dirs 0700 |
| `gf_runs.py` | task manifest via `atomic_json`, lock via `open('a+')` | lock opened 0600 |
| `gf_ledger.py` | ledger via `open('a+')` | `os.open(..., 0o600)` then append |
| `score_project.py` | `--output` via `write_text` | `write_private` |
| `gf_evidence.py` | `--output` via `write_text` | `write_private` |
| `gf_portfolio.py` | `--output`, `--markdown` via `write_text` | `write_private` |

4. **`.gitignore` offer in `install.py`.** Only for `--scope project`, and only when `<project>/.git` exists. Compute which of `.greenfield-observe/` and `research/greenfield/` are missing from `<project>/.gitignore` (match with and without leading or trailing slash). Then: on a TTY, ask "Add these to .gitignore so private research stays out of commits? \[Y/n\]"; off a TTY (agents, CI), change nothing and print the exact lines to add. Flags `--gitignore` (add without asking) and `--no-gitignore` (never ask) override. Appended lines go in a marked block, `# greenfield-business-evaluator: private research`, so W25's `uninstall` can find and remove it. Re-running is a no-op.
5. **Runtime nudge.** `gf_observe.py start` checks the same two patterns and, if `.greenfield-observe/` is not ignored in a git repo, prints a one-line hint pointing to `install.py --gitignore`. It never edits `.gitignore` itself.

### Files and functions

- `skill/scripts/gf_common.py` (from W1): `write_private`, `ensure_private_dir`, `tighten_tree`.
- The six scripts in the table above.
- `install.py`: `gitignore_missing()`, `offer_gitignore()`, new flags.
- `tests/test_observability.py`, `tests/test_skill.py`: tests below.

### Acceptance criteria

- [ ] Under `umask 022`, after `start`, `emit`, scorer `--output`, evidence `--output`, portfolio outputs and one ledger record, every created file is `0600` and every created folder `0700`.
- [ ] A `.greenfield-observe/` left at `0755` by an older version is `0700` after the next `start`.
- [ ] Non-TTY install into a git repo never modifies `.gitignore` unless `--gitignore` is passed, and prints the lines to add.
- [ ] Running the install twice with `--gitignore` leaves exactly one marked block.
- [ ] Installs into a folder without `.git`, or with `--scope user`, never touch `.gitignore`.

### Tests

- Permission matrix test using `os.umask(0o022)` in setup and `stat.S_IMODE` assertions, skipped on Windows.
- Tighten test: pre-create a loose tree, run `start`, assert modes.
- `.gitignore` tests with a temp repo (`.git` folder only, no git binary needed): TTY yes, TTY no, non-TTY, `--gitignore` twice, `--no-gitignore`, patterns already present in variant forms.

### Edge cases

- Shared group workflows where someone wants `0640`: out of scope; documented as a limit in W30's SECURITY.md.
- `.gitignore` without a trailing newline: add one before the block.
- `.gitignore` that is a symlink or read-only: print the lines and continue; never fail the install.
- A research folder configured elsewhere: only the two default paths are offered; others are the user's call.
- Network filesystems that ignore chmod: best effort, no error.

### Compared with the best tools

Every web validator asks you to paste your idea into someone else's server; their privacy story is a policy page. GreenField's story is that the idea never leaves your machine. W15 makes that true for other accounts on the same machine and for accidental `git push`, which is a claim none of the hosted tools can make.

## W16. Fetcher: pinned IP, ports 80 and 443, charset fallback

Closes Sec M4. `gf_evidence.py` already blocks private ranges, credentials, proxies and re-checks each redirect hop. Three gaps remain: it resolves the host to vet it and then `urllib` resolves again (a DNS-rebinding host can pass the check and connect internally); any port is allowed (`http://public-host:6379/`); and an unknown `charset` in the response header raises an uncaught `LookupError` that aborts the whole report (confirmed: `b'x'.decode('x-bogus')` raises `LookupError`).

**Goal.** The only address the fetcher ever connects to is one it has vetted, only on web ports, and one odd page can never kill a 40-source report.

### Design

1. **Vet once, connect to what was vetted.** `check_public_url()` returns `(hostname, port, scheme, vetted_ip)` instead of just the hostname. It picks the first global address from `getaddrinfo` (all addresses must still be global, as today). IPv6 literals and bracketed hosts are handled.
2. **Pinned connections.** Replace the `urllib` opener with `http.client`. Add `PinnedHTTPConnection` and `PinnedHTTPSConnection` subclasses whose `connect()` opens `socket.create_connection((vetted_ip, port), timeout)` and, for HTTPS, wraps it with `ssl.create_default_context().wrap_socket(sock, server_hostname=hostname)`. The request's `Host` header is the original hostname (with port when non-default). Certificate verification stays on, so pinning never weakens TLS. No proxy is ever consulted.
3. **Port allowlist.** Allow port 80 for `http` and 443 for `https`, explicit or implied. Anything else fails that claim with "Port 6379 not allowed; only 80 and 443 are fetched". Applied on every redirect hop.
4. **Redirects.** Keep the existing manual loop (at most 4 hops); each hop re-runs the full vet-and-pin, so a redirect to a rebinding host is caught too.
5. **Charset fallback.** Look up the declared charset with `codecs.lookup()`; on `LookupError` decode as utf-8 with `errors="replace"` and record `charset_fallback: true` on that claim's finding.
6. **Per-claim isolation.** In `analyze()`, catch any unexpected exception from one fetch, mark that claim `fetch_status: failed` with "Unexpected error: \<ExceptionType>" and continue. The summary still counts it under `fetch_failures`.
7. **Overall deadline.** Keep the 8-second socket timeout, and add a 20-second wall-clock budget per URL across redirects so a slow-drip server cannot stall the report.
8. **Testability.** `fetch_public(url, *, resolver=None, connector=None)`: `connector` defaults to `socket.create_connection`, so tests can capture the exact address dialled without network access.

### Files and functions

- `skill/scripts/gf_evidence.py`: `check_public_url()` return shape, `PinnedHTTPConnection`, `PinnedHTTPSConnection`, `fetch_public()` rewrite, `decode_body()`, `analyze()` exception isolation. `NoRedirect` and the opener go away.
- `tests/test_v2.py` (evidence tests): new tests below.
- `skill/references/research-protocol.md` and the README limits line: drop the "not an airtight DNS-rebinding defense" caveat for the fetch path, keep the wider "text matching is not truth" caveat.

### Acceptance criteria

- [ ] With a resolver that returns a public IP on the first call and `127.0.0.1` on any later call, the connector is only ever called with the public IP.
- [ ] `http://example.com:6379/` and a redirect to it both fail with the port message; `https://example.com:443/` passes the port check.
- [ ] A response with `charset=x-bogus` produces text, `charset_fallback: true`, and no exception.
- [ ] A fetcher that raises `KeyError` for one claim leaves the others fetched and the report written.
- [ ] TLS hostname verification still fails for a certificate that does not match the original hostname.
- [ ] Still standard library only; no network access in the test suite.

### Tests

- Rebinding test with a stateful fake resolver and a fake connector that records addresses.
- Port tests for explicit, implied and redirected ports.
- Charset test feeding a fake response object with a bogus charset.
- Isolation test with a fetcher that raises on one URL.
- Existing tests for private ranges, IPv4-mapped loopback, `0.0.0.0`, credentials and `.local` must pass unchanged.
- TLS test using a local `ssl` server with a self-signed cert for a different name, marked to run only when loopback sockets are available (the pinned IP is injected, bypassing the public-IP check for that one test via the resolver hook).

### Edge cases

- Hosts that resolve to both public and private addresses: still rejected, as today.
- Hosts with many A records where the first is down: try the next vetted global address, up to three.
- Non-ASCII hostnames: encode with IDNA before resolving and before SNI.
- Servers that send gzip despite no `Accept-Encoding`: treat as unsupported content and report it, rather than decode.
- HTTP to HTTPS redirects on the same host: allowed; HTTPS to HTTP downgrade: allowed but flagged in `issues` as `downgraded_to_http`.

### Compared with the best tools

Hosted validators fetch nothing you can audit; Preuve and DimeADozen link claims, but you take their word that the quote is on the page. GreenField fetches the page itself, hashes it, and checks the quoted passage is there. W16 makes that fetcher safe to point at agent-supplied URLs, which matters because the URLs come from web pages an attacker may control.

## W17. README: fix what is false, nothing more

Closes UX5, UX6 and the UX P2 broken link. Per the plan's conflict resolution, this wave only corrects false statements; the full quickstart rewrite is W28 in Wave 5, after the CLI exists.

**Goal.** Every factual sentence in the current README is true, so nobody is misled in the months before the rewrite.

### The edits

| Line | Says today | Problem | Replace with |
| --- | --- | --- | --- |
| 154 | "All scripts use the standard library and do not make network requests" | `gf_evidence.py --allow-network` fetches URLs (UX5) | "All scripts use the standard library. Only `gf_evidence.py --allow-network` makes network requests, and only to public HTTP(S) pages on ports 80 and 443; everything else runs offline. Live research is done by your coding assistant's own browsing tools." |
| 57 | "From the extracted `greenfield-business-evaluator/` folder" | The shared bundle is `greenfield-business-evaluator-v2/` (UX6); a git clone is `greenfield-business-evaluator/` | "From the repository root (the folder that contains `install.py`):" |
| 162 | `strategyzer.com/library/business-project-succcess` | Three c's; the corrected path did not load when checked on 3 Nov | Link a Strategyzer page that is confirmed to load at implementation time, or drop the line; never ship an unchecked URL |
| 53 | "gitignore it for private ideas" | True but stale after W15 | "`install.py` offers to add it to `.gitignore`; files are private (0600) by default." |

The same "extracted bundle" wording appears in `OBSERVABILITY.md` line 8; fix it the same way so the two docs agree. `install.py`'s docstring ("no network") is accurate for the installer and stays.

**Minimum Python is now 3.11** (Aaron approved this on 3 Nov: 3.10 reached end of life on 1 Oct 2026, and the tests already import `tomllib`). W17 changes every "Python 3.10+" to "Python 3.11+" in one pass: README lines 18 and 55, `OBSERVABILITY.md` line 5, `skill/SKILL.md` line 4 (`compatibility:`), the `skill/references/v2-workflows.md` header, and the docstrings of `install.py` and `gf_observe.py`. The doc-truth test also asserts that "3.10" appears nowhere in the docs or script docstrings. If W22's `pyproject.toml` lands later, its `requires-python` must say `>=3.11`, and that is noted for Wave 4.

### Files

- `README.md`, `OBSERVABILITY.md`.
- `tests/test_skill.py`: a small doc-truth test.

### Acceptance criteria

- [ ] No sentence in README or OBSERVABILITY says scripts never use the network.
- [ ] Following the install section from a fresh `git clone` works without renaming anything.
- [ ] Every URL in the README returned HTTP 200 when checked by hand at merge time (recorded in the PR description).
- [ ] No other README content changes in this wave.

### Tests

- Doc-truth test: assert the README does not contain "do not make network requests" or "succcess", and that every `skill/scripts/*.py` path mentioned in the README exists on disk. Cheap, offline, and catches the most common drift until W28's stronger gate ("every README command runs in a fresh repo") replaces it.

### Edge cases

- Line numbers will drift if anything else edits the README first; match by text, not line.
- If W15 slips out of this wave, leave line 53 as it is rather than describe a feature that has not shipped.

### Compared with the best tools

The hosted tools' docs are marketing pages; their claims (an "89% match rate", page counts) are self-reported. A README that is precisely true about what touches the network is part of the trust pitch, and a cheap test keeps it true.

## Wave gate, dependencies and open questions

**Gate.** The wave ships as one PR when the full suite is green (37 tests today, roughly 40 more after this wave) and the scorer snapshot tests pass for the shipped template and a filled VALIDATE\_BEFORE\_BUILD fixture. Two manual checks go in the PR description: the scorer output on a real terminal, and the README URLs loading.

**What Wave 2 needs from earlier waves.**

- W1 `gf_common.py`: `write_private()` and the shared error helper (W12, W14, W15).
- W7 never-throwing validator: its grouped errors are what the text mode prints on failure (W12).
- W8 portfolio re-scoring: W13 reads recomputed results and shows the mismatch flag; W12 must not rename fields W8 depends on.
- W3 CI: runs the new tests, including the umask permission matrix on Linux.

**What later waves take from Wave 2.**

- W18 Decision panel shows `verdict_label`, `headline`, `next_step` and `source_review_pending` instead of re-deriving them in JavaScript.
- W22 CLI wraps the scorer's `--json` and text modes unchanged; W24's `greenfield score` defaults to the active run that W14 now protects.
- W25 `uninstall` removes the marked `.gitignore` block from W15; `--dry-run` reports whether it would be added.
- W28 README rewrite replaces W17's doc-truth test with the full "commands run as written" gate.
- W29 DECISION.md reuses `bar()` and `VERDICTS` from W12.
- W30 SECURITY.md records W15's permission model and W16's pinned fetching as defended, and same-user access as not defended.

**Decisions.** Aaron approved all five on 3 Nov 2026.

- [x] `next_step` is a new `decision.json` field, not just text output, because the dashboard and DECISION.md both need it.
- [x] `source_review_gate_open` is deprecated in favour of `source_review_pending`, since its current value reads backwards. The old key keeps its current value for one release.
- [x] `demo` stops activating itself while a real run is running.
- [x] The `.gitignore` offer defaults to Yes on a TTY and makes no change off a TTY.
- [x] The broken Strategyzer link is replaced with a page checked at merge time, or dropped if none fits.

**Sources** (checked 3 Nov 2026): [Preuve, Best AI startup idea validation tools 2026](https://preuve.ai/blog/best-startup-validation-tools-2026) (written by a vendor) · [dev.to, I tested 7 free AI startup idea validators](https://dev.to/marketoracle/i-tested-7-free-ai-startup-idea-validators-most-are-useless-3-are-worth-your-time-15fd) (written by a vendor) · [Command Line Interface Guidelines, condensed](https://cdn.jsdelivr.net/npm/@hacxy/skills@0.1.0/skills/create-cli/references/cli-guidelines.md) · [Unified refactor plan](https://claude.ai/artifact/VniiAwzeSr8oS5mQhvFvXs) · [Security review](https://claude.ai/artifact/3aFGtvNf5GvjJBfzR2vPGk) · [UX review](https://claude.ai/artifact/RRWYd2ZABGbPzWzH7Lczu9) · [UI review](https://claude.ai/artifact/1kMZYDa3wuNY9hZfdqFows) · [Mission Control mockup](https://claude.ai/artifact/SEwPzhUYjF2hcydytzQzY8). Code facts were checked against `main` at `def6adb`.
