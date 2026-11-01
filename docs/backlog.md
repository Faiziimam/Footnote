# Backlog

Rule for now: **strengthen what exists before adding anything new.** Nothing in the last section gets built until the first two are done.

## 1. Waiting on the project owner (only you can do these)

| # | What | Why it needs you | How |
|---|---|---|---|
| 1 | Create the GitHub repository; `git init`, first commit, push | The folder isn't a git repository yet; nothing has been committed | your GitHub account |
| 2 | Replace `Faiziimam/Footnote` in the website | We don't know the repository address | `python scripts/set_site_repo.py yourname/yourrepo` |
| 3 | Put the real copyright holder name in `NOTICE` (the licence is now Apache-2.0), and get a short lawyer check before the first public release | Ownership and AI-generated code questions are yours to settle | edit `NOTICE` |
| 4 | Add a contact address to the Code of Conduct | Reports need somewhere to go | `CODE_OF_CONDUCT.md` |
| 5 | Put your GitHub username in CODEOWNERS | Required reviews can't work without it | `.github/CODEOWNERS` |
| 6 | Confirm the response-time targets in SECURITY.md (3 / 7 / 30 days) | You are the one committing to them | `SECURITY.md` |
| 7 | Apply the repository settings | Files cannot switch on branch protection, secret scanning or push protection | `scripts/harden_repo.sh Faiziimam/Footnote --apply` |
| 8 | Turn on two-factor authentication (hardware key/passkey), signed commits, tag protection, allowed-Actions list | Account-level settings | `docs/security-hardening.md` |
| 9 | Watch the first CI run on GitHub, including Python 3.10 and the experimental Windows/macOS jobs | Workflows have been validated but never executed; 3.10 was never run | GitHub Actions tab |
| 10 | Enable GitHub Pages and publish the website | Needs your repository and settings | Settings → Pages (workflow included) |
| 11 | Cut the first release tag (`v0.1.0`) and verify the checksum and attestation | Needs your repository | `git tag v0.1.0 && git push --tags` |
| 12 | Test with real accounts and tokens: Notion, Google Sheets (Apps Script), Stripe, GitHub, GitHub Issues, Trello, Shopify, WooCommerce, Slack, email | Every integration so far was tested only against fakes we wrote | `footnote doctor --live`, then use each for real |
| 13 | Try it inside a real Claude Code (and one other AI tool) | Never run inside a real agent session | `footnote connect claude` |
| 14 | Try it on real Windows and macOS | Only simulated here | install and run `footnote doctor` |
| 15 | Open a generated `.pptx` in real PowerPoint (and Keynote / Google Slides) | Verified only with an open-source library and LibreOffice | `footnote deck review.pptx` |
| 16 | Decide who it is for first (one group, not "everyone") | Positioning drives what to build next | your call |
| 17 | Find about 5 real users for a two-week trial; decide what counts as success | Only real use shows whether the idea works | see "Is this worth it?" notes |
| 18 | Confirm the name "Footnote" is free (GitHub, PyPI, domain) and decide on PyPI publishing | We never checked | PyPI / domain registrar |
| 19 | Decide who answers security reports and how fast | An ongoing commitment | `SECURITY.md` |
| 20 | Review the threat model and ADRs, and confirm you agree with the claims they make | The public promises are yours | `docs/threat-model.md`, `docs/decisions/` |

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

**Native packaging:** Zapier app, Make module, n8n node, Obsidian plugin, VS Code extension, JetBrains plugin, menu-bar app, mobile companion.

**Already on the list from before:** Google Sheets via direct sign-in (today: Apps Script or a token), tax and filing calendars (jurisdiction-specific).
