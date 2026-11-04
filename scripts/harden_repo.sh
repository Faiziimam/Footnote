#!/usr/bin/env bash
# Applies the GitHub repository settings from docs/security-hardening.md using the GitHub CLI (`gh`).
# SAFE BY DEFAULT: prints what it would do. Add --apply to really do it. Needs admin rights on the repo.
# Usage:  scripts/harden_repo.sh Faiziimam/Footnote [--apply] [--branch main]
set -euo pipefail
REPO="${1:?usage: $0 Faiziimam/Footnote [--apply] [--branch main]}"; shift || true
APPLY=0; BRANCH=main
while [ $# -gt 0 ]; do case "$1" in --apply) APPLY=1;; --branch) BRANCH="$2"; shift;; *) echo "unknown option $1"; exit 2;; esac; shift; done
run() { echo "+ $*"; if [ "$APPLY" = 1 ]; then "$@"; fi; }

echo "Repository: $REPO   branch: $BRANCH   mode: $([ $APPLY = 1 ] && echo APPLY || echo 'DRY RUN (add --apply)')"

# Security features
run gh api -X PUT "repos/$REPO/vulnerability-alerts"
run gh api -X PUT "repos/$REPO/automated-security-fixes"
run gh api -X PUT "repos/$REPO/private-vulnerability-reporting"
run gh api -X PATCH "repos/$REPO" \
  -f 'security_and_analysis[secret_scanning][status]=enabled' \
  -f 'security_and_analysis[secret_scanning_push_protection][status]=enabled'

# Actions: read-only token by default, Actions may not approve PRs
run gh api -X PUT "repos/$REPO/actions/permissions/workflow" -f default_workflow_permissions=read -F can_approve_pull_request_reviews=false

# Branch protection. A pull request and passing checks are required. With ONE maintainer, GitHub does not let you approve your own pull request,
# so approvals are 0 and Code Owner review is off; raise both (1 and true) as soon as there is a second maintainer.
cat > /tmp/protection.json <<JSON
{
  "required_status_checks": {"strict": true, "contexts": ["test (ubuntu-latest, py3.9)", "test (ubuntu-latest, py3.13)", "security", "Analyze (python)"]},
  "enforce_admins": true,
  "required_pull_request_reviews": {"dismiss_stale_reviews": true, "require_code_owner_reviews": false, "required_approving_review_count": 0},
  "restrictions": null,
  "required_linear_history": true,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_conversation_resolution": true
}
JSON
run gh api -X PUT "repos/$REPO/branches/$BRANCH/protection" --input /tmp/protection.json
echo "Done. Still manual: 2FA for maintainers, signed commits, tag protection rules, allowed-Actions list (see docs/security-hardening.md)."
