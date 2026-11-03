# Waves 4 and 5 specs: CLI and docs

Nov 3, 2026 · @Aaron

## Summary

Waves 4 and 5 turn seven separate scripts into one `greenfield` command and then rewrite the docs around it: 9 work items (W22 to W30), about 3 working days, shipped as two PRs. These specs follow the [unified refactor plan](https://claude.ai/artifact/VniiAwzeSr8oS5mQhvFvXs) and Aaron's decisions in it: standard library only, `pyproject.toml` plus `install.py` both kept, Windows fails clearly at startup, all three attestation defenses, one PR per wave. No code was changed.

Analogy: today the tool is a toolbox of seven loose wrenches, each with its own size markings. Wave 4 puts them in one handle with labelled bits (`greenfield score`, `greenfield doctor`). Wave 5 writes the one-page card that ships with it.

The ideas that would most move this toward "best free tool", beyond the plan's wording:

1. **Make the skill folder itself an importable package** (W22). One codebase then serves `pipx`/`uvx`, `install.py`, and agents running `python3 scripts/x.py` inside a repo. No forked copies.
2. **`greenfield doctor` checks what actually breaks research runs**: missing web access, hooks not trusted, stale installed copy, unverified ledger (W23). Competitors only say "if it fails, open an issue".
3. **A worked example gallery and an honest benchmark** in the docs (W28). The strongest free competitor ships five real end-to-end runs and publishes where its skills make no difference. We should match that, then beat it with our verifiable scorer.
4. **A Claude Code plugin marketplace manifest** so install is two slash commands, alongside `pipx` and `install.py` (W25).
5. **DECISION.md generated from `decision.json` by the scorer**, not hand-written by the agent, so the memo can never disagree with the score (W29).

Each spec below has: goal, design, files and functions, acceptance criteria, tests, edge cases, and the competitive comparison. Cross-wave dependencies are at the end.

## Competitive bar

The free competition splits into web validators and agent skill packs, and neither has a deterministic, auditable scorer; our gap is install friction and docs, which is exactly what Waves 4 and 5 fix.

| Category | Example | What it does well | Where it falls short | What we adopt |
| --- | --- | --- | --- | --- |
| Agent skill pack | [emotixco/claude-skills-founder](https://github.com/emotixco/claude-skills-founder) | Two-command plugin install; `examples/` with five unedited end-to-end runs including a "kill" verdict, each listing cost and dead links; `evals/` benchmark against plain Claude that admits where it makes no difference; `/status` reads back saved state | LLM-judged 7-dimension score, no reproducible scorer, no evidence ledger or source checks, no attestation | Plugin marketplace manifest (W25), example gallery and honest benchmark (W28), `greenfield status` (W22) |
| Agent skill pack | Single-file validator skills listed on [claudemarketplaces.com](https://claudemarketplaces.com/skills/ailabs-393/ai-labs-claude-skills/startup-validator) and similar registries | Zero setup | Prompt only; scores are whatever the model says | Nothing new; confirms our scorer is the differentiator |
| Web validator (freemium SaaS) | ValidatorAI, IdeaProof-style tools from [roundups like this](https://preuve.ai/blog/best-startup-validation-tools-2026) (listing only; page blocked from this sandbox) | Instant answer, no install | Opaque scoring, paywalled depth, idea text leaves your machine, no research trail | Lead the README with "local, private, auditable" (W28, W30) |

The CLI bar comes from tools developers already trust: `gh` and `uv` (one binary, grouped subcommands, `--json` everywhere), `brew doctor` and `flutter doctor` (checklist with a fix command per failure), and the [Command Line Interface Guidelines](https://clig.dev) (help with examples, stderr for messages, exit codes, `--dry-run` before anything destructive). Each spec below names the specific behavior it borrows.

## W22: one `greenfield` command and `pyproject.toml`

**Goal.** One entry point, `greenfield <command>`, replaces seven scripts with seven different argument styles, and the same code runs three ways: `pipx install` / `uvx`, an `install.py` copy inside a repo, and an agent calling `python3 <skill>/scripts/greenfield.py`. Closes UX1, UX7, UX8, UX15, UI U11.

### Design

**Package layout.** The `skill/` folder becomes the importable package, so there is one copy of the code and the installed skill and the pip package can never drift apart.

- Add `skill/__init__.py` and `skill/scripts/__init__.py` (empty). Agent Skills hosts ignore them.
- `pyproject.toml` maps the package name onto the folder: `package-dir = {"greenfield_evaluator" = "skill"}`, packages `greenfield_evaluator` and `greenfield_evaluator.scripts`, with `assets/*`, `references/*.md` and `SKILL.md` as package data. Then `gf_observe.py`'s existing `Path(__file__).parent.parent / "assets"` lookup keeps working unchanged inside a wheel.
- The two sibling imports (`gf_runs.py` imports `gf_observe`, `score_project.py` imports `gf_profiles` and `gf_ledger`) become `if __package__: from .gf_observe import ...` else the current absolute import. That one pattern is what lets a file work both as a script and as a package module.
- Build backend `setuptools>=69` (build time only). Runtime dependencies: none. `requires-python = ">=3.11"`. Console script `greenfield = "greenfield_evaluator.scripts.cli:main"`.
- Version lives once in `skill/scripts/_version.py` (`__version__ = "2.1.0"` for this wave; W2 sets 2.0.0) and pyproject reads it with `dynamic = ["version"]`.

This makes `uvx --from git+https://github.com/aarongbaker/greenfield-business-evaluator greenfield doctor` work today without publishing to PyPI. Publishing is an open question at the end.

**Command map.** Grouped like `gh`: nouns for things you manage, verbs for one-shot actions. Hidden commands are for hooks and stay out of `--help`.

| New command | Replaces | Notes |
| --- | --- | --- |
| `greenfield install` / `uninstall` | `install.py` | W25 adds `--dry-run` and uninstall |
| `greenfield hooks install` / `remove` | `configure_hooks.py` | W10 platform flag carried over |
| `greenfield start` | `gf_observe.py start` | W14 active-run guard, W24 scaffolding |
| `greenfield status` | `gf_observe.py status`, `gf_runs.py status` | One view: run, tasks, decision if scored |
| `greenfield task plan` / `claim` / `complete` / `fail` / `resume` / `coverage` / `set-rate` | `gf_runs.py` | `--role` gets `choices=` from W4's `ROLES` |
| `greenfield dashboard` | `gf_observe.py serve` | `--port`, `--open` launches the browser |
| `greenfield demo` | `gf_observe.py demo` | Unchanged |
| `greenfield event emit` | `gf_observe.py emit` | For agents reporting milestones |
| `greenfield hook`, `greenfield ingest-codex` | same in `gf_observe.py` | Hidden; called by hooks and pipes |
| `greenfield sources check` | `gf_evidence.py` | `--allow-network` stays explicit |
| `greenfield ledger record` / `verify` / `summary` | `gf_ledger.py` | W27's hook blocks agent `record --attester` |
| `greenfield score` | `score_project.py` | W12 text/JSON, W24 active-run default |
| `greenfield portfolio` | `gf_portfolio.py` | Unchanged flags |
| `greenfield doctor`, `greenfield profiles` | new | W23 |
| `greenfield completion bash\|zsh\|fish` | new | Static scripts generated from the parser tree |

**Module shape.** Each existing module gains `register(subparsers)` (adds its parsers) and handler functions that return a plain dict and never print. `cli.py` owns parsing, rendering, errors and exit codes. Each module's old `main(argv)` stays, now a thin wrapper that calls the same handlers, so old commands produce identical output.

**Global options** work before or after the subcommand: `--project DIR`, `--json`, `--quiet`, `--no-color`, `--version`. Implemented as one parent parser attached to the root and every subparser with `default=argparse.SUPPRESS`, so `greenfield --json score` and `greenfield score --json` both work. That is the most common argparse complaint and `gh` behaves this way.

**Output contract.**

- Text on a TTY, JSON when piped or with `--json` (the W12 rule, applied everywhere). With `--json`, stdout holds exactly the data object the old script printed, so existing agent parsing keeps working.
- Messages, progress and deprecation hints go to stderr only. Color only on a TTY and never when `NO_COLOR` is set.
- Errors use W1's helper: what failed, the path, the next command. With `--json` the error is `{"error": {"code", "message", "path", "next"}}` on stderr.
- Exit codes: 0 success, 1 a negative result the user asked about (ledger chain broken, doctor found failures), 2 bad input or usage, 3 environment problem (unsupported OS, skill not installed), 130 on Ctrl-C with no traceback.

**Help.** Every argument has `help=`; every closed set uses `choices=` (roles, providers, profiles, ledger kinds, platforms); every command has an epilog with two copy-pasteable examples. An unknown command prints the closest match from `difflib.get_close_matches` ("Did you mean `score`?"), since argparse only gained suggestions in Python 3.14.

**Deprecation.** Running an old script directly prints one stderr line, for example `note: score_project.py is now 'greenfield score'; this script keeps working until 3.0`. `GREENFIELD_NO_DEPRECATION=1` silences it. Removal is a breaking change, so it waits for 3.0, not the next minor.

### Files and functions

- New: `pyproject.toml`, `skill/__init__.py`, `skill/scripts/__init__.py`, `skill/scripts/_version.py`, `skill/scripts/cli.py` (`build_parser()`, `main(argv)`, `render(result, args)`, `fail(err, args)`, `suggest(name)`), `skill/scripts/greenfield.py` (three-line shim calling `cli.main`), `skill/scripts/completion.py`.
- Changed: every script in `skill/scripts/` gets `register()` and dict-returning handlers; `install.py` and `configure_hooks.py` logic moves into `skill/scripts/gf_install.py` and `gf_hooks.py`, and the root files become shims so the no-dependency path still works.

### Acceptance criteria

- `pipx install .` and `uvx --from . greenfield --version` both print `greenfield 2.1.0` on Python 3.11 and 3.13.
- Every old command in the current README still runs with identical stdout, plus one stderr hint.
- `greenfield <cmd> --help` exits 0 for every command and shows at least one example.
- `greenfield --json <cmd>` output parses as JSON for every non-serving command; `dashboard --json` prints one `{"url": ...}` line and keeps serving.
- The built wheel contains `assets/mission-control.html`, both templates and all references.

### Tests (`tests/test_cli.py`)

- Parametrized over the command table: help works, has an example, `--json` parses.
- Global flags in both positions give identical output.
- Old script vs new command: same stdout on the template and a filled fixture; hint only on stderr.
- Typo suggestion, each exit code, Ctrl-C (send SIGINT to a `dashboard` subprocess, expect 130 and no traceback), and `greenfield score ... | head -1` raising no `BrokenPipeError`.
- CI (W3) builds the wheel, installs it into a clean venv, runs `greenfield doctor --json`, and checks the wheel contents with `zipfile`.

### Edge cases

- Another `greenfield` binary earlier on `PATH`: doctor reports which one runs.
- pipx copy and in-repo skill copy at different versions: doctor warns; the in-repo copy wins when an agent calls it by path.
- Python 3.11 is the minimum (Wave 0 decision), so `tomllib` is available, but nothing at runtime needs TOML; \`pyproject.toml\` is build-time only.
- `--project` pointing at a file or a missing folder: exit 2 with the path, never a traceback.

### Compared with the best

`gh` and `uv` set the bar: grouped nouns, `--json` on everything, examples in help. Skill-pack competitors have no CLI at all, so a person can't check, score or rank ideas without an agent. Ours keeps every result reproducible from the terminal, which is the point of a deterministic scorer.

## W23: `greenfield doctor` and `greenfield profiles`

**Goal.** One command tells a user why a run will not work and the exact command that fixes it, and a second shows the six business-model profiles so users and agents pick the right one. Closes UX11.

### Design: doctor

Each check returns `{id, group, status: pass|warn|fail|info, detail, fix}`. `fix` is always a runnable command or a single sentence, never "see docs". Checks run in this order and each group is skipped with a reason if an earlier failure makes it meaningless.

| Group | Check | Fails or warns when | Fix shown |
| --- | --- | --- | --- |
| Environment | Python version | Below 3.11 | Install 3.11+ |
| Environment | Platform | Windows, or `fcntl` missing (W26) | Use WSL; plain text, exit 3 for locking commands |
| Environment | Which `greenfield` | Another binary shadows it, or pipx and repo copies differ in version | `pipx upgrade` or `greenfield install --force` |
| Install | Skill present | Neither `.claude/skills/...` nor `.agents/skills/...` exists at project or user scope | `greenfield install --platform both` |
| Install | Installed copy intact | File hashes differ from the install manifest W25 writes | `greenfield install --force` |
| Install | Shadowing | Same skill at user and project scope with different versions | Which one each host loads, and how to remove the other |
| Install | Agent roles | Any of the 9 `gf-*` files missing, or older than the package (W27 freshness) | `greenfield install --force` |
| Hooks | Configured | No Greenfield entries in `.claude/settings.local.json` or `.codex/hooks.json` (info only, hooks are optional) | `greenfield hooks install` |
| Hooks | Script path valid | A hook command points at a script that no longer exists (the README's "confirm they point to the same skill location" warning, now checked) | `greenfield hooks install` |
| Hooks | Self-attestation guard | W27 PreToolUse rule missing | `greenfield hooks install` |
| Hooks | Codex trust | Cannot be read from disk | Info: open `/hooks` in Codex |
| Privacy | Folder permissions | `.greenfield-observe/` not 0700 or files not 0600 (W15) | `greenfield doctor --fix` |
| Privacy | Ignored by git | `.greenfield-observe/` or `research/greenfield/` not ignored, or already tracked per `git ls-files` | `greenfield doctor --fix`; tracked files get `git rm --cached` shown, never run |
| Attestation | HMAC key | `~/.config/greenfield/` key missing or not 0600 (W11) | Created on first `ledger record`; `chmod 600` |
| Run | Active run | `active.json` points at a missing or malformed run | `greenfield start --new` |
| Run | Evaluation readiness | W7 validator errors on the active `evaluation.json`, listed as "what is missing before you can score" | Per error |
| Run | Ledger chain | `ledger verify` fails on the ledger the evaluation references | Shows the first broken event |
| Dashboard | Port | 8765 in use | `greenfield dashboard --port 8766` |
| Network | Reachability | Only with `--network`: HTTPS to one public host fails | Proxy or offline note; the tool never touches the network by default |
| Agent | Web access | Cannot be detected from a CLI | Info: enable browsing in the host before research |

**Output.** On a TTY, a grouped checklist (pass, warn, fail markers plus words, so it works without color), then a one-line summary such as "2 problems, 1 warning. Run the fix commands above." With `--json`, the list of check objects plus `summary`. Exit 0 with only passes and warnings, 1 with any failure, 3 when the platform is unsupported.

**`--fix`** applies only safe, local, idempotent repairs: permissions and `.gitignore` lines. It asks first on a TTY and lists what it changed. Anything else (reinstalling, removing tracked files) is printed, never run.

Doctor itself, `--help` and `--version` run on Windows so the platform check can explain itself; that is the one exception to W26's startup refusal.

### Design: profiles

- `greenfield profiles` prints the six profiles as a table: name, one-line "use when", the three heaviest weights, and the number of pilot gates.
- `greenfield profiles show <name>` prints all eight weights, each pilot gate with a plain description and what evidence satisfies it, and the profile's guiding questions.
- `greenfield profiles compare <a> <b>` prints weight differences side by side. Useful when a founder can't decide between bootstrapped SaaS and venture.
- Gates today are bare ids such as `delivery_margin`. Add a `GATE_HELP` dict in `gf_profiles.py` with a description and an example evidence id for each of the 17 gates, and a `USE_WHEN` line per profile. A test fails if any gate lacks help.

### Files and functions

- New `skill/scripts/gf_doctor.py`: `CHECKS` list, `run_checks(project, network=False) -> list[dict]`, `apply_fixes(results)`, `register()`.
- `gf_profiles.py`: `GATE_HELP`, `USE_WHEN`, `describe(name)`, `compare(a, b)`, `register()`.
- Reuses `gf_ledger.verify`, W7's `validate()`, W25's manifest reader and W27's freshness check rather than re-implementing them.

### Acceptance criteria

- Empty temp project: doctor exits 1, and every failure's `fix` command, run in order, gets it to exit 0.
- Each check can be forced to fail by a fixture, and its `fix` text is not empty.
- Doctor finishes in under 2 seconds without `--network` and never opens a socket in that mode (asserted by patching `socket.socket`).
- `profiles show` covers all 6 profiles and 17 gates; JSON output round-trips through `gf_profiles.PROFILES`.

### Tests

One fixture per row of the table (`tests/test_doctor.py`), the full repair loop above, `--fix` idempotence (second run changes nothing), the no-socket assertion, and the Windows path via `unittest.mock.patch` of `sys.platform` and a stubbed missing `fcntl`.

### Edge cases

Project is not a git repo (skip the tracked-files check, still check ignore rules); a read-only filesystem for `--fix` (report, do not crash); a user-scope-only install (project checks become info); a huge ledger (verify streams, no full load).

### Compared with the best

`brew doctor` and `flutter doctor` are the model: grouped checks, one fix per failure. The leading skill pack says outright that a broken install fails silently and asks users to open an issue. Doctor turns that into a self-serve fix, and it checks things no competitor can, like a broken evidence chain or an untrusted hook.

## W24: `greenfield start` scaffolds the run; later commands find it

**Goal.** Starting an evaluation goes from three commands plus a hand-copied template with a stale `2026-10-23` date to one command, and every later command finds the files on its own. Closes the UX P2 stale-dates and placeholder findings.

### Design

`greenfield start --idea "..." [--slug S] [--model PROFILE] [--customer TEXT] [--geography TEXT] [--depth quick|standard|deep] [--provider claude|codex|both] [--as-of YYYY-MM-DD] [--no-plan] [--new]` does, in order:

1. **Active-run guard (W14).** Refuses if a run is active, naming it and offering `--new` (start another) or `greenfield status` (see the current one).
2. **Slug.** From `--slug` or the idea: NFKD-normalize, ASCII only, lowercase, non-alphanumerics to `-`, collapse repeats, cut at 48 characters on a word boundary. If that leaves nothing (an idea written in Japanese, say), use `idea-YYYYMMDD`. Must match `[a-z0-9][a-z0-9-]{0,47}`.
3. **Folder.** Create `research/greenfield/<slug>/` and `specialists/` inside it, through W6's `resolve_inside()`. If `evaluation.json` already exists there, stop and suggest `--slug` or `greenfield status`. Never overwrite.
4. **Evaluation file.** Copy the template and fill: `as_of` = today in local time (or `--as-of`), `project.name` and `project.idea`, `business_model` from `--model` (`choices=` from `gf_profiles`), optional customer and geography, `execution.mode` = `"not_started"`, and the relative paths `evidence_ledger: "experiment-ledger.jsonl"` and `verification_report: "source-verification.json"`. Written with W1's permissioned atomic write.
5. **Run record.** Create the run in `.greenfield-observe/` and store `research_dir` (relative to the project) in its `meta.json`, so the dashboard (W18) and every command can find the research folder from the run.
6. **Task plan.** Run `task plan` unless `--no-plan`.
7. **Next steps.** Print the exact invocation to paste into Claude Code and Codex for this idea, plus `greenfield dashboard`. With `--json`: `{run_id, slug, research_dir, evaluation, next}`.

**Run context.** One helper, `run_context(project, run=None)`, returns `{run_id, research_dir, evaluation, decision, ledger, verification}` from `--run` or the active run. Commands use it for their defaults:

| Command | With no path given | With an explicit path (old behavior kept) |
| --- | --- | --- |
| `greenfield score` | Reads the run's `evaluation.json`, writes `decision.json` beside it, prints the W12 text summary | Unchanged: stdout unless `--output` |
| `greenfield sources check` | Reads the run's evaluation, writes `source-verification.json` beside it | Unchanged |
| `greenfield ledger ...` | `--ledger` defaults to the run's `experiment-ledger.jsonl` | Unchanged |
| `greenfield status` | Adds research folder, scored or not, and the verdict if scored | n/a |

With no active run and no path, each command exits 2 with "No active run. Start one with `greenfield start --idea ...`, or pass a path."

**Template.** `evaluation-template.json` drops its hardcoded date: `as_of` becomes `""`, which the scorer reads as "not started" (RESEARCH\_INCOMPLETE plus a warning naming the field), so the existing `test_template_requires_research` keeps passing. Any `REPLACE_` string left in a project field gets the same treatment. That is the evaluation-side twin of W13's portfolio placeholder check.

### Files and functions

- `gf_observe.py`: `new_run(..., research_dir=None)`, `slugify(idea)`, `scaffold(project, args)`.
- New `skill/scripts/gf_context.py`: `run_context()`, used by `score_project.py`, `gf_evidence.py`, `gf_ledger.py`, `gf_runs.py`.
- `skill/assets/evaluation-template.json`: `as_of` emptied.
- `score_project.py` (`validate()` from W7): empty `as_of` and `REPLACE_` placeholders become incomplete-with-warning, not exit 2.

### Acceptance criteria

- In an empty git repo, `greenfield start --idea "AI bookkeeping for dentists" --model services` then `greenfield score` prints RESEARCH\_INCOMPLETE and writes `research/greenfield/ai-bookkeeping-for-dentists/decision.json`.
- The scaffolded `as_of` equals today; no template or test fixture still hardcodes `2026-10-23`.
- A second `start` without `--new` exits 2 and changes no files.
- `start` never overwrites an existing `evaluation.json` (checked by hash before and after).

### Tests

Slug table (ASCII, punctuation, 200-character idea, emoji, Japanese, an idea that is only stopwords); date injection via `--as-of` so tests don't depend on the clock; collision and no-overwrite; each defaulted command with and without an active run; the run's `research_dir` rejected if it escapes the project (W6 symlink fixture).

### Edge cases

Midnight across time zones (use local date and say so in help); `research/` is a symlink outside the project (refused by W6); two `start` calls racing (the run record write is atomic and the guard rechecks under W14's lock); a user who renames the folder afterwards (`status` reports the missing path and suggests `--run` or re-linking).

### Compared with the best

The leading skill pack saves every output to a `founder/` folder and has `/status` read it back, which users like. We match that with one research folder per idea and add what it lacks: a dated, validated machine file the scorer reads, so the folder doubles as a reproducible audit trail.

## W25: `install --dry-run`, `uninstall`, and a plugin install

**Goal.** Users can see exactly what install will touch before it touches it, remove everything it added in one command, and upgrade without losing their own edits. Closes UX14. Adds a Claude Code plugin install as the easiest path.

### Design

**Plan, then apply.** `plan_install(args)` returns a list of actions `{op: create|replace|skip|remove, path, reason}`. `--dry-run` prints that list and exits 0 without writing. A real install runs the very same list, so the dry run can't drift from what happens. With `--json` the plan is the output.

**Install manifest.** Each install writes `<skill dir>/.greenfield-install.json`: package version, platform, scope, install time, and every file it placed (including the 9 agent files outside the skill folder) with its sha256. Three things read it:

- `uninstall` removes only listed files whose hash still matches.
- `install --force` (upgrade) refuses to replace an agent file the user edited, names it, and needs `--force --overwrite-modified` to proceed.
- `doctor` (W23) reports a stale or locally edited installed copy.

**Safe replace.** Today `install_skill()` deletes the old folder and then copies, so a crash in between leaves nothing. Instead copy into a sibling staging folder, swap with two renames, then delete the old one. On any error the old install stays as it was. W2's `ignore_patterns` keeps `__pycache__` out.

**Uninstall.** `greenfield uninstall [--platform] [--scope] [--project] [--dry-run] [--yes] [--keep-hooks] [--purge-telemetry]`:

1. Builds a removal plan from the manifest. For a v2.0 install with no manifest, it falls back to the known paths (the skill folder and the 9 `gf-*` names) and compares each against the package's own copy; files that differ are kept and listed.
2. Removes Greenfield hooks by default through `gf_hooks.remove`, leaving every other hook in place. A hook pointing at a deleted script would error on every tool call, so leaving it is the worse default. `--keep-hooks` opts out.
3. Never touches `research/greenfield/` (the user's work). `--purge-telemetry` also deletes `.greenfield-observe/`, after confirmation. `.gitignore` lines stay; the summary says so.
4. On a TTY it shows the plan and asks y/N; without a TTY it needs `--yes` (clig.dev's rule for destructive commands).
5. A second run finds nothing to do and exits 0.

**Plugin install (recommended addition).** Add `.claude-plugin/marketplace.json` and `.claude-plugin/plugin.json` so Claude Code users can run `/plugin marketplace add aarongbaker/greenfield-business-evaluator` then `/plugin install greenfield-business-evaluator@greenfield`. The plugin ships the skill and the 9 Claude agents, with no hooks, so hooks stay opt-in. If the current plugin format can't point at `skill/` and `platform/claude/agents/` in place, `make_agents.py` (W27) generates a `plugin/` folder and the freshness test covers it. Check the manifest fields against the current Claude Code plugin docs when building this; I did not verify them here.

### Files and functions

- `skill/scripts/gf_install.py` (moved from `install.py` in W22): `plan_install()`, `apply(plan)`, `write_manifest()`, `read_manifest()`, `plan_uninstall()`, `stage_and_swap()`.
- `install.py` stays a shim, gains `--dry-run` and an `uninstall` subcommand, still standard library only.
- New `.claude-plugin/marketplace.json`, `.claude-plugin/plugin.json`.

### Acceptance criteria

- `--dry-run` leaves the target tree byte-identical (hash every file before and after) and its plan equals the actions a real run then reports.
- Install then uninstall returns the project to its prior tree, except `.gitignore` lines and user research.
- An edited `gf-market.md` survives `uninstall` and blocks `install --force` with its name shown.
- An exception injected midway through the copy leaves the previous install working.
- Other skills, non-`gf` agents and unrelated hooks are never touched, at project or user scope.

### Tests

Tree-snapshot helper for the dry-run and round-trip cases; legacy (no manifest) uninstall; modified-file keep; hook removal preserving a third-party hook; idempotent second uninstall; user scope with `HOME` patched to a temp dir; injected `OSError` during `copytree`; JSON schema of the plan; a CI job that validates the plugin manifests parse and point at existing files.

### Edge cases

Symlinked `.claude/` (resolve and confirm it stays inside the target, via W6); a read-only file in the skill folder (report and continue, exit 1); both scopes installed (uninstall needs `--scope`, or `--scope all`); manifest present but corrupted (fall back to legacy mode with a warning).

### Compared with the best

The leading skill pack installs with two slash commands but has no dry run, no uninstall and no protection for edited files; its upgrade notes ask users to delete old folders by hand or see every skill twice. We match its two-command install and add the safety that package managers like Homebrew and pipx have.

## W26: Windows fails clearly at startup

**Goal.** On native Windows, a command that needs file locking stops at startup with a plain message and a WSL link instead of a traceback, per Aaron's decision (no portable locking). Closes UX13.

**A finding that shapes this.** Today the crash is wider than the locking commands. `score_project.py` imports `gf_ledger`, which imports `fcntl` at module top, so even scoring (which never locks) dies with `ModuleNotFoundError` on Windows. `gf_runs.py` has the same top-level import.

### Design

- New `skill/scripts/gf_platform.py` with `HAS_FCNTL` and `require_locking(command)`. It raises W1's error type with: "`greenfield task` needs POSIX file locking, which native Windows does not have. Run it inside WSL (https://learn.microsoft.com/windows/wsl/install). Read-only commands such as score, ledger verify, portfolio and doctor work here." Exit 3, JSON code `unsupported_platform`.
- Move `import fcntl` in `gf_ledger.py` and `gf_runs.py` inside the lock functions, behind `require_locking()`. Importing either module no longer fails on Windows.
- `cli.py` declares which commands need locking: `start`, `task *`, `ledger record`, `event emit`, `hook`, `ingest-codex`, `demo`. The check runs before argument handling, so nothing is half-written. Every other command runs normally.
- `install` on Windows prints a one-line warning that research runs need WSL, then installs (the skill text itself is still useful to the agent).
- `pyproject.toml` classifiers list POSIX and macOS only. The README limits section (W28) says the same in one line.

**Decided (Aaron, 3 Nov): per command.** Refusing per command rather than the whole CLI means scoring, verifying a ledger and ranking a portfolio all work on Windows at no extra cost.

### Acceptance criteria

- With `fcntl` made unimportable, every locking command exits 3 with the message on stderr and writes no files; no traceback anywhere.
- With `fcntl` unimportable, `greenfield score <fixture>` gives the same decision as on Linux.
- Cygwin and MSYS2 (which have `fcntl`) and WSL are treated as supported.

### Tests

Run subprocesses with `-c "import sys; sys.modules['fcntl'] = None; ..."` to simulate Windows on Linux CI. Parametrize over the locking-command list (exit 3, empty tree diff) and the read-only list (exit 0). Optionally add a `windows-latest` job to W3's CI that runs only these two test classes, which proves the real thing.

### Edge cases

The scorer's ledger *verification* reads without locking, so it stays allowed. A future command that adds locking must be added to the list; a test greps for `fcntl` usage outside `gf_platform.py` and fails if one appears.

### Compared with the best

Most Python CLIs that depend on `fcntl` simply crash on Windows. Clear refusal plus a working read-only subset is better than any skill pack offers, and it avoids the maintenance cost of portable locking, which Aaron chose not to take on.

## W27: generator to `tools/`, agents on the new CLI, self-attestation guard

**Goal.** Generated agent files can never silently drift from their source, the skill tells agents to use the new CLI, and the host itself stops an agent from recording a human attestation. Closes the UX P2 dev-script finding and the hook part of Sec H2 (Aaron chose all three attestation defenses).

### Part A: `tools/make_agents.py` with a freshness check

- `git mv make_agents.py tools/make_agents.py`. It reads roles from W4's `ROLES` table instead of its own dict, and emits W5's read-only settings (`tools:` frontmatter for Claude, `sandbox_mode = "read-only"` for Codex).
- Output is deterministic: sorted roles, fixed key order, LF endings, trailing newline, no timestamps.
- New `--check` mode generates in memory and compares with disk. It exits 1 listing stale files, like `black --check`. If W25 needs a generated `plugin/` folder, the generator writes it too and `--check` covers it.
- The agents' shared text drops the hardcoded `.claude/skills/...` and `.agents/skills/...` paths in favor of "the skill's `references/agent-briefs.md`", which hosts resolve. Research agents get no CLI commands at all: after W5 they have no Bash, so only the orchestrator runs the CLI.

### Part B: SKILL.md and references use the CLI

- Every `python3 scripts/<x>.py` line in `SKILL.md`, `references/v2-workflows.md`, `references/observability.md` and `references/outputs.md` becomes `python3 <skill dir>/scripts/greenfield.py <command> --json`. That form works in every install mode; `greenfield` on PATH is mentioned as a shortcut, not relied on. `--json` is always explicit, per the W12 conflict resolution.
- The run checklist in SKILL.md shrinks: `start` now plans tasks (W24), and `score` finds the evaluation by itself.
- SKILL.md gains a short "attestation is human-only" rule pointing at Part C, so the agent explains the block instead of retrying.

### Part C: PreToolUse self-attestation guard

**What it blocks.** An agent's tool call that would record or forge a human attestation:

- Bash commands that run a ledger `record` with `--attester`, in any spelling: old `gf_ledger.py record`, `greenfield ledger record`, `scripts/greenfield.py ledger record`, `python3 -m greenfield_evaluator ...`, `--attester=X`, behind `cd ... &&`, `;`, env-var prefixes, or `bash -c '...'`.
- Write, Edit, MultiEdit and NotebookEdit targeting a ledger file (`experiment-ledger.jsonl` or any path the active evaluation names) or anything under `~/.config/greenfield/` (W11's HMAC key), and Bash commands that reference that folder.

**How.** `greenfield hook guard --provider claude|codex` reads the hook JSON from stdin and calls `gf_guard.decide(tool_name, tool_input)`. It splits commands with `shlex` on shell separators and recurses into `bash -c` / `sh -c`. On deny it returns the host's deny response with a reason that gives the human the exact command to run in their own terminal. It allows everything else, including `ledger verify` and `ledger summary`. It fails closed only when a command mentions the ledger and can't be parsed; otherwise it fails open, like the observability hook.

**Install.** `greenfield hooks install` adds the guard alongside the observability hooks. `--guard-only` installs just the guard, which is what doctor (W23) recommends to anyone who skips observability. The guard has its own marker (`gf_guard`), so `hooks remove` and W25's uninstall take it out cleanly without touching other hooks.

**Honest limit.** This is defense in depth, not the lock itself. The real enforcement is W11: TTY-only confirmation (agent shells have no TTY) and HMAC-signed events. A determined agent could find a spelling the parser misses; it still can't produce a valid signature. SECURITY.md (W30) says this plainly. Confirm Codex's PreToolUse deny format against current Codex hook docs when building; the existing installer already registers Codex PreToolUse hooks, so the event exists.

### Files and functions

- `tools/make_agents.py` (`generate() -> dict[path, text]`, `--check`), 18 regenerated agent files.
- New `skill/scripts/gf_guard.py`: `decide()`, `split_commands()`, `is_attestation(argv)`, `protected_paths(project)`.
- `gf_hooks.py` (from `configure_hooks.py`): guard entries, `--guard-only`, marker-aware remove.
- `SKILL.md` and the four references listed above.

### Acceptance criteria

- `python3 tools/make_agents.py --check` exits 0 on main and 1 after any hand edit to a generated file; CI runs it.
- No `python3 scripts/` command remains in SKILL.md or references, and every CLI line in them parses with `cli.build_parser()` (placeholders substituted). This test is reused by W28 for the README.
- With the guard installed, every deny case in the test table is blocked with the human-run command in the reason; every allow case passes.
- Installing and removing the guard leaves unrelated hooks byte-identical.

### Tests

`tests/test_guard.py` holds a table of at least 25 commands: deny cases in every spelling above, and allow cases such as `greenfield ledger verify`, `greenfield ledger record --kind hypothesis` (no attester), `grep attester notes.md`, and an unrelated `--attester` flag on another tool. Add Write/Edit payload fixtures for both hosts, the fail-closed parse case, and the freshness test as a unit test so it runs without CI.

### Edge cases

A quoted string that merely mentions the command, like `echo "greenfield ledger record --attester"`, is denied: a harmless false positive, and the reason explains it. Ledger paths are resolved through W6 so `../` tricks still match. A user who truly wants an agent to record on their behalf is told to run it themselves; there is deliberately no override flag the agent could pass.

### Compared with the best

Competing skill packs rely on the prompt alone ("customer quotes are never invented"). Here the host refuses the action and the ledger can prove tampering. As far as I found, no free competitor enforces evidence integrity this way, and it's the core of the "auditable" claim in W28.

## W28: README as a 5-minute quickstart, deep dives in `docs/`

**Goal.** A newcomer goes from landing on the repo to a first verdict in five minutes, and every command they copy works. Today's README is 184 lines that open with "v2 Complete", a verification date and a five-row capability table before any command. Closes UX2, UX12, UX P2 tone, UI U18.

### README outline (target 120 to 150 lines)

1. **One sentence** of what it is: research a business idea with AI agents before you build it, and get a verdict you can audit. Badges: CI, MIT, Python 3.11+.
2. **Screenshot** of Mission Control (W18 to W21 final), captured by `tools/screenshot.py` with Playwright from `greenfield demo`. The DEMO label stays visible in the image, so the picture is honest. Below it, a 10-line sample of the W12 text verdict.
3. **Why this one**, three bullets: a deterministic scorer (same inputs, same verdict), an evidence trail with tamper-evident ledger and source checks, and everything local (no account, no telemetry, ideas never leave your machine).
4. **Quickstart**, at most six commands: install (three tabs: Claude Code plugin, `pipx`/`uvx`, `install.py`), `greenfield doctor`, `greenfield start --idea "..."`, the one-line agent invocation, `greenfield score`, `greenfield dashboard`.
5. **What you get**: the research folder tree, with DECISION.md first.
6. **How the verdict works**, five lines with the five labels in plain words and a link to `docs/how-scoring-works.md`. Analogy for readers: quality is how good the house looks in the listing, evidence is whether you've had it inspected.
7. **Limits**, one section, five bullets: heuristic not predictive; needs the host's web browsing; human attestations can still be dishonest; macOS, Linux and WSL only; agents must be allowed to run research.
8. **Learn more** links to `docs/`, examples, CHANGELOG, SECURITY.md.

Tone rules: second person, plain verbs, no all-caps warnings, one product name ("Greenfield Business Evaluator", then "Greenfield"), no version number in headings.

### `docs/` layout

| File | Content | Source |
| --- | --- | --- |
| `docs/install.md` | Every install path and scope, upgrade, dry run, uninstall, hooks | README install and upgrade sections, W25 |
| `docs/cli.md` | Every command with flags and examples | Generated from `cli.build_parser()` by `tools/gen_cli_docs.py`, with a `--check` freshness test |
| `docs/how-scoring-works.md` | Pillars, quality vs evidence, profiles, gates, verdicts, worked example | Human rewrite of `references/scoring.md` and `pillars.md` |
| `docs/mission-control.md` | Dashboard setup, hooks, Codex JSONL, privacy | `OBSERVABILITY.md` (root file becomes a one-line pointer for a release) |
| `docs/evidence.md` | Source checks, ledger, attestation, what a human must do | `references/v2-workflows.md`, W11 |
| `docs/portfolio.md` | Comparing several ideas | `gf_portfolio.py` docstring and template |
| `docs/troubleshooting.md` | Each doctor check, its meaning and fix | Generated from `gf_doctor.CHECKS` |

`skill/references/` stays for agents only: each file gets a first line saying so and linking its human twin in `docs/`. `RELEASE_NOTES.md` folds into W2's `CHANGELOG.md`.

### Recommended addition: examples and an honest benchmark

The strongest free competitor's best selling point is `examples/` (five unedited real runs, one told to kill the idea, each with cost and dead-link count) and `evals/` (a benchmark against plain Claude that admits where it makes no difference). We should do the same and go further:

- `examples/<slug>/` with three real runs, at least one NO\_GO or PIVOT, every file unedited, plus run cost, wall time, host and model, and dead links found by `sources check`. These must be genuine runs with web access; they can't be generated in a sandbox, and making them up would break the tool's whole premise.
- `evals/` comparing the skill against the same agent with no skill on five fixed ideas. Rubric: unsourced numbers, share of claims with working primary sources, verdict stability across three runs, and fabricated customer evidence. Publish losses too.
- One thing no competitor can show: rerunning `greenfield score` on any example's `evaluation.json` reproduces its `decision.json` exactly. A test enforces it.

### Acceptance criteria (the wave gate)

- `tests/test_docs.py` extracts every shell block from README and `docs/` and runs it in a fresh temp git repo with network blocked. Lines marked `# needs-agent` or `# needs-network` are parse-checked with `cli.build_parser()` instead of run. Any failure fails CI.
- Every relative link and anchor resolves (offline check). External links get a weekly scheduled CI job that opens an issue rather than failing PRs.
- README is at most 150 lines, and the quickstart reaches a RESEARCH\_INCOMPLETE verdict on a fresh repo in at most six commands.
- `docs/cli.md` and `docs/troubleshooting.md` pass their `--check` freshness tests.
- One person who has never seen the repo follows the README on a clean machine and reaches the dashboard in under five minutes; note what tripped them.

### Edge cases

Platform-specific commands (`open` vs `xdg-open`) are avoided, with `greenfield dashboard --open` instead. The screenshot is regenerated whenever the dashboard HTML changes, enforced by a hash check in `tools/screenshot.py --check`. Python version in commands is `python3` throughout.

### Compared with the best

The best free skill pack wins on proof (examples, evals) and a short install. With this wave we match both, and add reproducible verdicts and an evidence trail, which no free tool offers. The README should lead with exactly that difference.

## W29: DECISION.md with a verdict callout and a scorecard the scorer writes

**Goal.** The first screen of DECISION.md tells a reader the verdict, why, and how strong the evidence is, at a glance, and it can never disagree with `decision.json`. Closes UI U17.

### Design

**Generated block plus agent narrative.** Today the agent hand-writes the whole memo from the template in `references/outputs.md`, so the memo's verdict and scores can drift from the scorer's. Instead, a new `greenfield report` renders the factual top of the memo from `decision.json` and `evaluation.json` between two markers, and the agent writes the narrative sections below. Rerunning `report` replaces only what's between the markers.

```markdown
<!-- greenfield:generated v1 — do not edit; run `greenfield report` -->
# AI bookkeeping for dentists: investment memo

As of 2026-11-03 · Profile: services · Research: live web, 8 parallel specialists · Scorer 2.1.0 · decision.json sha256 3f2a…9c21

> [!WARNING]
> **PIVOT.** Dentists feel the pain, but two incumbents bundle bookkeeping free with practice software.
> Weighted quality 2.9 / 5 · Evidence average 1.6 / 5 · 1 of 3 pilot gates passed

| Pillar | Weight | Quality | Evidence | Finding | Claims |
| --- | --- | --- | --- | --- | --- |
| Problem | 20 | ████░ 4 | ██░░░ 2 | Weekly reconciliation pain, 3 forum threads | C1, C4 |
| Economics | 20 | ██░░░ 2 | █░░░░ 1 | Price ceiling set by bundled incumbents | C9 |
| Market | 8 | ·····  not assessed | ░░░░░ 0 | Not evaluated | |

**What would change this verdict:** paid_engagement gate needs a ledger receipt; competition evidence needs one primary source on incumbent pricing.
<!-- greenfield:generated end -->
```

**Callout.** GitHub alert syntax, which renders as a colored box on GitHub and as a plain quote elsewhere: CAUTION for NO\_GO, WARNING for PIVOT, NOTE for RESEARCH\_INCOMPLETE, TIP for VALIDATE\_BEFORE\_BUILD, IMPORTANT for PROCEED\_TO\_BOUNDED\_PILOT. The first line is the canonical verdict plus W12's plain-English `headline`; the second gives the three numbers.

**Bars.** Five cells, `█` filled and `░` empty, always followed by the digit so a screen reader and a grep both get the number. A null quality shows `·····  not assessed`, never a zero bar, matching the rule that unknown is not 0. Rows are sorted by the profile's weight, heaviest first, so the pillars that matter most come first. A row where quality is 4 or more but evidence is 1 or less gets "gap" after the finding: an attractive idea nobody has tested.

**What would change this verdict.** Derived, not written: the failed pilot gates, pillars below the evidence threshold the next verdict needs, and unresolved fatal blockers, each with the action that would clear it. This needs W12 to expose the scorer's reasons as a structured `blocking` list in `decision.json`; if W12 doesn't, W29 adds it.

**Narrative.** `references/outputs.md` (updated with W27) keeps the agent-written sections below the marker: one-paragraph thesis, market and economics findings, red-team dissent, must-be-true assumptions, next bet. SKILL.md tells the agent to run `report` after `score` and never hand-edit the generated block.

**Consistency with the dashboard.** W18's Decision panel uses the same headline, callout color mapping and bar rendering, from one shared `render_bars()` function in Python and its JS twin.

### Files and functions

- New `skill/scripts/gf_report.py`: `render_block(decision, evaluation) -> str`, `merge(existing_md, block) -> str`, `register()`.
- `score_project.py`: `blocking` list, if W12 hasn't added it.
- Reuses W13's `md_cell()` for every table cell.
- `references/outputs.md`, `SKILL.md`, `skill/assets/mission-control.html` (bar glyph helper).

### Acceptance criteria

- For each of the five verdicts, the callout type and first line match `decision.json` exactly (snapshot tests).
- `report` is idempotent and preserves every byte outside the markers.
- A DECISION.md without markers gets the block inserted at the top with a stderr note; nothing the agent wrote is removed.
- Editing a score in `evaluation.json` and rerunning `score` then `report` updates the table; the hash line changes to match.

### Tests

Snapshots for the template fixture and four filled fixtures; idempotence; narrative preservation including text that looks like a marker inside a code block; a pipe or newline in a finding (escaped by `md_cell`); null quality; every profile's weight ordering.

### Edge cases

Unicode block characters on a terminal without UTF-8 (`report --ascii` uses `#` and `-`); very long findings (truncate at 120 characters in the table with the full text in `evaluation.json`); a hand-edited generated block (overwritten, with a warning that names the edited lines).

### Compared with the best

Competing skill packs produce scorecards the model writes freehand, so the numbers in the memo are whatever it typed. Web validators show a score with no trail. Ours is a memo whose verdict, scores and gaps are generated from a reproducible file, with a hash to prove which one.

## W30: `SECURITY.md` threat model

**Goal.** One page that says what Greenfield protects, against whom, what it does not protect, and how to report a problem, with every "defended" claim pointing at the test that proves it. Closes Sec phase 3's documentation item.

### Outline

1. **What we protect**, four assets: the privacy of your idea and research (it never leaves the machine), the integrity of the verdict (it can't be pushed to PROCEED by edited files), the integrity of evidence (attestations and receipts can't be forged by an agent), and your machine (installer and hooks stay inside their folders).
2. **Trust boundaries**, as a short list: web pages to research agents, agents to the CLI, the dashboard to your browser, hooks to the host, the installer to your filesystem.
3. **Defended and not defended**, one table (below).
4. **Your part**: run attestations yourself in your own terminal, keep `research/greenfield/` private or ignored, review hooks before trusting them, run `greenfield doctor`.
5. **Reporting a vulnerability**: GitHub private vulnerability reporting (needs enabling in the repo's Security settings), acknowledgement within 7 days, supported versions (latest minor only).
6. **Supply chain**: zero runtime dependencies, standard library only; releases carry the wheel's sha256. If you publish to PyPI, use trusted publishing so builds carry provenance.

### The table, drafted from waves 1 to 4

| Threat | Status | How | Proved by |
| --- | --- | --- | --- |
| Web page with prompt injection tells a research agent to write files or run commands | Defended | Research agents are read-only (W5) | W5 agent-file test |
| Agent records a fake human interview or payment | Defended, layered | TTY-only confirmation and HMAC signatures (W11), PreToolUse guard (W27) | W11 and `test_guard.py` |
| Edited `decision.json` or `evaluation.json` ranks a project higher in the portfolio | Defended | Portfolio and dashboard re-score from inputs (W8, W18) | W8 regression test |
| Path in a ledger, run or pilot gate reads files outside the project | Defended | `resolve_inside()`, symlink escape rejected (W6) | W6 tests |
| Malicious JSON crashes or confuses the scorer | Defended | Type-checked validator, fuzz test (W7) | W7 fuzz test |
| Another website in your browser reads the dashboard API (DNS rebinding, CSRF) | Defended | Host, Origin and Sec-Fetch-Site checks, loopback only (W9) | W9 tests |
| Source fetcher tricked into reaching a private network address | Defended | Connect to the vetted IP, ports 80 and 443 only (W16) | W16 tests |
| Other local users read your research | Defended on shared machines | 0700 folders, 0600 files (W15) | W15 tests |
| You, or anyone with full file access, rewrite the whole ledger and key | Not defended | Local HMAC can't stop the key holder; it proves tampering by anyone else | n/a |
| A person who attests honestly-looking but false evidence | Not defended | Attestation records who vouched, not whether it's true | n/a |
| Source excerpts that match but misrepresent the source | Not defended | Excerpt checks are lexical, not semantic; a human review is required before a pilot | n/a |
| A parser bypass of the PreToolUse guard | Partly | Guard is best effort; HMAC still rejects the unsigned event | `test_guard.py` |
| Host agent sandbox or permission bypass | Out of scope | Greenfield relies on the host's controls and can't strengthen them | n/a |

### Files

New `SECURITY.md` at the repo root (GitHub shows it in the Security tab). README limits section and `docs/evidence.md` link to it. `RELEASE_NOTES.md`'s privacy section is replaced by a link.

### Acceptance criteria

- Every row marked Defended names a test, and `tests/test_docs.py` fails if a named test doesn't exist.
- No row says Defended for a wave that hasn't merged; the table is written last, from what actually landed.
- Private vulnerability reporting is enabled on the repo (a settings change Aaron makes; the doc links to it).

### Edge cases

If W11's HMAC or W27's guard changes scope during waves 1 or 4, the table row changes with it. Claims stay narrow: "tamper-evident against anyone without the key", never "tamper-proof".

### Compared with the best

None of the free validators or skill packs I looked at publish a threat model. For a tool whose pitch is "trust this verdict", an explicit not-defended list, backed by tests, is a credibility edge that costs half a day.

## Dependencies, order and effort

Wave 4 should start only after waves 0 to 2 have merged, and it needs about 3.5 days rather than the plan's 1.5 to 2; Wave 5 needs about 1.5 days plus real example runs. The extra time is the package layout, the guard and the docs tests, which are what make this the best free option rather than a rename.

**What each item needs from other waves** (specced in sibling threads, not here):

| Item | Needs | Why |
| --- | --- | --- |
| W22 | W1, W2, W3, W4, W12 | Error helper, version and `--version`, CI to run the wheel job, `ROLES` for `choices=`, the TTY/JSON output rule |
| W23 | W7, W11, W15, W25, W27 | Validator, HMAC key, permissions, install manifest, freshness check |
| W24 | W6, W7, W14 | `resolve_inside()`, placeholder handling, active-run guard and lock |
| W25 | W2, W10, W22 | `ignore_patterns`, platform flag in hook removal, module moves |
| W26 | W1, W3 | Error type; CI for the optional Windows job |
| W27 | W4, W5, W11, W12, W22 | Final role names, read-only agent settings, the attestation path the guard protects, `--json` rule, CLI names |
| W28 | All of waves 3 and 4 | Final commands and the final dashboard for the screenshot |
| W29 | W12, W13, W18 | `headline` and `blocking`, `md_cell()`, shared bar rendering |
| W30 | Waves 1 to 4 merged | The table states only what landed |

**Order inside Wave 4.** W22 first (everything else plugs into it), then W26 (small, touches the same imports), then W24 and W25 in parallel, then W27, then W23 last because doctor checks what all the others built.

**Order inside Wave 5.** W29 first (the README shows its output), then W30, then W28 last, so the docs test runs against final commands.

**Aligned with Wave 0 decisions** (Aaron, 3 Nov): Python 3.11 is the minimum throughout these specs; the role name "Execution & Founder Fit" comes from `ROLES`; CI is required on main, so each wave's PR must pass the new jobs these specs add (wheel install, `make_agents --check`, `gen_cli_docs --check`, docs test).

**PRs.** One PR per wave as decided, one commit per work item so review can go item by item. Versions: 2.1.0 at the end of Wave 4, 2.2.0 at the end of Wave 5; old script entry points are removed in 3.0.

| Item | Estimate |
| --- | --- |
| W22 CLI and package | 1 day |
| W23 doctor and profiles | 0.5 day |
| W24 scaffolded start | 0.5 day |
| W25 dry run, uninstall, plugin | 0.75 day |
| W26 Windows | 0.25 day |
| W27 generator, CLI in skill, guard | 0.5 day |
| W28 README and docs (excluding example runs) | 0.75 day |
| W29 DECISION.md generator | 0.5 day |
| W30 SECURITY.md | 0.25 day |

## Decisions

Aaron answered all five on 3 Nov, each as recommended, so the specs above stand as written.

| Question | Decision |
| --- | --- |
| Windows scope (W26) | Per command: only locking commands refuse; score, ledger verify, portfolio and doctor work on Windows |
| Publish to PyPI | Yes, after Wave 5, with trusted publishing; check the `greenfield-evaluator` name first |
| Real example runs and benchmark (W28) | Yes: three genuine end-to-end evaluations with web access plus a five-idea comparison against a plain agent |
| Claude Code plugin install (W25) | Yes, skill and agents only, no hooks |
| DECISION.md generated block (W29) | Yes: scorer writes verdict and scorecard, agent writes the narrative |

## Sources

- [emotixco/claude-skills-founder README](https://github.com/emotixco/claude-skills-founder) (opened 3 Nov 2026)
- [Command Line Interface Guidelines](https://clig.dev)
- [Unified refactor plan](https://claude.ai/artifact/VniiAwzeSr8oS5mQhvFvXs)
- Repo code read at commit `def6adb` on main
