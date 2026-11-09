# Security and threat model

Greenfield Business Evaluator is a local tool. It reads and writes files in your project, and its research agents browse the public web. This page says what it protects, against whom, what it does not protect, and how to report a problem. Every "Defended" row names the test that proves it. `tests/test_security_doc.py` fails if a named test or file goes missing.

Current version: 2.2.0. Supported versions: the latest minor release only.

## What we protect

1. **Your idea and research stay on your machine.** The scorer, Mission Control and the ledger make no network calls. The source checker fetches public pages only when you pass `--allow-network`. Research agents browse the web through your agent host.
2. **The verdict can't be pushed to `PROCEED_TO_BOUNDED_PILOT` by edited files or by an agent.** The verdict is recomputed from `evaluation.json`, never copied from `decision.json`.
3. **Evidence receipts can't be forged by an agent.** Attestations need a person at a terminal and a signed key.
4. **Your machine.** Paths from data stay inside their project folder, and the installer removes only files it installed.

## Trust boundaries

- **Web pages to research agents.** Pages are untrusted. Agents may be steered by injected text.
- **Agents to the CLI.** Agent output is data. Agents run without a shell or write tools.
- **Mission Control to your browser.** Other websites in your browser must not read the local dashboard.
- **Hooks to the host agent.** Hooks run with your agent's permissions. Review them before you trust them.
- **The installer to your filesystem.** Uninstall removes only files whose hash matches the install manifest. Hook edits leave other hooks alone.

## Defended and not defended

| Threat | Status | How | Proved by |
| --- | --- | --- | --- |
| Web page with prompt injection tells a research agent to write files or run commands | Defended | Research agents have only `WebSearch`, `WebFetch`, `Read`, `Grep` and `Glob`. Codex agents run with `sandbox_mode = "read-only"` | `test_claude_agents_have_research_tools_only`, `test_codex_agents_read_only_sandbox` (`tests/test_agents.py`) |
| Agent records a fake human interview or payment | Defended, layered | No shell or write tools for agents. A PreToolUse guard refuses commands that record or touch the key (`skill/scripts/gf_guard.py`). Attestation needs a TTY confirmation code and an HMAC signature (`skill/scripts/gf_ledger.py`) | `test_bash_deny_table`, `test_installed_command_denies_end_to_end` (`tests/test_guard.py`); `test_cli_record_requires_tty`, `test_library_append_without_tty_refused`, `test_tampered_signed_event_fails` (`tests/test_attestation.py`) |
| Edited `decision.json` or `evaluation.json` ranks a project higher in the portfolio or dashboard | Defended | Portfolio and dashboard re-score from `evaluation.json` (`skill/scripts/gf_portfolio.py`, `skill/scripts/gf_observe.py`). A stored decision that disagrees is flagged | `test_forged_decision_not_ranked` (`tests/test_exploits.py`); `test_decision_mismatch_flagged` (`tests/test_observability.py`) |
| A path in a ledger, run or pilot gate reads files outside the project, including a ledger borrowed from another idea | Defended | `resolve_inside()` in `skill/scripts/gf_common.py` resolves symlinks and requires the result to sit under the base folder. The evidence ledger is confined once in `validate()` | `test_pilot_gate_ledger_outside_folder_rejected`, `test_pilot_gate_borrowed_ledger_rejected_low_evidence`, `test_symlink_escape_rejected` (`tests/test_exploits.py`); `test_symlinks` (`tests/test_common.py`) |
| A run id such as `../../escaped` writes a manifest outside `.greenfield-observe/` | Defended | `skill/scripts/gf_observe.py` validates run ids before building any path | `test_manifest_path_rejects_traversal_run_id` (`tests/test_exploits.py`); `test_bad_run_ids_exit_2_and_write_nothing` (`tests/test_cli.py`) |
| Malicious JSON crashes or confuses the scorer | Defended | Type-checked validator; `skill/scripts/score_project.py` returns errors and never throws | `test_never_throws`, `test_audited_crash_inputs` (`tests/test_fuzz.py`) |
| Another website in your browser reads the Mission Control API (DNS rebinding, cross-site requests) | Defended | Server binds to `127.0.0.1`. Every request's `Host` must be a loopback name. `/api/` requests also check `Origin` and `Sec-Fetch-Site` (`skill/scripts/gf_observe.py`) | `test_foreign_host_rejected`, `test_cross_origin_api_rejected`, `test_sec_fetch_cross_site_rejected` (`tests/test_observability.py`) |
| The source fetcher is tricked into reaching a private network address | Defended | `skill/scripts/gf_evidence.py` vets every resolved address as public, connects to the vetted IP (not a second lookup), re-vets each redirect, and allows only ports 80 and 443 | `test_rebinding_connects_only_to_vetted_ip`, `test_ports` (`tests/test_fetcher.py`) |
| Other local users read your research, telemetry or attestation key | Defended on shared machines | `.greenfield-observe/` and the key folder are 0700, their files 0600. Score and decision files keep your umask | `test_new_files_private`, `test_start_tightens_loose_tree` (`tests/test_observability.py`); `test_key_permissions` (`tests/test_attestation.py`) |
| Uninstaller deletes files you edited | Defended | Uninstall removes only files whose hash matches the install manifest (`skill/scripts/gf_install.py`) | `test_edited_agent_survives_uninstall_and_blocks_force` (`tests/test_install.py`) |
| Native Windows file-locking races | Refused | Commands that need file locks exit 3 on native Windows before writing anything. Other commands run. Use WSL for the full tool | `test_each_locking_command_refuses_with_exit_3_and_writes_nothing` (`tests/test_platform.py`) |
| Same-user attacker, or you, rewrites the whole ledger and the key | Not defended | The local HMAC key is on the same account. Whoever holds the key can re-sign a chain. Signing makes forgery costly and makes edits by anyone else detectable. It is not a lock | n/a |
| A person attests to evidence that looks right but is false | Not defended | Attestation records who vouched and when, not whether the claim is true | n/a |
| Source excerpts match the text but misrepresent the source | Not defended | Excerpt checks are lexical, not semantic. A human must review sources before a pilot | n/a |
| A bypass of the PreToolUse guard by spelling a command the parser misses | Partly | The guard is best effort. A bypassed command still needs a TTY and the signing key, which agent shells don't have | `test_bash_deny_table` (`tests/test_guard.py`) |
| Injected page makes an agent send idea text to another site inside a URL (`WebFetch`, `WebSearch`) | Not defended | Domain allowlists don't fit open-ended research. The agent brief tells agents never to put idea text in URLs | n/a |
| A local attacker swaps a file for a symlink between the path check and the read | Not defended | The check and the read are separate steps (`resolve_inside()`, then open). The threat model is a confused or injected agent, not a hostile local user who can write your project folder | n/a |
| `--allow-host` on `gf_observe.py` accepts extra `Host` names | Not defended | This is your choice, for port forwarding or tunnels. Only use it on networks you trust | n/a |
| Host agent sandbox or permission bypass | Out of scope | Greenfield relies on the host's controls and can't strengthen them | n/a |

## How much to trust Proceed

You attest your own receipts. The kind, `--as` type and `--result` are what you declare. Anything with shell access can sign, and `confirm_via` is self-reported, so it catches only accidental injection. An agent can also drive the real CLI under a pseudo-terminal (`script`, `unbuffer`, `expect`, python `pty`), read the one-time code and type it back, which records a genuine `confirm_via: tty`: the code proves a terminal, not a human. Quality, profile, claims and blockers can be changed by hand; every change is shown on each score, not stopped, and Proceed still needs receipts that support every quality above 3. Re-typed or re-exported data, splits under different experiment ids and re-saved binary files are not detected as reuse. A whole run folder copied into another project under the same slug is not detected. A one-word swap within `ledger reidea`'s 10-character allowance (dental to veterinary) is printed, not refused. Someone who deletes both `evaluation_id` and `quality-history.jsonl` can get a copied pre-wave ledger marked `legacy: true`. Source review covers only linked URL facts, and nothing ages evidence.

## Your part

- Run attestations yourself, in your own terminal. An agent can't do this for you, and it shouldn't try.
- Keep `research/greenfield/` private, or add it to `.gitignore`.
- Review hooks before you trust them. Codex project hooks must be reviewed and trusted in `/hooks`.
- Run `greenfield doctor` after install and after upgrades.
- Back up `attest.key` in your config folder. Receipts verify only where that key is.

## Reporting a vulnerability

Report privately through GitHub private vulnerability reporting: [report a vulnerability](https://github.com/aarongbaker/greenfield-business-evaluator/security/advisories/new). This needs private vulnerability reporting enabled in the repository's Security settings. Do not open a public issue for a security problem.

We aim to acknowledge reports within 7 days. Only the latest minor release gets fixes.

## Supply chain

- The package has zero runtime dependencies. It uses only the Python 3.11+ standard library (`pyproject.toml`).
- There is no PyPI publish job yet. When one is added, publish with trusted publishing so builds carry provenance, and publish the wheel's sha256 with each release.
