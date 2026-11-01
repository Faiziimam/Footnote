"""Activity for projects WITHOUT git (design folders, marketing docs, spreadsheets...): notice which files changed.

Compares a snapshot of file sizes/times between syncs. A task whose ID appears in a changed file's path
(e.g. 'T-004-brochure.pdf') is marked In progress. Used automatically when the folder is not a git repo.
"""
import json
import time
from pathlib import Path
from . import config
from .architecture import SKIP
from .signals import ID, _git
from .store import atomic_write, now, iso

MAX_FILES = 20_000
FILE = "_activity.jsonl"


def uses_activity(project, cfg):
    if "activity" in cfg:
        return bool(cfg["activity"])
    return _git(project, "rev-parse", "--is-inside-work-tree").strip() != "true"


def _ignored_names(project, cfg):
    names = {".mcp.json", "CLAUDE.md", "AGENTS.md", "GEMINI.md", ".windsurfrules"}
    for m in cfg.get("mirrors", []):
        if m.get("type") in ("csv", "excel"):
            names.add(Path(m.get("path") or "Tracker.csv").name)
        if m.get("type") == "sqlite":
            names.add(Path(m.get("path") or "tracker.db").name)
    return names


def scan(project, vault, cfg):
    root, vault = Path(project), Path(vault).resolve()
    skip_names = _ignored_names(project, cfg)
    out, stack = {}, [root]
    while stack and len(out) < MAX_FILES:
        d = stack.pop()
        try:
            entries = list(d.iterdir())
        except OSError:
            continue
        for p in entries:
            if p.name in SKIP or p.name.startswith(".") or p.name in skip_names or p.resolve() == vault:
                continue
            if p.is_dir():
                stack.append(p)
            else:
                try:
                    st = p.stat()
                    out[p.relative_to(root).as_posix()] = [int(st.st_mtime), st.st_size]
                except OSError:
                    pass
    return out


def record(project, vault, cfg):
    """-> (change_summary | None, events[(when, task_id, 'active', why)])"""
    snap_p = config.dir_for(project) / "files.json"
    cur = scan(project, vault, cfg)
    try:
        prev = json.loads(snap_p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        prev = None
    snap_p.parent.mkdir(exist_ok=True)
    atomic_write(snap_p, json.dumps(cur))
    if prev is None:
        return None, []
    added = sorted(set(cur) - set(prev))
    deleted = sorted(set(prev) - set(cur))
    modified = sorted(p for p in cur if p in prev and cur[p] != prev[p])
    if not (added or deleted or modified):
        return None, []
    touched = added + modified
    areas = {}
    for p in touched + deleted:
        a = p.split("/")[0] if "/" in p else "(top level)"
        areas[a] = areas.get(a, 0) + 1
    entry = {"ts": iso(now()), "added": len(added), "modified": len(modified), "deleted": len(deleted),
             "areas": sorted(areas, key=lambda k: -areas[k])[:3], "sample": touched[:4] or deleted[:4]}
    with open(Path(vault) / FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    events = [(entry["ts"], t.upper(), "active", f"file changed: {p}") for p in touched for t in ID.findall(p)]
    return entry, events


def read(vault):
    p = Path(vault) / FILE
    out = []
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out
