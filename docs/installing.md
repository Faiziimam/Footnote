# Installing

**Easiest (one file, no pip):** download or build `footnote.pyz` (`python build_pyz.py` → `dist/footnote.pyz`), put it in
your project folder and run `python footnote.pyz` — it asks a few plain questions. Needs Python 3.9+ only.
`connect`, `install-hook` and the web page all work from that single file.

**With npm (if you already use Node):** `npx footnote-app` runs it without installing anything; `npm install -g footnote-app` then `footnote`
installs it. This is a tiny launcher around the same one-file program. It **still needs Python 3.9+ on the computer** (there are no Python *packages* to
install, only Python itself, and the launcher tells you plainly if it is missing). It has no dependencies and no install scripts. Using it with an AI tool:
`npx footnote-app connect claude`.

**With pip:** `pip install /path/to/footnote` then `footnote`.

**No terminal at all:** double-click `Start Tracker.command` (Mac/Linux) or `start-tracker.bat` (Windows) in your project folder.

Something wrong? `footnote doctor` explains in plain words; `footnote doctor --live` also tests Notion/Sheets/Stripe/GitHub
(read-only); `footnote log` shows what happened recently; `footnote undo` reverses the last change (yours or automatic).
