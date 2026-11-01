# 1. Footnote runs on the user's device; there is no hosted service

Status: accepted

## Context
Teams asked for logins, roles and a hosted team version. A hosted service means accounts, passwords, stored customer data, uptime,
billing, privacy law, and a permanent target for attackers.

## Decision
We will run **entirely on the user's own computer**. We operate no server and hold no user data. Team sharing happens through tools
people already trust and already control access to (Notion, Google Sheets, GitHub, Trello, git), which have their own logins and
permissions. The only "role" we provide is a **read-only view** (`footnote ui --read-only`) for showing the tracker to someone else.

## Consequences
- No account system to build, secure or leak. Privacy is simple: data never leaves the computer except to services the user connects.
- "Who may see/edit what" is decided in the shared tool, not in ours.
- No central dashboard across companies, no push notifications from us, no usage analytics. We accept that.
- Revisit only if a clear need appears that shared tools cannot meet; it would be a separate, opt-in product.
