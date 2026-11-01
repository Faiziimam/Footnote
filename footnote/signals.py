"""Evidence of work, read from git. Produces chronological (task_id, state, when, why) events."""
import re
import subprocess  # nosec B404
ID = re.compile(r"\bT-\d{3,}\b", re.I)
CLOSING = re.compile(r"\b(close[sd]?|fix(?:e[sd])?|resolve[sd]?|done|complete[sd]?|finish(?:e[sd])?)\b", re.I)
WORD = re.compile(r"[a-z0-9]{3,}")


def _git(project, *args):
    try:
        r = subprocess.run(["git", "-C", str(project), *args], capture_output=True,  # nosec B603 B607
                           text=True, timeout=30, encoding="utf-8", errors="replace")
        return r.stdout if r.returncode == 0 else ""
    except Exception:
        return ""


def tokens(s):
    return set(WORD.findall(s.lower()))


def similarity(a, b):
    ta, tb = tokens(a), tokens(b)
    return len(ta & tb) / len(tb) if tb else 0.0  # how much of the task title the commit covers


def git_events(project, tasks):
    """tasks: {id: frontmatter}. Returns sorted list of (when, id, state, reason)."""
    log = _git(project, "log", "--reverse", "--pretty=format:%H%x1f%aI%x1f%s%x1f%b%x1e")
    events = []
    for rec in filter(None, log.split("\x1e")):
        parts = rec.strip("\n").split("\x1f")
        if len(parts) < 4:
            continue
        sha, when, subj, body = parts[0], parts[1], parts[2], parts[3]
        text = f"{subj}\n{body}"
        is_merge = subj.lower().startswith("merge")
        hit = set()
        for tid in ID.findall(text):
            tid = tid.upper()
            if tid in tasks:
                closing = bool(CLOSING.search(text)) or is_merge
                events.append((when, tid, "done" if closing else "active",
                               f"commit {sha[:7]}: {subj}"))
                hit.add(tid)
        if is_merge:
            continue
        # no explicit id: fuzzy-match the commit subject to a task title
        for tid, fm in tasks.items():
            if tid in hit or fm.get("status") == "done":
                continue
            title = fm["title"].replace("Implement:", "")
            if similarity(subj, title) >= 0.7:
                state = "done" if CLOSING.search(subj) else "active"
                events.append((when, tid, state, f"commit {sha[:7]} ~ title: {subj}"))
    # branch names mentioning an id => active (work in progress, not yet committed)
    cur = _git(project, "rev-parse", "--abbrev-ref", "HEAD").strip()
    when = _git(project, "log", "-1", "--format=%aI").strip()
    for tid in ID.findall(cur):
        if tid.upper() in tasks:
            events.append((when, tid.upper(), "active", f"on branch {cur}"))
    return sorted(events)


def git_relations(project, tasks):
    """Commits that mention two or more task ids relate those tasks. -> [(a, b, reason)]"""
    log = _git(project, "log", "--reverse", "--pretty=format:%H%x1f%s%x1f%b%x1e")
    out = []
    for rec in filter(None, log.split("\x1e")):
        parts = rec.strip("\n").split("\x1f")
        if len(parts) < 3 or parts[1].lower().startswith("merge"):
            continue
        ids = sorted({t.upper() for t in ID.findall(parts[1] + "\n" + parts[2])} & set(tasks))
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                out.append((a, b, f"commit {parts[0][:7]} touches both"))
    return out


CO_AUTHOR = re.compile(r"^co-authored-by:\s*(.+?)\s*<", re.I | re.M)
AI_NAMES = re.compile(r"claude|copilot|cursor|codex|gemini|chatgpt|openai|devin|aider|\bai\b", re.I)


def git_history(project, extra_repos=(), limit=3000):
    """Every commit, newest last, from this repo (+ any extra repos). -> list of dicts."""
    from pathlib import Path
    out = []
    for repo in [Path(project), *[Path(project) / r if not Path(r).is_absolute() else Path(r) for r in extra_repos]]:
        log = _git(repo, "log", f"-{limit}", "--reverse", "--name-only",
                   "--pretty=format:%x1e%H%x1f%aI%x1f%an%x1f%ae%x1f%s%x1f%b%x1f")
        for rec in filter(None, log.split("\x1e")):
            parts = rec.split("\x1f")
            if len(parts) < 7:
                continue
            sha, when, an, ae, subj, body, files = parts[:7]
            out.append({"sha": sha, "when": when, "author": an, "email": ae.lower(), "subject": subj,
                        "body": body, "repo": repo.name,
                        "files": [f for f in files.strip().splitlines() if f.strip()],
                        "merge": subj.lower().startswith("merge"),
                        "ai": any(AI_NAMES.search(c) for c in CO_AUTHOR.findall(body))})
    out.sort(key=lambda c: c["when"])
    return out
