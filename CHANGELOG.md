# Changelog
All notable changes. Format based on "Keep a Changelog"; versions follow semantic versioning once 1.0 ships.

## Unreleased
### Added
- Reports by email (daily / weekly / monthly), with an optional PowerPoint deck and HTML copy attached; `footnote deck`.
- Read-only web view (`footnote ui --read-only`).
- Security: threat model, SECURITY.md, hardening checklist/script, CodeQL, Scorecard, pinned Actions, reproducible and attested releases.
- A website (`site/`) and community files (contributing guide, code of conduct, issue/PR templates).

### Security
- Local web page: per-request-nonce CSP, Origin/Host checks, body limits, brute-force lockout, constant-time token compare.
- Task IDs and field names from shared trackers are validated (path traversal, SQL injection); text from outside is cleaned.
- Outbound requests: http(s) only, no credentials over cleartext, credentials dropped on cross-host redirects, reply size cap, secret redaction.
- Output returned to AI tools is labelled as untrusted data.

### Fixed
- Python 3.9–3.11 compatibility (nested f-strings, timestamps ending in `Z`).
- The single-file installer now preserves exit codes and builds byte-identically.

## Renamed
- The product is now **Footnote** (command `footnote`, file `footnote.pyz`, settings folder `.footnote/`, environment variables `FOOTNOTE_*`). It was called "autotracker" in early builds; the old settings folder, instruction blocks, MCP entry and hooks are migrated automatically.
