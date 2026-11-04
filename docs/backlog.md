# Backlog

Rule for now: **strengthen what exists before adding anything new.** Nothing in the last section gets built until the first two are done.

## 1. Status of the owner-dependent items

**Done**

| What | Result |
|---|---|
| GitHub repository created, code pushed, **made public** | https://github.com/Faiziimam/Footnote |
| Commit history rewritten to your name and GitHub noreply address | no personal email in history on `main` |
| `NOTICE` names the copyright holder (Syed Faiz Imam) | done |
| `OWNER/REPO` replaced, CODEOWNERS filled in | site and docs point at `Faiziimam/Footnote` |
| Licence switched to Apache-2.0 | `LICENSE` is the official text; `NOTICE` added |
| First CI run on GitHub | Python 3.9, 3.10, 3.11, 3.12, 3.13, the installer-reproducibility job and the security job all pass |
| Windows and macOS runs | found two real bugs (folder locks, Windows command paths); fixed; **all 8 CI jobs now pass**, including Windows and macOS |

**Still needs you**

| # | What | Why it needs you | How |
|---|---|---|---|
| 1 | Turn on GitHub Pages, then re-run the "Website" workflow | The one API call that does this is blocked in my session. A private repo needs a paid GitHub plan for Pages; otherwise make the repo public | Settings → Pages → Source: **GitHub Actions**; then Actions → Website → Run workflow |
| 2 | Decide on Dependabot PR #1 (11 action upgrades, including the release workflow) | It changes supply-chain code, and they are major version jumps | review release notes; merge when its checks pass |
| 4 | Apply the repository settings | Needs admin rights with your own login (my session can't change them) | run on your computer: `gh auth login` then `scripts/harden_repo.sh Faiziimam/Footnote --apply` |
| 5 | Turn on 2FA (hardware key/passkey), signed commits, tag protection, allowed-Actions list | Account-level settings | `docs/security-hardening.md` |
| 6 | Put the real copyright holder name in `NOTICE`; get a short lawyer check before the first public release | Ownership and AI-generated-code questions are yours | edit `NOTICE` |
| 7 | Add a contact address to the Code of Conduct; confirm the response-time targets in `SECURITY.md` | You are the one committing to them | `CODE_OF_CONDUCT.md`, `SECURITY.md` |
| 8 | Cut the first release tag and check the checksum (the signed attestation works once the repo is public) | Needs your repository | `git tag v0.1.0 && git push --tags` |
| 9 | Test with real accounts: Notion, Google Sheets, Stripe, GitHub, GitHub Issues, Trello, Shopify, WooCommerce, Slack, email | Every integration was tested only against stand-ins | `footnote doctor --live`, then use each for real |
| 10 | Try it inside a real Claude Code and one other AI tool | Never run inside a real agent session | `footnote connect claude` |
| 11 | Open a generated deck in real PowerPoint, Keynote and Google Slides | Verified only with an open-source library and LibreOffice | `footnote deck review.pptx` |
| 12 | Decide the first audience (one group); find about 5 real users for a two-week trial | Only real use shows whether the idea works | your call |
| 13 | Check the name Footnote: trademark search, GitHub/domain, PyPI (`footnote-app`) | Never checked | USPTO / EUIPO / WIPO, registrar |
| 14 | Decide who answers security reports, and how fast | An ongoing commitment | `SECURITY.md` |
| 15 | Publish to npm: create/confirm the npm account with 2FA, then `python scripts/build_npm.py dist/npm && cd dist/npm && npm publish --access public` (the package name `footnote-app` was free when checked) | Needs your npm account | npmjs.com |
| 16 | Review the threat model and decision records and confirm you stand behind them | The public promises are yours | `docs/threat-model.md`, `docs/decisions/` |

## 2. Strengthen the current product first (no new integrations)

| Area | Work |
|---|---|
| Truth | Fix whatever the real-account tests (items 12 to 15 above) reveal; make the fake servers match reality |
| Real agents | Verify the agent instructions are actually followed by Claude Code / Cursor / Codex / Gemini; tune the wording |
| First five minutes | Watch a non-technical person set it up; fix every stumble; shorten the setup questions; add a screen recording to the site |
| Reliability | Performance on large repositories (10k+ files, long history); behaviour with very large trackers; recovery from interrupted writes |
| Platforms | Make Windows and macOS first-class (hook quoting under cmd.exe, paths with spaces, line endings) and promote them from "experimental" in CI |
| Accessibility | Screen-reader and keyboard audit of the web page; contrast check; translate the interface and website |
| Documentation | One page per task a person actually does ("track a launch", "hand over a project"); real screenshots |
| Safety | Second-person security review; fuzz the parsers; consider a bug-bounty-style invitation after the first release |
| Support | Make `doctor` fix problems, not just describe them; add an "export everything" and "delete everything" command |

## 3. Integrations for later (not started)

**Work trackers:** Linear, Jira, Asana, ClickUp, Monday.com, Airtable, Basecamp, Todoist, Microsoft Planner / To Do, Azure DevOps Boards, GitLab issues and merge requests, Bitbucket.

**Code and delivery signals:** GitLab CI, CircleCI, Vercel, Netlify, Sentry, PagerDuty, Datadog.

**Documents and design (activity signals for non-code work):** Google Docs/Drive, Microsoft 365 / SharePoint / OneDrive, Dropbox, Figma, Canva, Miro, Confluence.

**Sales, money and accounting:** PayPal, Square, Lemon Squeezy, Paddle, Gumroad, BigCommerce, Etsy, Amazon Seller, QuickBooks, Xero, FreshBooks, Wave, bank feeds (Plaid and similar).

**Audience and marketing numbers:** Google Analytics 4, Plausible, PostHog, Mixpanel, Google Ads, Meta Ads, Mailchimp / email-list tools.

**People and customers:** HubSpot, Salesforce, Pipedrive, Zendesk, Intercom, Toggl, Clockify, Harvest.

**Talking to it:** Microsoft Teams, Discord, Telegram, WhatsApp, a Slack slash command, "forward an email to create a task", calendar (Google / Outlook).

**More AI tools:** Aider, Cline, Zed, JetBrains AI, Amazon Q (each needs its MCP configuration format verified first).

**No-Python installs:** native programs per operating system (PyInstaller/Nuitka), signed/notarised, via Homebrew, winget, scoop and per-platform npm packages (see ADR 0005; wait until users show Python is the blocker).

**Native packaging:** Zapier app, Make module, n8n node, Obsidian plugin, VS Code extension, JetBrains plugin, menu-bar app, mobile companion.

**Already on the list from before:** Google Sheets via direct sign-in (today: Apps Script or a token), tax and filing calendars (jurisdiction-specific).
