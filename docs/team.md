# Working as a team (or with several AI agents)

**What you get, automatically, from commit history — no one has to fill anything in:**
- `Team.md` and `People/<name>.md`: what each person has been doing, in plain words ("3 commits in the last 7 days, mostly in `app/cart` — 2 new things, 1 fix"), which tasks they own, and which parts of the project they know best.
- **Task owners:** the person who made the most commits for a task becomes its owner (assign by hand any time: `footnote assign T-004 alice` — your choice is never overwritten).
- **Heads-ups:** two people changing the same files in the last 14 days; in-progress tasks with no activity for 7+ days; areas only one person has touched (so you can pair or document).
- **Catch-up:** `footnote catchup` shows what changed since *you* last looked (tasks finished/started, what each person did, decisions, new risks, architecture changes). `--since 3d` for a fixed window.
- **Who knows about X?** `footnote whois checkout/` (or a person, or `T-004`). AI agents use the same thing (`tracker_whois`, `tracker_catchup`) to avoid stepping on a teammate.

**Sharing one tracker:** connect everyone to the same Notion database or Google Sheet (`footnote add-tracker notion`).
Tasks a teammate adds appear on your side with the same ID; edits made by anyone are merged cell by cell.
Keep `Tracker/` out of git (it is regenerated locally). If two people create a task at the exact same second you may
get a duplicate; it is harmless, merge them by hand.

**Several repos / teams:** `footnote add-repo ../api` includes another repository's history.
**Merging identities / grouping:** in `.footnote/config.json` add
`"team": {"aliases": {"alice.personal@gmail.com": "alice@work.com"}, "groups": {"Frontend": ["alice@work.com"]}, "ignore": ["ci@work.com"]}`.
Bots (dependabot, renovate, GitHub Actions) are ignored automatically.

**On purpose, there is no leaderboard.** Commit counts say little about value; this is for visibility and handoffs.
