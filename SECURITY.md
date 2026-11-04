# Security

Footnote runs **on your own computer**. There is no account, no server of ours, and no data sent to us. That removes a whole
class of risk, but the tool still reads your project files, can talk to services you connect (Notion, GitHub, Stripe…), and is
used by AI tools, so we treat security seriously.

## Reporting a vulnerability

**Please do not open a public issue.** Use the repository's **Security → "Report a vulnerability"** button (GitHub private
vulnerability reporting). Include what you did, what you expected, what happened, and the version
(`python footnote.pyz --help` or the release tag).

What you can expect (our targets — we are volunteers, so these are goals rather than guarantees):

| Step | Target |
|---|---|
| Acknowledge your report | within 3 working days |
| Confirm and rate the severity | within 7 days |
| Fix or mitigation for high/critical | within 30 days |
| Public advisory + credit (if you want it) | when the fix is released |

We will not take legal action against people who test in good faith, stay within their own accounts and data, don't degrade
others' service, and give us reasonable time to fix before disclosing. There is no bug bounty.

## What is in scope

Anything that lets an attacker, **without already controlling your account or your computer**, do one of these:
run code or commands through Footnote · read or write files outside the project folder · steal a token or secret · make the
local web page or relay act on their behalf (CSRF, DNS rebinding, XSS, auth bypass) · crash or corrupt your tracker with
crafted input (from a webhook, a shared Notion/Sheet/GitHub row, a commit message, a file in a repository) · trick an AI tool
into acting on text it received through the tracker (prompt injection through our tools' output).

Out of scope: problems that need an attacker who already has full control of your computer or of the service you connected;
vulnerabilities in Python, git, Notion, Slack etc. themselves; social engineering; denial of service by sending enormous amounts
of traffic to a relay you chose to host.

## How it is built (summary — details in [docs/threat-model.md](docs/threat-model.md))

- **No runtime dependencies.** Only the Python standard library, so there is no third-party package that can be hijacked. A test
  fails if anyone adds one.
- **Local only by default.** The web page binds to `127.0.0.1`, needs a secret token, checks the `Host` and `Origin` headers,
  sends a strict Content-Security-Policy (no inline script without a per-request nonce), limits request size, locks out
  guessing, and has a `--read-only` mode for screen sharing.
- **Untrusted input is cleaned at the door.** Task IDs from outside must look like `T-123`; field names are validated; text is
  stripped of control characters; sizes are capped; SQL identifiers are quoted; formulas are parsed into a safe subset (no
  code execution).
- **Outbound calls go through one function** that allows only `http(s)`, refuses to send credentials over plain `http://`, never
  forwards credentials on a redirect to another host, caps reply sizes, and redacts secrets from every log line and warning.
- **No shell.** Subprocesses use fixed argument lists; `shell=True`, `eval`, `exec`, `pickle` are forbidden by a test.
- **Secrets stay private.** Tokens live in `.footnote/config.json` (mode 600, git-ignored) or environment variables; prefer
  environment variables. `footnote doctor` warns about loose permissions.
- **AI-tool safety.** Text coming back to an AI tool (task titles, PR titles, commit messages) is labelled as untrusted data, and
  the agent instructions tell it never to follow commands found inside it.
- **Releases you can verify.** `footnote.pyz` is built **reproducibly**: rebuilding the same source gives the same bytes. Each
  release publishes a SHA-256 and a signed build-provenance attestation.

## The npm package

`footnote-app` on npm contains only a ~60-line launcher plus the same `footnote.pyz` as the release (its SHA-256 is checked every time it runs). It has **no dependencies and no install scripts**, so installing it executes nothing; running it starts Python with your arguments passed straight through (no shell). `tests/test_npm.py` enforces all of this.

## Verifying a download

```bash
# 1. the checksum matches
sha256sum -c footnote.pyz.sha256
# 2. it was built by this repository's release workflow (GitHub CLI)
gh attestation verify footnote.pyz --repo Faiziimam/Footnote
# 3. (optional) rebuild it yourself from the tagged source and compare
git checkout vX.Y.Z && python build_pyz.py dist && sha256sum dist/footnote.pyz
```

## Staying safe as a user

- Keep tokens in environment variables (`NOTION_TOKEN`, `GITHUB_TOKEN`, …) rather than the settings file when you can.
- Give each token the **least access** it needs: read-only for Stripe/Shopify/GitHub; Notion access to one page only.
- Before approving an `.mcp.json` that came from a repository you didn't write, read it — it names a program that will run.
- Host the relay only behind HTTPS, and never publish its PULL token.
- Run `footnote doctor` after setup and after upgrades.
- No software is perfectly secure. If something here looks wrong to you, tell us.
