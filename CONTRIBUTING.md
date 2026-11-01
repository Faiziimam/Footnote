# Contributing to Footnote

Thank you! This project is for **everyone who tracks work**: founders, designers, developers, managers, shop owners. You do not
need to be a programmer to help, and there are many ways to contribute.

## Ways to help (no code needed)
- **Tell us where it confused you.** Open an issue using the "I got stuck" template; screenshots welcome. Confusing wording is a bug.
- **Share a recipe**: how you use it day to day (a bakery, a podcast, a research project). Add it to `site/` or `docs/recipes.md`.
- **Improve the words.** Plain, friendly language is a feature. Fix typos, simplify sentences, translate.
- **Test on your system** (Windows, macOS, Linux; Python 3.9–3.13) and tell us what happened (`footnote doctor` output helps).
- **Report a security problem**: privately, see [SECURITY.md](SECURITY.md).

## Ways to help (code)
```bash
git clone <your fork> && cd footnote
python -m unittest discover -s tests -t .      # ~1 minute; needs git. No installs: there are no dependencies.
python build_pyz.py                            # builds dist/footnote.pyz
```
Optional extras for development only: `pip install bandit python-pptx` (security scan and a deck double-check; tests skip what is missing).

### Where things live
| You want to… | Look at |
|---|---|
| Add a connected tool (Linear, Jira, Asana, Airtable…) | `footnote/mirrors/`: copy `issues.py` (`PrefixedMirror`) or `csvm.py`; register it in `mirrors/__init__.py` and `setup.py` |
| Add a source of numbers (a shop, a payment provider) | `footnote/metrics.py` (`stripe_pull`, `shopify_pull`…); register in `PULLS`/`PINGS` |
| Add a signal (what counts as "started"/"done") | `footnote/signals.py`, `github.py`, `activity.py`; merge in `engine.py` |
| Add a project type template | `footnote/profiles.py` (pure data) |
| Add a plain-English phrase | `footnote/nl.py` (and a test in `tests/test_p0.py::PlainEnglishEdgeCases`) |
| Change what a report/deck says | `footnote/report.py`, `deck.py` |
| Add a framework to the architecture scan | `footnote/architecture.py` |

### The rules that keep users safe (please read — a test enforces most of them)
1. **No new runtime dependencies.** Standard library only (ADR 0002). Dev-only tools are fine.
2. **No `shell=True`, `eval`, `exec`, `pickle`, `os.system`.** Subprocesses take fixed argument lists.
3. **All network calls go through `mirrors/http.py:call`** (it enforces http(s), no cleartext credentials, redirect safety, size caps, redaction).
4. **Text from outside is hostile** (ADR 0003): validate IDs, clean and cap text, escape on output, label it untrusted for AI tools.
5. **Never log or print a secret.** Use `security.redact`. Never put real tokens in tests (use obvious fakes).
6. **Every read-modify-write holds the lock** (`Tracker._lock()`); files are written with `atomic_write`; always pass `encoding="utf-8"`.
7. **Works on Python 3.9.** No `match`, no `X | Y` types, no nested same-quote f-strings, no backslashes inside f-string braces. CI runs 3.9–3.13.
8. **Be honest in the UI.** If something wasn't verified or can't be known (e.g. sales numbers), say so; never invent data.

### Pull requests
- Small and focused beats big. Explain the *why*; link the issue.
- **Add a test that fails without your change.** For a security fix, add an attack test to `tests/test_security.py`.
- Run the full suite and (if you can) `bandit -r footnote` before opening the PR. CI will run both.
- Add a line to `CHANGELOG.md` under "Unreleased".
- **Licence:** the project is Apache-2.0. As the licence itself says (section 5), anything you contribute is licensed the same way unless you state otherwise. Please also sign off your commits (`git commit -s`): that adds a line saying you wrote the change or have the right to submit it (the Developer Certificate of Origin, developercertificate.org).

### Testing external services honestly
We test integrations against small fake servers in `tests/` (they are not the real services). If you have a real account, run
`footnote doctor --live` and tell us what differs. Fixes that make the fakes more faithful to the real API are very welcome.

## Behaviour
Be kind and assume good intent. See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
