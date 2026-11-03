# Wave 0 specs: foundation

Nov 3, 2026 · @Aaron

Wave 0 adds four pieces of plumbing that every later wave imports, with no change to scores or verdicts. Each spec below gives the goal, design, files, acceptance criteria, tests, edge cases, and how it compares to other idea-validation tools. Plan: [unified refactor plan](https://claude.ai/artifact/VniiAwzeSr8oS5mQhvFvXs).

## At a glance

Wave 0 is about half a day of work in one PR. W1 and W4 must merge first, because 10 of the 26 later items build on them. W2 and W3 touch separate files and can be built in parallel with them.

| Item | New files | Changed files | Effort | Unblocks |
| --- | --- | --- | --- | --- |
| W1 shared helpers | `skill/scripts/gf_common.py`, `tests/test_common.py` | `gf_observe.py`, `gf_runs.py` (atomic write only) | 2 to 3 h | W6, W7, W8, W11, W14, W15, W22 |
| W2 packaging hygiene | `CHANGELOG.md` | `install.py`, `.gitignore`, `RELEASE_NOTES.md`, all scripts (`--version`) | 1 h | W22, W25 |
| W3 CI | `.github/workflows/ci.yml`, `.github/dependabot.yml` | none | 1 h | Gate for every later PR; runs W7's fuzz test |
| W4 `ROLES` table | `skill/scripts/gf_roles.py`, `tests/test_roles.py` | `make_agents.py`, `gf_observe.py`, `gf_runs.py`, `configure_hooks.py`, 18 agent files, README role list | 1 to 2 h | W5, W20, W27 |

The wave gate: all 37 existing tests plus the new ones pass on Python 3.11 to 3.14, a fresh install contains no `.pyc` files, and scoring the template and the test fixture gives byte-identical `decision.json` before and after.

## W1: gf\_common.py shared helpers

**Goal.** One small module that every script uses for four risky operations: confining a path to a folder, loading JSON safely, writing files atomically, and reporting errors. Today each script does these its own way: 20 separate `json.loads` or `read_text` calls with no size limit, two different atomic-write styles, and five different `ERROR:` formats. Wave 0 adds the module and moves only the call sites where behavior stays identical. Wave 1 switches the security-sensitive call sites over.

**Where it lives.** `skill/scripts/gf_common.py`, next to the scripts that import it, so the installed skill carries it. Scripts already import siblings this way (`from gf_profiles import ...`). Root scripts (`configure_hooks.py`, `make_agents.py`) add `ROOT / "skill" / "scripts"` to `sys.path`. Standard library only, Python 3.11+.

**API.**

```python
VERSION = "2.0.0"                      # single source, see W2
MAX_JSON_BYTES = 5 * 1024 * 1024       # 5 MiB default

class GFError(Exception):
    def __init__(self, what, *, path=None, hint=None, code=2): ...
    def as_dict(self) -> dict          # {"error": what, "path": ..., "next": ..., "code": ...}

def report(err, *, stream=sys.stderr) -> int   # prints, returns err.code

def resolve_inside(base, candidate, *, must_exist=False) -> pathlib.Path

def load_json(path, *, max_bytes=MAX_JSON_BYTES, expect=dict,
              reject_duplicates=True, allow_nan=False)

def atomic_write(path, data, *, mode=None)            # bytes or str
def atomic_write_json(path, obj, *, mode=None)
```

**resolve\_inside(base, candidate).** Resolves `base` strictly (it must exist), joins the candidate, resolves the result (which follows every symlink), and raises `GFError` unless the result is `base` or below it. Absolute candidates are allowed only if they land inside. Rejects empty strings and NUL bytes up front with a clear message instead of a raw `ValueError`. With `must_exist=True` it also requires the target to exist. Returns the resolved path, so callers store and open the same path they checked. Analogy: a bouncer who checks where you end up, not which door you used.

**load\_json(path).** Checks size with `stat()` before reading, then reads at most `max_bytes + 1` bytes so a file that grows mid-read is still caught. Decodes as UTF-8 and accepts a BOM (Windows editors add one). Rejects `NaN` and `Infinity`, because a `NaN` quality score compares false against every threshold and can slip past gates. Rejects duplicate keys, because a reviewer reading the file sees the first value while Python silently keeps the last one. Converts `RecursionError` from deeply nested input into a `GFError`. Checks the top-level type against `expect`.

**atomic\_write(path, data, mode=None).** Creates a temp file in the same folder with `tempfile.mkstemp` (already 0600), writes, flushes, `fsync`s, sets the final mode, `os.replace`s, then `fsync`s the folder on POSIX. Deletes the temp file if anything fails, which the current `atomic_json` does not. When `mode` is `None`, it keeps the existing file's mode, or uses the umask default for a new file, so Wave 0 changes no permissions. W15 later passes `0o600`. `atomic_write_json` writes 2-space JSON, `ensure_ascii=False`, `allow_nan=False`, trailing newline.

**report(err).** One error shape everywhere, following the [Command Line Interface Guidelines](https://clig.dev/) advice to rewrite errors for humans and suggest the next command:

```
ERROR: evaluation.json is not valid JSON (line 14, column 3)
  path: research/greenfield/acme/evaluation.json
  next: fix the file, then run: score_project.py research/greenfield/acme/evaluation.json
```

The first line keeps the existing ` ERROR:  ` prefix, so anything that greps for it still works. `as_dict()` exists now so W22's `--json` mode can print errors as JSON without another refactor. Exit code stays 2 for all errors, matching today.

**Call sites moved in Wave 0 (no behavior change).**

1. `gf_observe.atomic_json` becomes a thin wrapper over `atomic_write_json`, so `gf_runs` gets it for free.
2. Nothing else. The `load_json` and `resolve_inside` switch-over belongs to W6 and W7 in Wave 1, where the behavior change is the point and gets its own regression tests.

**Acceptance criteria.**

- `gf_common.py` exists, imports only the standard library, and is copied by `install.py`.
- Every function above has a docstring and is covered by `tests/test_common.py`.
- `decision.json` for the template and for the `sample()` fixture in `tests/test_skill.py` is byte-identical before and after.
- All 37 existing tests pass unchanged.

**Tests (`tests/test_common.py`).**

| Function | Case | Expected |
| --- | --- | --- |
| `resolve_inside` | `"a/b.json"` inside base | returns resolved path |
| `resolve_inside` | `"../x"`, `"/etc/passwd"` | `GFError` naming base |
| `resolve_inside` | symlink inside base pointing outside | `GFError` |
| `resolve_inside` | symlink inside base pointing inside | allowed |
| `resolve_inside` | `""`, `"a\x00b"` | `GFError`, not `ValueError` |
| `resolve_inside` | base itself reached through a symlink | allowed (base resolved first) |
| `load_json` | file over limit, file grows past limit during read | `GFError` with size and limit |
| `load_json` | `NaN`, `Infinity`, duplicate key | `GFError` naming the problem |
| `load_json` | UTF-8 BOM | loads |
| `load_json` | 100,000 nested `[` | `GFError`, no `RecursionError` |
| `load_json` | list when `expect=dict` | `GFError` |
| `atomic_write` | crash mid-write (monkeypatched `os.replace` raises) | original file intact, no temp file left |
| `atomic_write` | `mode=0o600` | final mode 0600 |
| `atomic_write` | `mode=None`, existing 0640 file | stays 0640 |
| `report` | all fields | three-line format, returns 2 |

**Edge cases and limits.**

- Time-of-check to time-of-use: a local attacker could swap a symlink between `resolve_inside` and `open`. This is out of scope because the threat model is a confused or prompt-injected agent, not a hostile local user. W30's `SECURITY.md` should say so.
- Case-insensitive file systems (macOS default): `is_relative_to` compares resolved paths, which `resolve()` normalizes, so `Research/` and `research/` agree.
- Network drives where `fsync` on a folder fails: catch `OSError` on the folder `fsync` only and carry on.
- Windows: `os.replace` works, folder `fsync` is skipped. Full Windows behavior is W26.

**Compared with other tools.** Hosted validators such as [ValidatorAI, IdeaProof and DimeADozen](https://preuve.ai/blog/best-startup-validation-tools-2026) publish no code, so users cannot check how inputs are handled. W1 is invisible to users but is what lets GreenField claim, with tests to prove it, that a malformed or hostile file cannot silently change a verdict. No hosted tool can make that claim checkable.

## W2: packaging hygiene

**Goal.** A user who installs GreenField gets exactly the source files, a clear license, a changelog, and a version number they can quote in a bug report. Today none of that holds. I ran the test suite and then `install.py` into an empty folder: the install contained 14 `.pyc` files from my machine. No script answers `--version`, and the only release history is a prose `RELEASE_NOTES.md` that says "v2".

**Already done.** The repo import added an MIT `LICENSE` and a `.gitignore` covering `__pycache__/`, `*.pyc`, `.greenfield-observe/` and `research/greenfield/`. W2 keeps both and adds what is missing.

**Design.**

1. **Clean installs.** `install_skill()` calls `shutil.copytree(source, dst, ignore=IGNORE)` with `IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".DS_Store", "*.tmp-*", ".pytest_cache")`. The installer then walks the destination and fails loudly if any ignored pattern slipped through, so a future copy path cannot regress silently.
2. **One version.** `VERSION = "2.0.0"` lives in `gf_common.py` (W1). Every script's parser gets `parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")`, including `install.py` and `configure_hooks.py`. No `-v` short flag, because [the CLI guidelines](https://clig.dev/) note `-v` is ambiguous between verbose and version. W22's `pyproject.toml` reads the same constant, so there is never a second number to bump.
3. **Semver rules, written down.** Major: a change to `evaluation.json` that older files fail, or a verdict that changes for the same input. Minor: new commands, new optional fields, new output fields. Patch: fixes with no output change. `schema_version` ("2.0") stays separate from the tool version and only changes on a major.
4. **`CHANGELOG.md`** in [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format, with an `Unreleased` section and a `2.0.0 - 2026-10-23` entry that summarises today's `RELEASE_NOTES.md`. `RELEASE_NOTES.md` becomes a one-line pointer to the changelog so there is one history. Each wave PR adds its lines under `Unreleased`.
5. **Installer records what it installed.** Write `.greenfield-version` (one line: `2.0.0`) into each installed skill folder. W23's `doctor` and W25's `uninstall` read it to tell a stale install from a current one.

**Files.** `install.py`, `skill/scripts/gf_common.py`, every `main()` in `skill/scripts/`, `configure_hooks.py`, new `CHANGELOG.md`, `RELEASE_NOTES.md`.

**Acceptance criteria.**

- After running the full test suite, a fresh `install.py --platform both` into a temp folder contains zero files matching `*.pyc`, `__pycache__` or `*.tmp-*`.
- `python3 <script> --version` prints `<name> 2.0.0` and exits 0 for all 8 entry points (6 scripts plus `install.py` and `configure_hooks.py`).
- `grep -rn '2\.0\.0'` finds the version in `gf_common.py` only (plus the changelog).
- The installed skill folder contains `.greenfield-version`.

**Tests.**

- `PackageTests.test_install_has_no_bytecode`: import every script first so `__pycache__` exists, install, assert no bytecode in the destination.
- `PackageTests.test_version_flag`: run each entry point with `--version` in a subprocess and compare to `gf_common.VERSION`.
- `PackageTests.test_single_version_source`: scan `*.py` for a semver literal outside `gf_common.py`.
- `PackageTests.test_changelog_has_current_version`: `CHANGELOG.md` contains `## [2.0.0]`.

**Edge cases.**

- `--force` reinstall over an older install that did ship `.pyc` files: `rmtree` already removes the old folder, so stale bytecode goes too. Add a test anyway.
- A user's own files inside the installed skill folder are deleted by `--force` today. Out of scope here; W25 (`install --dry-run`) should list them before deleting.
- Agent role files are single files copied with `copy2`, so the ignore list does not apply. They are generated text and never have bytecode.

**Compared with other tools.** Of the 7 validators [tested by Preuve](https://preuve.ai/blog/best-startup-validation-tools-2026), none is listed as open source or run locally. GreenField's MIT license and versioned changelog are its main free-tool advantage: people can pin a version, read exactly what changed, and fork it. OpenSSF Scorecard treats a declared license and no checked-in binaries as basic trust signals ([checks list](https://github.com/laurentsimon/scorecard)), and stray `.pyc` files count as binaries in that sense.

## W3: CI workflow

**Goal.** Every push and PR runs the full test suite on every supported Python and both supported operating systems, so each later wave PR shows green or red before Aaron reviews it. The plan requires each wave to end with the suite green; CI makes that a visible check instead of a promise.

**Python floor: 3.11 (decided 3 Nov).** The README says 3.10+, but [Python 3.10 reached end of life on 1 October 2026](https://devguide.python.org/versions/) and gets no more security fixes. The existing test `test_codex_roles_valid_toml` already imports `tomllib`, which only exists from 3.11, so the suite fails on 3.10 today. Raising the floor costs nothing real and fixes both. W17 corrects the README sentence.

**Design: `.github/workflows/ci.yml`.**

```yaml
name: CI
on:
  push: {branches: [main]}
  pull_request:
  workflow_dispatch:
permissions:
  contents: read
concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true
jobs:
  test:
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, macos-latest]
        python: ["3.11", "3.12", "3.13", "3.14"]
    runs-on: ${{ matrix.os }}
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@<full commit SHA>      # v4
        with: {persist-credentials: false}
      - uses: actions/setup-python@<full commit SHA>  # v5
        with: {python-version: "${{ matrix.python }}"}
      - run: python -W error -m unittest discover -s tests -v
      - run: python -m compileall -q skill install.py configure_hooks.py make_agents.py
      - name: Generated agent files are up to date
        run: python make_agents.py && git diff --exit-code platform/
      - name: Clean install smoke test
        run: |
          d=$(mktemp -d)
          python install.py --platform both --project "$d"
          test -z "$(find "$d" -name '*.pyc' -o -name __pycache__)"
  fuzz:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps: [checkout, setup-python 3.13,
            run: GF_FUZZ_ITERATIONS=20000 python -m unittest tests.test_fuzz -v]
```

Notes on the choices:

1. **No dependencies to install.** Everything is standard library, so there is no `pip install` step, no cache, and nothing to pin besides the two actions.
2. **Actions pinned by full SHA, token read-only, credentials not persisted.** These are the OpenSSF Scorecard Pinned-Dependencies, Token-Permissions and Dangerous-Workflow checks ([checks list](https://github.com/laurentsimon/scorecard)). Use `pull_request`, never `pull_request_target`.
3. **`-W error`** turns deprecation warnings into failures, so a Python 3.15 removal shows up a year early.
4. **macOS in the matrix** because the ledger and task manifest use `fcntl` locks, and macOS is a supported platform. Windows is not in the matrix; W26 adds one Windows job that only checks the clear startup error.
5. **Generated-files check** runs `make_agents.py` and fails on any diff, so the 18 agent files can never drift from the `ROLES` table (W4). W27 moves the script to `tools/` and updates the path.
6. **Fuzz job slot.** W7 (Wave 1) writes `tests/test_fuzz.py`, the never-throws test for the validator. W3 adds the job now, gated with `if: hashFiles('tests/test_fuzz.py') != ''` so it is skipped cleanly until the file exists. In the normal suite the fuzz test runs a small fixed-seed sample (about 500 cases) so local runs stay fast. The CI job raises it through `GF_FUZZ_ITERATIONS`.
7. **`.github/dependabot.yml`** with one `github-actions` ecosystem entry, weekly, so the pinned SHAs get update PRs.

**Branch protection (approved 3 Nov).** Once the workflow has run once, mark the `test` jobs as required checks on `main` in [repository settings](https://github.com/aarongbaker/greenfield-business-evaluator/settings/branches). This is a settings change, not code.

**Acceptance criteria.**

- The workflow runs on a PR and on push to `main`; all 8 matrix jobs pass on the current code once the floor is 3.11.
- Total wall time under 3 minutes for the test jobs (the suite takes about 1.1 s locally).
- Deliberately breaking one test in a scratch branch turns the check red.
- A README badge links to the workflow (added in W28 with the rest of the README).

**Edge cases.**

- `test_observability` starts a local HTTP server. It already binds `127.0.0.1` port 0, so parallel matrix jobs cannot collide. Keep it that way.
- macOS runners have a different `TMPDIR` that resolves through `/private`. Path-confinement tests must resolve `tempfile` paths before comparing, which `resolve_inside` already does.
- If the `fcntl` import ever moves behind a platform check (W26), the test matrix still covers both lock paths through macOS and Linux.

**Compared with other tools.** None of the hosted validators publish tests at all, and their accuracy figures are self-reported ([Preuve's review](https://preuve.ai/blog/best-startup-validation-tools-2026) notes IdeaProof's 89% figure is "internal and uncertified"). A public green CI badge, plus regression tests that reproduce each security exploit from Wave 1, is evidence a user can check for themselves.

## W4: one ROLES table

**Goal.** Each of the nine roles has one display name, one Claude id and one Codex id, defined once in Python and used by the agent generator, the dashboard, the task manager, the hook matcher and the docs. Today the list is written out in five places and has already drifted:

| Where | Role list | Value role | Execution role | Order |
| --- | --- | --- | --- | --- |
| `make_agents.py` `ROLES` | dict with title and brief | Customer Value | Feasibility & Founder Fit | pillar order |
| `README.md` "The eight roles" | hand-written | Customer Value | Execution & Founder Fit | pillar order |
| `mission-control.html` `roles` | JS object | Value proposition | Execution & feasibility | dashboard order |
| `gf_observe.py` `AGENTS` (and `gf_runs.ROLES`) | slug list | n/a | n/a | competition before value |
| `configure_hooks.py` `REGEX` | hard-coded regex | n/a | n/a | n/a |

So the same specialist is called three different things depending on where you look, which is UI finding U8.

**Design: `skill/scripts/gf_roles.py`.**

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class Role:
    key: str            # "value"
    display: str        # "Customer Value"
    pillar: str | None  # "value"; None for the red team
    brief: str          # role-specific instructions, moved from make_agents.py

    @property
    def claude_id(self): return f"gf-{self.key}"   # agent file and hook name
    @property
    def codex_id(self):  return f"gf_{self.key}"   # Codex TOML name

ROLES: tuple[Role, ...] = (...)        # 8 specialists in pillar order, then redteam
SPECIALISTS = ROLES[:-1]
REDTEAM = ROLES[-1]
BY_ID = {...}                          # both id spellings -> Role

def normalize(name) -> Role | None     # accepts gf-x, gf_x, any case
def hook_matcher() -> str              # "^gf[-_](problem|market|...)$"
```

It lives in `skill/scripts/` so the installed skill and the dashboard server can import it. `make_agents.py` adds that folder to `sys.path`. The shared `COMMON` instruction text stays in `make_agents.py`, because only the generator uses it.

**Canonical names (decided 3 Nov).** Problem Discovery, Market & ICP, Customer Value, Unit Economics, Distribution & GTM, Competitive Intelligence, Execution & Founder Fit, Timing & Survivability, Independent Red Team. These match the agent files and README except one: "Execution & Founder Fit" replaces the agent file's "Feasibility & Founder Fit", because it matches pillar P7 in `references/pillars.md` and the README. Order is pillar order (P1 to P8), matching the scoring weights.

**Call sites.**

1. `make_agents.py` loops over `gf_roles.ROLES`. Output differs only in the execution role's title line, so 2 of 18 generated files change.
2. `gf_observe.AGENTS = [r.claude_id for r in ROLES]`. `clean_agent()` uses `normalize()`.
3. `gf_runs.ROLES` already aliases `AGENTS`; no change. `gf_runs.coverage()` replaces its hard-coded pillar tuple with `[r.pillar for r in SPECIALISTS]`.
4. `configure_hooks.REGEX = gf_roles.hook_matcher()`. The string must stay byte-identical to today's, so existing installed hooks are still recognised and removable.
5. `current_state()` adds `"roles": [{"id": r.claude_id, "name": r.display, "pillar": r.pillar}, ...]` to the `/api/state` payload. This is additive; the dashboard ignores it until W20 swaps its JS `roles` object for this list.
6. README "The eight roles" stays hand-written for now (W28 rewrites the README), but a test checks it lists every display name.

**Visible changes.** Two only: the execution agent's title, and Mission Control agent cards appear in pillar order (value moves up two places). Scores, verdicts and the task manifest format do not change. The dashboard labels still differ until W20; that is expected.

**Acceptance criteria.**

- Searching the repo for a role display name finds it in `gf_roles.py`, generated agent files and docs only, not in other `.py` files.
- `python make_agents.py && git diff --exit-code platform/` is clean after the change is committed (W3 enforces this in CI).
- `hook_matcher()` equals the old `REGEX` string exactly.
- `/api/state` includes `roles` with 9 entries.

**Tests (`tests/test_roles.py`).**

- 9 roles, unique keys, unique display names, exactly one with `pillar=None`.
- Specialist pillars equal the keys of `gf_profiles.BASE`, so a new pillar cannot be added without a role.
- `gf_observe.AGENTS` equals the ROLES ids, in order.
- `hook_matcher()` matches all 18 ids, rejects `gf-other`, `xgf-market`, `gf-market-2`, and equals the legacy string.
- `normalize()` round-trips both spellings and returns `None` for unknown names.
- Each generated Claude file's `# Title` line and each Codex TOML `name` match the table.
- `README.md` contains every display name.

**Edge cases.**

- Existing runs: `events.jsonl` stores the slug (`gf-value`), not the display name, so old runs render with the new names automatically.
- Hooks installed with an older version: unchanged regex means `configure_hooks.py remove` still finds them.
- Users who customised an installed agent file: `install.py` already refuses to overwrite without `--force`, so a rename never silently clobbers their edits.

**Hooks for later waves.** W5 adds a per-role tool policy (read-only research tools for Claude, `sandbox_mode = "read-only"` for Codex), most naturally as a field on `Role`. W20 reads `roles` from `/api/state`. W27 regenerates agents for the new CLI paths.

**Compared with other tools.** Hosted tools present fixed report sections (DimeADozen sells a 7-section starter report, per [Preuve's comparison](https://preuve.ai/blog/best-startup-validation-tools-2026)). GreenField's named, independent specialists plus a red team are a real differentiator, but only if the same specialist has the same name in the agent list, the dashboard and the final report. W4 makes that consistency structural rather than a matter of care.

## Cross-wave dependencies and open questions

Wave 0 hands later waves these contracts. Sibling specs should build on them rather than re-design them.

| Later item | Wave | Uses from Wave 0 |
| --- | --- | --- |
| W5 agent tool limits | 1 | `Role` dataclass gains a tool-policy field; `make_agents.py` already loops over `ROLES` |
| W6 path confinement | 1 | `resolve_inside()`; switches scorer, ledger and runs call sites over |
| W7 never-throwing validator | 1 | `load_json()`, `GFError`, `report()`; writes `tests/test_fuzz.py`, which W3's fuzz job picks up |
| W8 portfolio re-scoring | 1 | `load_json()` and `resolve_inside()` for each listed evaluation |
| W11 HMAC ledger | 1 | `atomic_write(mode=0o600)` for the key file |
| W14, W15 | 2 | `atomic_write(mode=0o600)`; `GFError` hints for "a run is already active" |
| W17 README fixes | 2 | Change "Python 3.10+" to "3.11+" (floor approved) |
| W20 dashboard status | 3 | `roles` list in `/api/state` |
| W22 CLI and `pyproject.toml` | 4 | `VERSION`, `GFError.as_dict()` for `--json` errors |
| W23 doctor, W25 uninstall | 4 | `.greenfield-version` marker written by the installer |
| W26 Windows | 4 | Adds a Windows CI job next to W3's matrix |
| W27 `tools/` move | 4 | Updates the generated-files CI step path |
| W28 README | 5 | CI badge; canonical role names |

**Decisions.**

- [x] Raise the minimum Python from 3.10 to 3.11. Aaron: yes (3 Nov).
- [x] Rename "Feasibility & Founder Fit" to "Execution & Founder Fit". Aaron: yes (3 Nov).
- [x] Turn on required status checks for `main` after the first CI run. Aaron: yes (3 Nov).

## Sources

- Code facts come from `main` at commit `def6adb` of [aarongbaker/greenfield-business-evaluator](https://github.com/aarongbaker/greenfield-business-evaluator), read and run on 3 Nov 2026 (37 tests pass; a post-test install contained 14 `.pyc` files).
- [GreenField Evaluator: unified refactor plan](https://claude.ai/artifact/VniiAwzeSr8oS5mQhvFvXs)
- [Best AI Startup Idea Validation Tools (2026)](https://preuve.ai/blog/best-startup-validation-tools-2026), Preuve AI, updated 26 Oct 2026. Written by a competitor, so treat its rankings with care; used here only for prices and features.
- [I tested 7 free AI startup idea validators](https://dev.to/marketoracle/i-tested-7-free-ai-startup-idea-validators-most-are-useless-3-are-worth-your-time-15fd), DEV Community
- [Command Line Interface Guidelines](https://clig.dev/)
- [Status of Python versions](https://devguide.python.org/versions/), Python Developer's Guide
- [OpenSSF Scorecard default checks](https://github.com/laurentsimon/scorecard) (fork of the upstream README)
