# Repository hardening checklist (for maintainers)

Files in this repository enforce what they can (pinned Actions, least-privilege workflows, CodeQL, Scorecard, Dependabot,
pre-commit, reproducible releases). **These settings live on GitHub, not in files**, so someone with admin rights must apply them.
`scripts/harden_repo.sh` applies most of them (dry run by default; read it first).

## Account
- [ ] Two-factor authentication (hardware key or passkey) for every maintainer; require it for the organisation.
- [ ] Maintainers sign commits (SSH or GPG) and enable "Vigilant mode".

## Branch protection on `main` (a ruleset also works)
- [ ] Require a pull request; at least 1 approval; dismiss stale approvals; require review from Code Owners.
- [ ] Require status checks: `test (ubuntu-latest, py3.9)` … `py3.13`, `security`, `CodeQL`.
- [ ] Require branches to be up to date; require conversation resolution; require linear history.
- [ ] Block force pushes and deletions; include administrators.
- [ ] Protect release tags (`v*`) so only maintainers can create them.

## Security features
- [ ] Private vulnerability reporting **on** (SECURITY.md relies on it).
- [ ] Dependency graph + Dependabot alerts + Dependabot security updates **on**.
- [ ] Secret scanning **and push protection** on.
- [ ] Code scanning (CodeQL workflow included) on.

## Actions
- [ ] Default workflow token permission: **read-only**; don't allow Actions to approve pull requests.
- [ ] Allow only GitHub-owned and explicitly listed Actions; require full-length commit SHAs for third-party ones.
- [ ] Require approval for workflows from first-time contributors / outside collaborators.
- [ ] Use an `environment` with required reviewers for releases if you add publishing secrets (the current release workflow uses none).

## Releases
- [ ] Tag, let `release.yml` build; confirm the attached SHA-256 equals a local rebuild (`python build_pyz.py`).
- [ ] Verify the attestation: `gh attestation verify footnote.pyz --repo Faiziimam/Footnote`.

## Ongoing
- Review Dependabot PRs for Actions weekly. Re-run `bandit -r footnote` and the security tests before every release.
- Keep `SECURITY.md` contact path working; rehearse once per year.
