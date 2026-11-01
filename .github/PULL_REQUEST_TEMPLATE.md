## What and why
<!-- What does this change, and what problem does it solve for users? Link the issue. -->

## How I checked it
- [ ] I added or updated tests (for a security fix: an attack test in `tests/test_security.py`)
- [ ] `python -m unittest discover -s tests -t .` passes
- [ ] I considered Python 3.9 (no `match`, no `X | Y` types, no nested same-quote f-strings)

## Safety checklist (see CONTRIBUTING.md)
- [ ] No new runtime dependency
- [ ] No `shell=True` / `eval` / `exec` / `pickle`; network only via `mirrors/http.py:call`
- [ ] Input from outside is validated, cleaned and escaped on output
- [ ] No secret in code, tests, logs or screenshots
- [ ] User-facing text is plain and honest (nothing invented; limits stated)

## Notes for the reviewer
<!-- Anything unusual, trade-offs, follow-ups. -->
