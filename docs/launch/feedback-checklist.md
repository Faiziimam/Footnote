# Try Footnote: a 10-minute feedback checklist

Thank you for trying it. You can't do this wrong: **where you got stuck is the most useful thing you can tell us.**
Don't fix things quietly or work around them; just note what happened.

You need Python 3.9 or newer. Pick a **real** project (a folder you actually work in), not an empty one.
Everything stays on your computer.

## Before you start (1 minute)

Write down: your system (Windows, Mac or Linux), whether you use git, and which tools you use (Notion, Sheets, Excel, Obsidian, an AI assistant…).

## The steps

Tick each box. After each one, note anything that confused you, took long, or felt wrong.

1. **Install it.** In your project folder run `npx footnote-app`, or download `footnote.pyz` from the [latest release](https://github.com/Faiziimam/Footnote/releases/latest) and run `python footnote.pyz`.
   - [ ] It started without errors. How long did it take? ____
2. **Answer the setup questions.**
   - [ ] The questions made sense.
   - [ ] I knew what to choose, or I guessed. (Which one? ____ )
3. **Open it.** Run `footnote ui` (or `python footnote.pyz ui`).
   - [ ] The page opened and showed tasks that matched my project.
   - [ ] Anything missing or strange? ____
4. **Tell it something.** In the box, type what you really did today, in your own words.
   - [ ] The right task moved, or it asked me a sensible question.
   - [ ] If it got it wrong, I could undo it (`footnote undo`).
5. **Add a task** in the page, then **refresh**.
   - [ ] It showed up where I expected.
6. **If you use git:** make a commit that mentions a task ID (for example `T-001`), then run `footnote sync`.
   - [ ] The task moved.
7. **Open the report.** Run `footnote report --for manager --html report.html` and open the file.
   - [ ] I could understand it without explanation.
   - [ ] I would show this to someone else. (Who? ____ )
8. **Optional: connect a tool** you already use (`footnote add-tracker notion`, `gsheets`, `csv`, `sqlite`, or `footnote connect <your AI tool>`).
   - [ ] I got it connected. How long did it take? ____
   - [ ] Changes made in that tool showed up in Footnote, and the other way round.

## Five questions

1. In one sentence, what is this for? (Your words, not ours.)
2. What was the **first** thing that confused or annoyed you?
3. Was there a moment you thought "oh, that's useful"? What was it?
4. Is there anything you expected it to do that it didn't?
5. Would you keep using it next week? Why, or why not?

## If something breaks

Run `footnote doctor` and `footnote log`. They explain problems in plain words and scrub secrets. Paste the output into your report.
Please **don't** paste tokens, passwords or private project details. If unsure, describe the problem instead.

## How to send it

Any of these is fine:
- Open an issue: https://github.com/Faiziimam/Footnote/issues/new/choose (pick "I got stuck / something confused me").
- Reply to whoever sent you this link, with the checklist filled in.

If you found a security problem, please don't post it publicly. Report it privately here:
https://github.com/Faiziimam/Footnote/security/advisories/new
