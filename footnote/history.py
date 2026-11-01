"""Undo. Before anything changes the tracker's own data, a compressed snapshot of it is kept (last 100).

`undo` steps back one state and makes it STICK: tasks it reverted are locked (so automation cannot just redo
the change from the same commit) and tasks it removed are remembered (so the docs scan cannot re-create them).
"""
import gzip
import hashlib
import json
import re
import time
from pathlib import Path
from . import config
from .store import now, iso, parse_frontmatter, atomic_write

KEEP = 100
TOP = ("_schema.json", "_journal.jsonl", "_metrics.jsonl", "_project.json", "_ignored.json")


def _dir(project):
    d = config.dir_for(project) / "history"
    d.mkdir(parents=True, exist_ok=True)
    return d


def bundle(vault):
    vault = Path(vault)
    files = {}
    for name in TOP:
        p = vault / name
        if p.exists():
            files[name] = p.read_text(encoding="utf-8")
    for p in sorted((vault / "Tasks").glob("T-*.md")):
        files[f"Tasks/{p.name}"] = p.read_text(encoding="utf-8")
    return files


def digest(files):
    h = hashlib.sha1(usedforsecurity=False)  # a content fingerprint, not a security measure
    for k in sorted(files):
        h.update(k.encode()); h.update(b"\0"); h.update(files[k].encode()); h.update(b"\1")
    return h.hexdigest()[:12]


def _list(project):
    out = []
    for p in sorted(_dir(project).glob("*.json.gz")):
        try:
            with gzip.open(p, "rt", encoding="utf-8") as f:
                m = json.load(f)
            out.append((p, m))
        except (OSError, ValueError):
            continue
    return out


def snapshot(project, vault, label, relabel=False):
    files = bundle(vault)
    if "_schema.json" not in files:
        return None
    h = digest(files)
    snaps = _list(project)
    if snaps and snaps[-1][1]["hash"] == h:
        if relabel:                                   # same state already saved: just make it easy to find
            path, m = snaps[-1]
            m["label"] = label
            with gzip.open(path, "wt", encoding="utf-8") as f:
                json.dump(m, f)
            return m["id"]
        return None
    sid = f"{int(time.time() * 1000)}-{h}"
    with gzip.open(_dir(project) / f"{sid}.json.gz", "wt", encoding="utf-8") as f:
        json.dump({"id": sid, "ts": iso(now()), "label": label, "hash": h, "files": files}, f)
    for p, _ in snaps[: max(0, len(snaps) + 1 - KEEP)]:
        p.unlink(missing_ok=True)
    return sid


def listing(project):
    rows = []
    for p, m in reversed(_list(project)):
        rows.append({"id": m["id"], "ts": m["ts"], "label": m["label"],
                     "tasks": sum(1 for k in m["files"] if k.startswith("Tasks/"))})
    return rows


def _tasks(files):
    out = {}
    for k, txt in files.items():
        if k.startswith("Tasks/"):
            fm, _ = parse_frontmatter(txt)
            out[fm.get("id")] = fm
    return out


def describe(old, new):
    a, b = _tasks(old), _tasks(new)
    lines = []
    for tid in sorted(set(a) | set(b)):
        if tid not in b:
            lines.append(f"{tid} removed")
        elif tid not in a:
            lines.append(f"{tid} “{b[tid]['title']}” appeared")
        else:
            for f in ("status", "title", "owner", "archived"):
                if a[tid].get(f) != b[tid].get(f):
                    lines.append(f"{tid} {f}: {a[tid].get(f)!r} → {b[tid].get(f)!r}")
    return lines


def restore(project, vault, sid=None, steps=1):
    """Go back. -> (restored_snapshot_id, human-readable lines, set of locked task ids)."""
    vault = Path(vault)
    cur = bundle(vault)
    snapshot(project, vault, "undo (the state you left)", relabel=True)            # keeps what we are leaving, so it can be redone
    snaps = _list(project)
    if sid:
        target = next((m for _, m in snaps if m["id"] == sid), None)
    else:
        distinct = [m for _, m in reversed(snaps) if m["hash"] != digest(cur)]
        target = None
        seen = []
        for m in distinct:
            if not seen or seen[-1] != m["hash"]:
                seen.append(m["hash"])
                if len(seen) == steps:
                    target = m
                    break
    if not target:
        return None, ["Nothing to undo."], set()
    files = dict(target["files"])
    cur_t, new_t = _tasks(cur), _tasks(files)
    locked, ignored = set(), json.loads(files.get("_ignored.json", "[]"))
    for tid, fm in new_t.items():
        before = cur_t.get(tid)
        if before and before.get("status") != fm.get("status"):
            locked.add(tid)
    for tid, fm in cur_t.items():                        # created since: don't let the docs scan bring it back
        if tid not in new_t and fm.get("key") and fm["key"] not in ignored:
            ignored.append(fm["key"])
    files["_ignored.json"] = json.dumps(ignored)
    for tid in locked:
        k = f"Tasks/{tid}.md"
        fmx, body = parse_frontmatter(files[k])
        fmx["locked"] = True
        from .store import dump_frontmatter
        files[k] = dump_frontmatter(fmx, body)
    lines = describe(cur, files)
    for k in list(cur):
        if k not in files and k.startswith("Tasks/"):
            (vault / k).unlink(missing_ok=True)
    for k, txt in files.items():
        (vault / k).parent.mkdir(parents=True, exist_ok=True)
        atomic_write(vault / k, txt)
    return target["id"], lines, locked
