# Launch post drafts

Edit the bracketed parts, then post. Everything here is true as of v0.1.0; if you change a claim, check it against the README first.
Be there for the first two hours after posting: answer every comment, and thank people who report problems.

Links to use:
- Website: https://faiziimam.github.io/Footnote/
- Source: https://github.com/Faiziimam/Footnote
- Try it: `npx footnote-app` (needs Python 3.9+)

---

## 1. Show HN

**Title** (80 characters or fewer):

> Show HN: Footnote – a project tracker that updates itself from git and plain English

**Text:**

> Hi HN, I'm Faiz. I built Footnote because every tracker I've used goes stale the week after I set it up.
>
> Footnote sits next to your project and keeps the tracker current. It reads your checklists and docs, your git history, and anything you tell it in plain English ("finished the logo, started the landing page"). Mention `T-004` in a commit and the task moves; "closes T-004" or a merge finishes it. If you move a task by hand, automation won't push it back.
>
> It syncs both ways with Obsidian/markdown, Notion, Google Sheets, CSV/Excel, SQLite, GitHub Issues and Trello. It also keeps the parts trackers usually forget: an architecture map re-scanned from the code, a decisions/risks journal, business numbers (Shopify, WooCommerce, Stripe or CSV), a team view built from commit history, and reports you can email or turn into a PowerPoint deck. AI assistants (Claude, Cursor, Codex, Gemini, Copilot, Windsurf) can use it over MCP.
>
> Some choices you may care about:
> - Runs on your computer. No accounts, no server of ours, nothing sent to us.
> - Python standard library only: zero runtime dependencies (a test enforces it).
> - Every change, yours or automatic, is saved first, so `footnote undo` works.
> - Releases are reproducible and come with a checksum; the repo has a threat model and security tests.
>
> Honest limits: the Notion, Sheets, Stripe, Shopify, GitHub and Trello connections are tested against realistic fakes, not every real account yet (`footnote doctor --live` checks yours, read-only). No Linear or Jira yet. Windows and macOS are newer targets than Linux. This is v0.1.0.
>
> Try it: `npx footnote-app` (needs Python 3.9+), or download `footnote.pyz` from the release page. Apache-2.0.
>
> What I'd most like to know: where did you get stuck in the first five minutes?
>
> https://github.com/Faiziimam/Footnote

---

## 2. Reddit (r/SideProject, r/selfhosted, r/ObsidianMD)

Adjust the opening line for each community, and read each community's self-promotion rules first.

**r/SideProject / r/selfhosted**

> **I got tired of stale trackers, so I built one that fills itself in (free, open source, runs locally)**
>
> Footnote watches your project (git commits, checklists in your docs, or you just typing "finished the brochure, started packaging") and keeps your tracker up to date. It syncs both ways with Notion, Google Sheets, Excel/CSV, SQLite, GitHub Issues and Trello. It also keeps an architecture map, a decisions journal, business numbers and a team view, and can email a weekly report or build a PowerPoint.
>
> No account, no cloud, Python standard library only. `npx footnote-app` or a single `footnote.pyz` file.
>
> It's v0.1.0 and the real-service connections are tested against fakes so far, so I'd love to hear what breaks on your setup.
>
> Site and screenshots: https://faiziimam.github.io/Footnote/ · Source: https://github.com/Faiziimam/Footnote

**r/ObsidianMD** (lead with the vault)

> **A tracker that lives in your Obsidian vault and updates itself**
>
> Footnote writes each task as a markdown note with frontmatter (plus reports, an architecture map and a decisions journal), and keeps them current from git, your docs and plain-English updates. Edit a note and it flows back; your vault stays yours. Free, open source, local only. Looking for feedback from vault-heavy users on the note layout.

---

## 3. LinkedIn / X

> I built a project tracker that updates itself.
>
> You type "finished the logo, started the landing page", or mention T-004 in a commit, and the right tasks move. It keeps Notion, Google Sheets, Excel, Obsidian, GitHub Issues and Trello in sync, writes the weekly report, and can build the PowerPoint for your review.
>
> Free, open source, runs on your computer. No account.
>
> Try: `npx footnote-app`
> https://faiziimam.github.io/Footnote/

---

## 4. A short message to send people directly

> Hi [name], I just released a small open-source tool and I'd like an honest first reaction. It's a project tracker that updates itself from git and what you type. Would you try it for ten minutes on a real project and tell me where you got stuck? Instructions are here: https://github.com/Faiziimam/Footnote/blob/main/docs/launch/feedback-checklist.md . Rough edges are welcome; that's what I'm looking for.

---

## Before you post

- [ ] `npx footnote-app --help` works on a clean machine.
- [ ] The website loads, and the Download and GitHub links work.
- [ ] CI is green on `main`.
- [ ] You can reply to comments for the next two hours.
- [ ] You know how you'll triage reports: GitHub issues, using the "I got stuck" template (it adds the `usability` label).
- [ ] Don't ask for upvotes or stars in the post. Ask for feedback.
