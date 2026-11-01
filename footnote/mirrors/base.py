"""Two-way mirrors. The local vault is the source of truth; each mirror is an external view
(Notion, Google Sheets, Excel/CSV, SQLite) that people may ALSO edit.

Each sync:  pull remote -> 3-way merge against the last-pushed snapshot (only cells a human
actually changed are applied) -> run automation -> push the result -> save new snapshot.
Failures are warnings, never data loss: if a mirror is unreachable it is skipped this round.
"""
import hashlib
import json
import time
from pathlib import Path
from .. import rows as R


class MirrorError(Exception):
    pass


class Mirror:
    type = "base"
    supports_publish = False

    def __init__(self, cfg, project, vault):
        self.cfg, self.project, self.vault = cfg, Path(project), Path(vault)
        self.name = cfg.get("name") or cfg["type"]
        self.snap_path = self.vault / ".mirrors" / f"{self.name}.json"

    def publish(self, docs):                # docs: {page name: markdown}
        raise NotImplementedError

    def missing_pages(self, names):         # published pages someone deleted (so we can recreate them)
        return set()

    # -- to implement
    def pull(self):                       # -> list[dict col -> str]
        raise NotImplementedError

    def push(self, columns, all_rows, changed_ids):
        raise NotImplementedError

    def where(self):                      # human-readable location
        return self.name

    def ping(self):
        """Safe, read-only connection test -> (ok, human message)."""
        try:
            self.pull()
            return True, f"connected ({self.where()})"
        except MirrorError as e:
            return False, str(e)

    # -- shared state
    def snapshot(self):
        try:
            return json.loads(self.snap_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"rows": {}, "meta": {}}

    def save_snapshot(self, snap):
        self.snap_path.parent.mkdir(parents=True, exist_ok=True)
        from ..store import atomic_write
        atomic_write(self.snap_path, json.dumps(snap, indent=1))


def _same(col, a, b, schema):
    return R.from_cell(col, a, schema) == R.from_cell(col, b, schema)


def publish(mirror, docs, force=False):
    """Write the report / team / figures pages into the external tool. Throttled, and only when content changed
    (Notion's API is slow at rewriting pages)."""
    snap = mirror.snapshot()
    meta = snap.setdefault("meta", {})
    every = float(mirror.cfg.get("publish_every_minutes", 30)) * 60
    if not force and time.time() - meta.get("published_at", 0) < every:
        return 0
    digest = lambda t: hashlib.sha1(t.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]
    gone = mirror.missing_pages(docs)
    changed = {n: t for n, t in docs.items() if meta.get("published", {}).get(n) != digest(t) or n in gone}
    if not changed:
        return 0
    mirror.publish(changed)
    snap = mirror.snapshot()                       # publish() may have saved page ids
    meta = snap.setdefault("meta", {})
    meta.setdefault("published", {}).update({n: digest(t) for n, t in changed.items()})
    meta["published_at"] = time.time()
    mirror.save_snapshot(snap)
    return len(changed)


def merge_pull(mirror, tasks, schema, store, ops):
    """Apply human edits found in the mirror. `ops` supplies set_status/create callbacks."""
    snap = mirror.snapshot()
    last = snap["rows"]
    remote = mirror.pull()
    changed = 0
    for row in remote:
        rid = (row.get("id") or "").strip()
        if not rid:                                   # a brand-new row typed into the tracker
            title = (row.get("title") or "").strip()
            if title:
                ops["create"](tasks, row, f"added in {mirror.name}")
                changed += 1
            continue
        if rid not in tasks:                          # created by a teammate: adopt it, keep their ID
            if (row.get("title") or "").strip() and "adopt" in ops:
                ops["adopt"](tasks, row, mirror.name)
                changed += 1
            continue
        fm = tasks[rid][0]
        old = last.get(rid)
        if old is None:                               # never pushed before: nothing to compare
            continue
        for col, cell in row.items():
            if col in R.READONLY or col in R.HIDDEN or col in (schema.get("formulas") or {}) or col not in old:
                continue
            if _same(col, cell, old[col], schema):
                continue
            val = R.from_cell(col, cell, schema)
            if val is None or val == fm.get(col):
                continue
            if col == "status":
                changed += ops["set_status"](fm, val, f"edited in {mirror.name}")
            else:
                store.log(f"{rid} {col}: {fm.get(col)!r} → {val!r} (edited in {mirror.name})")
                fm[col] = val
                changed += 1
    return changed


def push(mirror, tasks, schema, waits, errors):
    snap = mirror.snapshot()
    cols = R.columns(schema)
    rows = {tid: R.to_row(fm, schema, waits) for tid, (fm, _) in sorted(tasks.items())}
    changed = [t for t, r in rows.items() if snap["rows"].get(t) != r]
    removed = set(snap["rows"]) - set(rows)
    if not changed and not removed and snap.get("cols") == cols:
        return 0
    mirror.types = schema["fields"]
    mirror.removed = removed
    mirror.push(cols, list(rows.values()), set(changed) | ({"*"} if snap.get("cols") != cols else set()))
    snap = mirror.snapshot()          # re-read: push() may have saved ids (database / spreadsheet)
    snap.update({"rows": rows, "cols": cols})
    mirror.save_snapshot(snap)
    return len(changed)
