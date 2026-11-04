# Footnote (npm)

A project tracker that keeps itself up to date. This package is the easy way to get it if you already use Node.

```bash
npx footnote-app            # first run: a few plain questions
npx footnote-app ui         # open it in your browser
npm install -g footnote-app # or install once, then just:  footnote
```

## What this package is (and isn't)
- It is a tiny launcher plus the Footnote program. **It needs Python 3.9 or newer on your computer** (most Macs and Linux machines have it;
  on Windows: `winget install Python.Python.3.12`). There are **no Python packages to install**: Footnote only uses Python itself.
- It has **no dependencies** and **no install scripts**: installing it runs nothing. When you run it, it checks the bundled program against its
  checksum, finds Python, and passes your arguments straight through (no shell, so nothing you type is reinterpreted).
- Using it with an AI tool: `npx footnote-app connect claude` writes the right setup for your project.
- Python not in the usual place? Set `FOOTNOTE_PYTHON` to its full path.

Website: https://faiziimam.github.io/Footnote/

Full documentation, security policy and source: https://github.com/Faiziimam/Footnote
