# 3. Everything that arrives from outside is untrusted

Status: accepted

## Decision
Task text, IDs, field names, commit messages, PR/issue titles, webhook payloads, rows in shared trackers and files in other people's
repositories are treated as hostile until cleaned: validated IDs, capped sizes, control characters removed, escaped on output (HTML,
XML, SQL, Markdown), and labelled as *data, not instructions* when handed to an AI tool.

## Why
Footnote mixes content from many authors and feeds it to humans, browsers, spreadsheets and AI agents. Each of those is an
injection target. One central rule is easier to keep correct than many local ones; `tests/test_security.py` enforces it by attacking.
