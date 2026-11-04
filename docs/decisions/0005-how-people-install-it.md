# 5. How people install Footnote

Status: accepted

## Context
Footnote is written in Python with **no third-party packages**. The only thing a computer needs is Python 3.9+. Some people (especially
users of AI coding tools, which are mostly installed with npm) find `npx` easier than Python tooling.

## Decision
Offer several routes that all run the **same, reproducibly built `footnote.pyz`**:
1. the single file (`python footnote.pyz`),
2. pip (`footnote-app`),
3. npm (`npx footnote-app`, `npm install -g footnote-app`): a tiny launcher that bundles `footnote.pyz`, verifies its checksum, finds Python and
   runs it. No dependencies, no install scripts, no shell. It does **not** remove the need for Python.

## Not decided / later
A route with **no Python at all** means shipping native programs (PyInstaller/Nuitka) per operating system, signing/notarising them (macOS and
Windows warn about unsigned programs), keeping builds reproducible, and then offering them through GitHub Releases, Homebrew, winget and
per-platform npm packages. That is real, ongoing work and security surface, so it waits until real users show it is the blocker.

## Consequences
Every route has the same code and the same checksum; npm adds only the launcher. We say plainly everywhere that Python 3.9+ is required.
