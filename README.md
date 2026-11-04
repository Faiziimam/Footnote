<h1 align="center">Footnote</h1>

<p align="center"><b>A project tracker that creates and updates itself.</b><br>
It reads your notes and docs, watches your work (git, or just you saying what happened), and keeps your tracker current in
Obsidian, Notion, Google Sheets, Excel or a database. Runs on your own computer. No technical knowledge needed.</p>

<p align="center">
<a href="https://faiziimam.github.io/Footnote/"><b>Website</b></a> ·
<a href="https://github.com/Faiziimam/Footnote/releases/latest">Download</a> ·
<a href="docs/installing.md">Install guide</a> ·
<a href="https://github.com/Faiziimam/Footnote/issues/new/choose">Ask a question or report a problem</a> ·
<a href="CONTRIBUTING.md">Contribute</a>
</p>

<p align="center">
<a href="https://github.com/Faiziimam/Footnote/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/Faiziimam/Footnote/actions/workflows/ci.yml/badge.svg"></a>
<a href="https://github.com/Faiziimam/Footnote/actions/workflows/codeql.yml"><img alt="CodeQL" src="https://github.com/Faiziimam/Footnote/actions/workflows/codeql.yml/badge.svg"></a>
<a href="LICENSE"><img alt="License: Apache-2.0" src="https://img.shields.io/badge/license-Apache--2.0-blue"></a>
<img alt="Python 3.9+" src="https://img.shields.io/badge/python-3.9%2B-blue">
<img alt="No runtime dependencies" src="https://img.shields.io/badge/runtime%20dependencies-0-brightgreen">
</p>

## Who is it for?

- **Founders and makers** who want to know "where are we, what's next?" without keeping a tracker by hand.
- **Developers** who want commits, pull requests and AI-agent work to move tasks automatically.
- **Teams** who need to see who did what, who owns what, and where work collides.
- **Anyone running a project**: a portfolio, an online store, a campaign, client work, research. It is not only for code.

## What you get

- **A tracker that keeps itself current.** Say "I finished the logo and started the landing page", mention `T-004` in a commit, or tick a box in a doc, and the right tasks move.
- **Your tools, both ways.** Edit in Obsidian, Notion, Google Sheets, Excel or SQLite and the change flows back.
- **The whole project's memory.** Architecture, decisions, numbers, timeline and a "is it really done?" checklist.
- **Reports people read.** A manager report, an HTML page, a PowerPoint deck, or a daily, weekly or monthly email.
- **Safe by design.** Your data stays on your computer, there is no account and no server of ours, and every change can be undone.

## Start (2 minutes)

You need **Python 3.9 or newer** ([python.org](https://www.python.org/downloads/)). Nothing else to install.

**Option 1: one file (easiest).** Download `footnote.pyz` from the [latest release](https://github.com/Faiziimam/Footnote/releases/latest), then in the folder you work in:

```bash
python footnote.pyz
```

**Option 2: with npm** (once `footnote-app` is published on npm; it still needs Python, but no Python packages):

```bash
npx footnote-app
```

**Option 3: from source:**

```bash
git clone https://github.com/Faiziimam/Footnote.git
pip install ./Footnote
footnote
```

Then:

1. Run `footnote`. It asks a few plain questions (where do you want your tracker, which AI tool do you use).
2. Run `footnote ui`. Your tracker opens in the browser. Type what happened and it updates. Tasks come from your
   checklists (`- [ ] ...`) or from the headings in documents like `ARCHITECTURE.md` or `README.md`. No docs? Add tasks in the page.

Windows or Mac and not comfortable with a terminal? Double-click **start-tracker.bat** or **Start Tracker.command**.

## Where your tracker can live (use several at once; edits flow both ways)

| You use | Setup | Guide |
|---|---|---|
| Obsidian | open the `Tracker/` folder as a vault | — |
| Notion | `footnote add-tracker notion` | [docs/notion.md](docs/notion.md) |
| Google Sheets | `footnote add-tracker gsheets` | [docs/google-sheets.md](docs/google-sheets.md) |
| Excel / Numbers | `footnote add-tracker csv` → `Tracker.csv` | — |
| A database | `footnote add-tracker sqlite` → `tracker.db` (tables `tasks`, `relations`) | — |

Change a status in Notion or a spreadsheet and the tracker picks it up. Type a new row and it becomes a task.

## Use it with any AI tool

`footnote connect <claude|cursor|codex|gemini|copilot|windsurf|generic>` — see [docs/agents.md](docs/agents.md).
Anything else can use the web address (webhook), a command, or a file drop.

## What updates automatically

- Mention a task ID (`T-004`) in a commit → **In progress**; "closes T-004" or a merge → **Done**.
- A checked box in your docs → Done. A parent task starts when a subtask starts and finishes when all subtasks finish.
- Relationships: nested checklists, headings, "depends on T-003 / “Design logo” / [[Design logo]]" become
  links; tasks show **Waiting on** until their dependencies are done.
- Tracker data stays safe: automation only moves tasks forward; if *you* move one back, it stays where you put it.
  Every automatic change is written to `Tracker/Changelog.md`.

Developers: `python3 -m unittest discover -s tests -t .` · adding a backend = one class in `footnote/mirrors/`.

## It remembers the whole project (not just tasks)

| You want to know | Where | Filled by |
|---|---|---|
| What is it, how far along, what's next | `Project Report.md`, the web page, `footnote report --for manager` | tasks + git |
| What was built, and by which commits/files | `Built.md`, `Timeline.md` | git history |
| The architecture (stack, pages, APIs, data models, how to run) | `Architecture.md` — re-scanned every sync, changes logged | the project files |
| Why things were decided, risks, learnings | `Journal.md` | your AI tool (`tracker_record`) or you |
| The numbers (sales, visitors, spend, cash, anything) | `Metrics.md` + the report | CSV exports (`metrics-import`), Stripe, webhook, or your AI tool |
| Who is doing what, who owns what, who to ask | `Team.md`, `People/` | commit history — see [docs/team.md](docs/team.md) |
| "Is it really done?" | Handover checklist in the report | everything above |

Works for any project: templates exist for portfolios, online stores, SaaS, apps, campaigns, content, finance, client work,
events and research — and anything else works too (tasks, journal and numbers are free-form).
Honest limits: sales and visitor numbers cannot be read from code — they come from an export, Stripe, or someone telling the tool.

## Everything else it can do

| Need | Command / where |
|---|---|
| Undo anything (yours or automatic) | `footnote undo`, `footnote history` |
| Plan: due dates, estimates, priorities, roadmap | `footnote due T-004 next friday`, `- [ ] Launch due:2026-12-01 ~3d !high`, `Roadmap.md` |
| Your own fields, even calculated | `footnote field add days_open --type number --formula "days_since(created)"` |
| Sales from Shopify / WooCommerce / Stripe / CSV | `footnote add-source shopify …`, `metrics-import` |
| Money: categories, monthly profit & loss, invoices | `footnote categorize`, `invoice add`, `Finance.md` |
| Teams: who's doing what, collisions, catch-up | [docs/team.md](docs/team.md), `footnote catchup` |
| GitHub PRs / reviews / build status | `footnote add-source github --opt repo=owner/name` |
| Trackers: Notion, Sheets, Excel, SQLite, GitHub Issues, Trello | `footnote add-tracker …` (reports are published into Notion/Sheets too) |
| Alerts and a weekly digest in Slack / email | `footnote add-notify --slack <url> --digest weekly` |
| Zapier / Make / webhooks | [docs/relay.md](docs/relay.md) |
| Several projects at once | `footnote portfolio add ../shop`, `footnote portfolio` |
| Share a report with anyone | `footnote report --for manager --html report.html` |
| Slides for a review or presentation | `footnote deck review.pptx --for manager` (also a button in the web page) |
| The report by email, daily / weekly / monthly | `footnote add-notify --email-to you@x.com --smtp-host smtp.gmail.com --digest monthly --content report --attach deck` |
| Show it on a screen without risk of changes | `footnote ui --read-only` |
| Optional AI help (other languages, summary paragraph) | `footnote add-llm` — off by default |
| Something wrong? | `footnote doctor`, `footnote log` — [docs/installing.md](docs/installing.md) |

### Safe by design
It runs on **your computer**: no accounts, no servers of ours, no data sent to us (a deliberate decision: [ADR 0001](docs/decisions/0001-runs-on-your-device.md)).
No third-party code at runtime, a locked-down local web page, hostile text handled everywhere, secrets scrubbed from logs, every change undoable,
and releases you can verify. Read the [security policy](SECURITY.md) and the [threat model](docs/threat-model.md); report problems privately.

### Contribute
You don't need to code: tell us where you got stuck, share how you use it, improve the words, test on your system.
See [CONTRIBUTING.md](CONTRIBUTING.md) and the [code of conduct](CODE_OF_CONDUCT.md). The website ([faiziimam.github.io/Footnote](https://faiziimam.github.io/Footnote/)) lives in [`site/`](site/) and is published by the Website workflow.

### Honest limits
Tested against fake versions of Notion, Sheets, Stripe, GitHub, Shopify, WooCommerce, Trello and Slack — not yet against the real
services (`footnote doctor --live` is how you check yours). Not built: Linear/Jira adapters, Google Docs/Figma signals, tax
calendars. A hosted team version and logins are intentionally not offered (everything runs on your device).

## Links

- Website: https://faiziimam.github.io/Footnote/
- Releases: https://github.com/Faiziimam/Footnote/releases
- Changelog: [CHANGELOG.md](CHANGELOG.md)
- Security: [SECURITY.md](SECURITY.md) (report privately via the Security tab)
- Help and ideas: [open an issue](https://github.com/Faiziimam/Footnote/issues/new/choose)

## License

[Apache-2.0](LICENSE). Copyright 2026 Syed Faiz Imam and Footnote contributors. See [NOTICE](NOTICE).
