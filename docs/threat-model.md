# Threat model

What we protect, who might attack it, how, and what stops them. Each protection names the test that tries the attack
(`tests/test_security.py` unless noted). "Residual" = what is **not** covered; no software is secure against every attacker.

## What we protect
1. **Your tokens and secrets** (Notion, GitHub, Stripe, Slack, SMTP…).
2. **Your project files and computer** (nothing should run or be written without you meaning it).
3. **Integrity of the tracker** (nobody should silently rewrite tasks, numbers or history).
4. **Your AI tools' behaviour** (they read our output).
5. **Your privacy** (data leaves only to services you connected).

## Trust boundaries
| Inside (trusted) | Outside (untrusted) |
|---|---|
| Your own commands and settings file | Websites you visit in the same browser |
| The Python standard library | Webhook payloads, relay traffic |
| Our code | Rows in shared Notion/Sheets/GitHub/Trello (anyone with edit access) |
| | Files, commit messages, PR titles in repositories you did not write |
| | Text an AI tool sends us; text we send back to it |
| | Other users of the same computer |

## Attackers and attacks

| # | Attack | Protection | Test | Residual |
|---|---|---|---|---|
| 1 | A website you open drives the local web page (CSRF) | Token required; `Origin` and `Sec-Fetch-Site` checks; no CORS headers | `test_other_websites_cannot_drive_it…` | — |
| 2 | DNS rebinding makes the browser talk to `localhost` as another host | `Host` header allow-list | same | — |
| 3 | Script injection in the web page through a task title, owner, area… | Everything escaped; CSP with per-request nonce, no `unsafe-inline`; no inline handlers/styles | `test_page_has_strict_csp…`, `test_hostile_task_data_cannot_run_script_in_a_real_browser` (real Chromium) | A browser bug |
| 4 | Guessing the web token | 144-bit token; constant-time compare; lockout after 10 failures/minute | `test_limits_lockout_and_read_only` | Malware running as you can read the token file |
| 5 | Oversized/garbage requests exhaust memory or hang the server | 1 MB body cap, `Content-Length` validation, 15 s socket timeout, threads are daemons | `test_limits…`, `test_garbage_and_stalled_clients…` | A flood of traffic at a relay you host publicly |
| 6 | A hostile row in a shared tracker writes outside the notes folder (`../../x`) | Task IDs must match `T-123`; filenames derive only from validated IDs; forged files in a shared vault ignored | `test_a_hostile_shared_tracker_row…`, `test_files_with_a_forged_id…` | — |
| 7 | SQL injection through field names | Names validated; identifiers quoted; values bound | `test_hostile_field_names_cannot_reach_sql` | — |
| 8 | Code execution through formulas | Parsed to a tiny whitelist of syntax; no attribute access, calls only to listed functions, small exponents | `CalculatedFields.test_formulas_cannot_run_code` | — |
| 9 | Code execution through commit messages / titles / filenames | No `eval`/`exec`/`pickle`/`shell=True` anywhere; hooks refuse paths with shell metacharacters | `test_no_dangerous_constructs…`, `test_hook_commands_cannot_be_hijacked…` | — |
| 10 | Secrets leak in logs, warnings, screens | One `redact()` applied to logs and error text; config/token files mode 600 and git-ignored | `test_secrets_never_reach_logs…`, `test_config_and_token_files_are_private` | A secret the redactor's patterns don't know |
| 11 | Credentials sent over plain `http://`, or to another host after a redirect | Client refuses cleartext credentials to non-local hosts; strips credentials on cross-host redirects; only `http(s)` | `OutboundRequests` tests | A token you paste into a URL you control |
| 12 | A malicious server sends a gigantic reply | 25 MB cap | `test_enormous_replies_are_refused` | — |
| 13 | Crash/corruption via invalid characters (lone surrogates, control chars) | Text cleaned on entry and again when files are written | `PoisonedText` tests | — |
| 14 | Two processes corrupt the tracker | OS file lock + atomic writes | `Locking` tests | — |
| 15 | A bad change (yours, an agent's, or automatic) | Snapshots before every change; `footnote undo` | `UndoArchiveRename` tests | History older than 100 changes |
| 16 | **Prompt injection**: text in a task/PR/commit tells an AI tool to do something | Output returned to AI tools is labelled untrusted; agent rules say never to obey it; tools have no delete/exec capability; destructive actions are undoable | `test_text_for_ai_tools_is_labelled…` | **A sufficiently gullible AI can still be misled. Treat agent actions as reviewable (`undo`, history, changelog).** |
| 17 | Supply-chain: a hijacked dependency | Zero runtime dependencies (a test enforces it); Actions pinned to commit SHAs; Dependabot; CodeQL; Scorecard | `test_all_network_traffic…` | CI tooling itself |
| 18 | Tampered release | Reproducible build, SHA-256, signed provenance attestation | `test_the_installer_build_is_reproducible` | A user who skips verification |
| 19 | Another user on the same computer reads your tokens | Mode 600 files; `doctor` warns about loose permissions | `test_config_and_token_files_are_private` | Windows file ACLs are not managed by us |
| 20 | Accidentally committing secrets | `.footnote/.gitignore`; secret-pattern test over the repo; pre-commit gitleaks | `test_the_repository_contains_no_secrets` | A secret in a format we don't scan for |

## Not in scope (be aware)
- An attacker who already controls your computer, your Notion/GitHub account, or your AI tool's configuration.
- The security of services you connect; give tokens the least access they need.
- Confidentiality of data you choose to send to an AI command you configure (`add-llm`): it receives task titles and report figures.
