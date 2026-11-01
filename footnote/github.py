"""GitHub signals: pull requests -> task states, reviews -> team visibility, CI -> health. Opt-in (needs a token).

Read-only. Token: config `token`, env GITHUB_TOKEN, or the `gh` CLI if you are already logged in.
"""
import datetime as dt
import json
import os
import re
import shutil
import subprocess  # nosec B404
from pathlib import Path
from . import config
from .mirrors.http import call
from .mirrors.base import MirrorError
from .signals import ID, CLOSING, _git

API = "https://api.github.com"


def repo_from_remote(project):
    url = _git(project, "remote", "get-url", "origin").strip()
    m = re.search(r"github\.com[:/]([^/\s]+/[^/\s]+?)(?:\.git)?$", url)
    return m.group(1) if m else ""


def token(item):
    t = config.secret(item, default_env="GITHUB_TOKEN")
    if not t and shutil.which("gh"):
        try:
            t = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, encoding="utf-8",  # nosec B603 B607
                               errors="replace", timeout=10).stdout.strip()
        except Exception:
            t = ""
    return t


def _get(item, path, tok):
    base = (item.get("base_url") or API).rstrip("/")
    return call("GET", base + path, {"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json",
                                     "X-GitHub-Api-Version": "2022-11-28"}, retries=2, timeout=15)


def ping(item, project):
    tok = token(item)
    if not tok:
        raise MirrorError("GitHub: no token. Set GITHUB_TOKEN (read-only 'Pull requests' + 'Checks' access) or log in with `gh auth login`")
    repo = item.get("repo") or repo_from_remote(project)
    if not repo:
        raise MirrorError("GitHub: couldn't tell which repository this is; add --opt repo=owner/name")
    _get(item, f"/repos/{repo}", tok)
    return f"connected to {repo} (read-only)"


def fetch(item, project, days=60):
    """-> {"prs": [...], "ci": {...}, "events": [(when, id, state, why)], "repo": "o/r"}"""
    tok = token(item)
    repo = item.get("repo") or repo_from_remote(project)
    if not tok or not repo:
        raise MirrorError("GitHub: token or repository missing (run: footnote doctor --live)")
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    prs = []
    for p in _get(item, f"/repos/{repo}/pulls?state=all&sort=updated&direction=desc&per_page=40", tok):
        upd = dt.datetime.fromisoformat(p["updated_at"].replace("Z", "+00:00"))
        if upd < since:
            continue
        reviews = []
        if upd > dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30) and len(prs) < 25:
            try:
                reviews = [{"user": r["user"]["login"], "state": r["state"], "at": r.get("submitted_at", "")}
                           for r in _get(item, f"/repos/{repo}/pulls/{p['number']}/reviews", tok) if r.get("user")]
            except MirrorError:
                pass
        prs.append({"number": p["number"], "title": p["title"], "body": p.get("body") or "", "state": p["state"],
                    "draft": bool(p.get("draft")), "merged": bool(p.get("merged_at")), "merged_at": p.get("merged_at") or "",
                    "user": (p.get("user") or {}).get("login", ""), "created_at": p["created_at"], "updated_at": p["updated_at"],
                    "branch": (p.get("head") or {}).get("ref", ""), "url": p.get("html_url", ""),
                    "reviewers": [r["login"] for r in p.get("requested_reviewers", [])], "reviews": reviews})
    ci = {"state": "unknown", "failing": [], "branch": ""}
    try:
        info = _get(item, f"/repos/{repo}", tok)
        branch = info.get("default_branch", "main")
        runs = _get(item, f"/repos/{repo}/commits/{branch}/check-runs?per_page=50", tok).get("check_runs", [])
        bad = sorted({r["name"] for r in runs if r.get("conclusion") in ("failure", "timed_out", "cancelled", "action_required")})
        pending = any(r.get("status") != "completed" for r in runs)
        ci = {"state": "failing" if bad else ("running" if pending else ("passing" if runs else "unknown")),
              "failing": bad, "branch": branch}
    except MirrorError:
        pass
    events = []
    for p in prs:
        text = f"{p['title']}\n{p['body']}\n{p['branch']}"
        ids = {i.upper() for i in ID.findall(text)}
        closing = bool(CLOSING.search(p["title"] + "\n" + p["body"]))
        for tid in ids:
            if p["merged"]:
                events.append((p["merged_at"], tid, "done" if closing or ID.search(p["title"]) else "active",
                               f"PR #{p['number']} merged"))
            elif p["state"] == "open" and not p["draft"]:
                events.append((p["created_at"], tid, "active", f"PR #{p['number']} opened"))
            elif p["state"] == "open":
                events.append((p["created_at"], tid, "active", f"draft PR #{p['number']}"))
    return {"prs": prs, "ci": ci, "events": sorted(events), "repo": repo,
            "fetched": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}


def save(vault, data):
    from .store import atomic_write
    keep = {k: v for k, v in data.items() if k != "events"}
    atomic_write(Path(vault) / "_github.json", json.dumps(keep, indent=1))


def load(vault):
    try:
        return json.loads((Path(vault) / "_github.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def review_counts(gh, people):
    """{person_key: reviews given in the data window}. Matches GitHub logins to people by email/name."""
    out = {}
    if not gh:
        return out
    def match(login):
        l = login.lower()
        for k, p in people.items():
            if k == f"{l}@github" or k.split("@")[0] == l or l in p["name"].lower().replace(" ", ""):
                return k
        return None
    for pr in gh["prs"]:
        for r in pr["reviews"]:
            k = match(r["user"])
            if k and r["user"] != pr["user"]:
                out[k] = out.get(k, 0) + 1
    return out


def waiting_prs(gh, now=None, min_days=2):
    """Open, non-draft PRs nobody has reviewed for a while."""
    now = now or dt.datetime.now(dt.timezone.utc)
    out = []
    for p in (gh or {}).get("prs", []):
        if p["state"] == "open" and not p["draft"]:
            age = (now - dt.datetime.fromisoformat(p["created_at"].replace("Z", "+00:00"))).days
            changes = any(r["state"] == "CHANGES_REQUESTED" for r in p["reviews"])
            approved = any(r["state"] == "APPROVED" for r in p["reviews"]) and not changes
            if changes or (age >= min_days and not p["reviews"]):
                out.append({"number": p["number"], "title": p["title"], "user": p["user"], "age": age,
                            "state": "changes requested" if changes else "no review yet", "url": p["url"]})
            elif approved and age >= min_days:
                out.append({"number": p["number"], "title": p["title"], "user": p["user"], "age": age,
                            "state": "approved, not merged", "url": p["url"]})
    return out
