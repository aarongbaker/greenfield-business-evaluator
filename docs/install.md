# Install, upgrade and uninstall

Greenfield installs in three ways. All of them use only the Python standard library at run time.

| Way | Gives you | Best for |
|---|---|---|
| Claude Code plugin | The skill and the nine research roles in Claude Code | Trying it in Claude Code with two keystrokes |
| `pipx` or `uvx` | The `greenfield` command, which can then install the skill into any repository | Everyday use, Codex, Mission Control |
| `install.py` from a clone | The same install, with no packaging tools at all | Locked-down machines, reading the code first |

## Claude Code plugin

```text
/plugin install greenfield-business-evaluator --marketplace aarongbaker/greenfield-business-evaluator
```

The plugin ships the skill and the nine research roles only. It adds no hooks, so Mission Control stays opt-in. It does not put `greenfield` on your PATH; install the command with `pipx` as well if you want the quickstart, the scorer on your terminal, or the dashboard.

## pipx or uvx

```bash
pipx install git+https://github.com/aarongbaker/greenfield-business-evaluator  # needs-network
pipx upgrade greenfield-evaluator  # needs-network
uvx --from git+https://github.com/aarongbaker/greenfield-business-evaluator greenfield --version  # needs-network
```

`uvx` runs the command without installing it. Either way you then install the skill into a repository with `greenfield install`.

## Install the skill into a repository

Run these from the root of the repository you are evaluating ideas in. `--dry-run` shows every file the install would create or replace and writes nothing.

```bash
greenfield install --platform both --dry-run
greenfield install --platform both --gitignore
```

`--gitignore` adds `.greenfield-observe/` and `research/greenfield/` to `.gitignore` without asking, so private research stays out of commits. Without it, install asks on a terminal and only prints the lines otherwise.

Common variations:

```bash
# One assistant only
greenfield install --platform claude --force
greenfield install --platform codex --force

# The skill without the nine research roles
greenfield install --platform both --no-agents --force

# Personal install, available in every repository
greenfield install --platform both --scope user
```

| Platform | Skill | Research roles |
|---|---|---|
| Claude Code (project) | `.claude/skills/greenfield-business-evaluator/` | `.claude/agents/gf-*.md` |
| Codex (project) | `.agents/skills/greenfield-business-evaluator/` | `.codex/agents/gf-*.toml` |
| Claude Code (user) | `~/.claude/skills/greenfield-business-evaluator/` | `~/.claude/agents/gf-*.md` |
| Codex (user) | `~/.agents/skills/greenfield-business-evaluator/` | `~/.codex/agents/gf-*.toml` |

The installer never modifies `settings.json`, `config.toml`, API keys, approval settings, network permissions, or your product code. Each install writes `.greenfield-install.json` into the skill folder, listing every file it placed with its sha256. If both scopes are installed, the project copy wins in the host; `greenfield doctor` warns when their versions differ.

## Upgrade

```bash
greenfield install --platform both --force
```

`--force` replaces only files this tool installed. If you edited a research role file, the upgrade stops and names it; add `--overwrite-modified` to replace it anyway. The new copy is staged next to the old one and swapped in, so an interrupted upgrade leaves the previous install working.

## From a clone with install.py

`install.py` takes the same options as `greenfield install` and needs nothing but Python:

```bash
git clone https://github.com/aarongbaker/greenfield-business-evaluator.git  # needs-network
cd greenfield-business-evaluator  # needs-clone
python3 install.py --platform both --scope project --project ../your-repo --dry-run  # needs-clone
python3 install.py --platform both --scope project --project ../your-repo  # needs-clone
python3 install.py uninstall --project ../your-repo --yes  # needs-clone
```

An agent can also run the CLI from an installed skill without anything on PATH: `python3 .claude/skills/greenfield-business-evaluator/scripts/greenfield.py doctor`.

## Hooks for Mission Control

The dashboard works without hooks, but it only sees live specialist activity when the host reports it. Hooks are opt-in and project-local:

```bash
greenfield hooks install --platform both
greenfield hooks remove --platform both
```

`hooks install` writes `.claude/settings.local.json` and `.codex/hooks.json`, keeps every hook that is not Greenfield's, and also adds the PreToolUse guard that stops agents from recording human attestations. Restart the assistant afterwards. Claude may ask you to trust project hooks; in Codex, open `/hooks` and approve them. Details are in [Mission Control](mission-control.md).

## Enforcing diligence before new builds

To have your assistant run this evaluation whenever a new project is proposed, copy the relevant snippet into your repository:

- Codex: [`integration/AGENTS.snippet.md`](../integration/AGENTS.snippet.md) into `AGENTS.md`
- Claude Code: [`integration/CLAUDE.snippet.md`](../integration/CLAUDE.snippet.md) into `CLAUDE.md`

The installer does not do this for you, since it changes repository-wide agent behavior. The gate always yields to a user who explicitly asks to skip it.

## Uninstall

```bash
greenfield uninstall --dry-run
greenfield uninstall --yes
```

Uninstall removes the files listed in the install manifest whose hashes still match, and Greenfield's hooks. It keeps files you edited, other skills, other hooks, `.gitignore` lines and everything in `research/greenfield/`. `--keep-hooks` leaves the hooks, and `--purge-telemetry` also deletes `.greenfield-observe/`. Without a terminal it needs `--yes`. Running it twice is safe.

## Windows

Use WSL. On native Windows, the commands that take file locks (`start`, `demo`, `task`, `event emit`, `ledger record`, `ledger reattest` and the hooks) refuse with a clear message. `score`, `ledger verify`, `portfolio` and `doctor` work there.

If something does not work, run `greenfield doctor` and see [Troubleshooting](troubleshooting.md).
