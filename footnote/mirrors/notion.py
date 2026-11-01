"""Notion: a database of tasks. Needs an internal integration token and ONE parent page shared
with that integration (Notion setup guide: docs/notion.md). Edits made in Notion flow back."""
import os
import re
import time
from .base import Mirror, MirrorError
from .http import call
from .. import config
from .. import rows as R
from .. import mdconv
from ..store import LABELS

API = "https://api.notion.com/v1"
VERSION = "2022-06-28"
TITLE_COL = "title"


def prop_name(col):
    return {"title": "Name", "id": "ID"}.get(col, col.replace("_", " ").capitalize())


def page_id(s):
    m = re.findall(r"[0-9a-fA-F]{32}", (s or "").replace("-", ""))
    return m[-1] if m else ""


def trunc(s, n=1900):
    return s if len(s) <= n else s[:n - 1] + "…"


class NotionMirror(Mirror):
    type = "notion"
    supports_publish = True

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.base = (self.cfg.get("base_url") or os.environ.get("FOOTNOTE_NOTION_URL") or API).rstrip("/")
        self.pause = 0 if self.base != API else 0.34   # Notion allows ~3 requests/second
        self.token = config.secret(self.cfg, default_env="NOTION_TOKEN")
        self._db = None

    def _req(self, method, path, body=None):
        if not self.token:
            raise MirrorError("Notion token missing: set NOTION_TOKEN (see docs/notion.md)")
        time.sleep(self.pause)
        return call(method, self.base + path, {"Authorization": f"Bearer {self.token}",
                                               "Notion-Version": VERSION}, body)

    def ping(self):
        try:
            me = self._req("GET", "/users/me")
            return True, f"connected as {me.get('name') or me.get('bot', {}).get('owner', {}).get('type', 'integration')}"
        except MirrorError as e:
            return False, str(e)

    def _children_ids(self, pid):
        ids, cursor = [], None
        while True:
            res = self._req("GET", f"/blocks/{pid}/children?page_size=100" + (f"&start_cursor={cursor}" if cursor else ""))
            ids += [b["id"] for b in res.get("results", [])]
            if not res.get("has_more"):
                return ids
            cursor = res.get("next_cursor")

    def _alive(self, pid):
        try:
            return not self._req("GET", f"/pages/{pid}").get("archived")
        except MirrorError as e:
            if "404" in str(e):
                return False
            raise

    def missing_pages(self, names):
        pages = (self.snapshot().get("meta") or {}).get("pages", {})
        return {n for n in names if pages.get(n) and not self._alive(pages[n])}

    def publish(self, docs):
        parent = page_id(self.cfg.get("parent_page"))
        if not parent:
            raise MirrorError("Notion: parent_page is needed to publish the report")
        snap = self.snapshot()
        pages = snap.setdefault("meta", {}).setdefault("pages", {})
        for name, md in docs.items():
            blocks = mdconv.blocks(md)
            pid = pages.get(name)
            rest = blocks
            if pid and not self._alive(pid):
                pid = None                                   # deleted or archived in Notion: recreate it
            if pid:
                for bid in self._children_ids(pid):
                    self._req("DELETE", f"/blocks/{bid}")
            if not pid:
                res = self._req("POST", "/pages", {"parent": {"page_id": parent},
                                                   "properties": {"title": {"title": [{"text": {"content": name}}]}},
                                                   "children": blocks[:100]})
                pid = pages[name] = res["id"]
                rest = blocks[100:]
            for i in range(0, len(rest), 100):
                self._req("PATCH", f"/blocks/{pid}/children", {"children": rest[i:i + 100]})
            self.save_snapshot(snap)

    def where(self):
        db = (self.snapshot().get("meta") or {}).get("database_id") or self.cfg.get("database_id")
        return f"Notion database {db}" if db else "Notion (database not created yet)"

    # ---- database / schema
    def _schema_props(self, columns, schema_types):
        props = {}
        for c in columns:
            if c == "title":
                props[prop_name(c)] = {"title": {}}
            elif c == "status":
                props[prop_name(c)] = {"select": {"options": [{"name": v} for v in LABELS.values()]}}
            elif c == "epic":
                props[prop_name(c)] = {"select": {}}
            elif c in ("started", "done", "created") or schema_types.get(c) == "date":
                props[prop_name(c)] = {"date": {}}
            elif c == "cycle_days" or schema_types.get(c) == "number":
                props[prop_name(c)] = {"number": {}}
            elif c == "locked" or schema_types.get(c) == "bool":
                props[prop_name(c)] = {"checkbox": {}}
            else:
                props[prop_name(c)] = {"rich_text": {}}
        return props

    def _ensure_db(self, columns, types):
        if self._db:
            return self._db
        snap = self.snapshot()
        db = (snap.get("meta") or {}).get("database_id") or page_id(self.cfg.get("database_id"))
        want = self._schema_props(columns, types)
        if not db:
            parent = page_id(self.cfg.get("parent_page"))
            if not parent:
                raise MirrorError("Notion: tell me which page to put the tracker in (parent_page)")
            res = self._req("POST", "/databases", {
                "parent": {"type": "page_id", "page_id": parent},
                "title": [{"type": "text", "text": {"content": self.cfg.get("title", "Tracker")}}],
                "properties": want})
            db = res["id"]
            snap.setdefault("meta", {})["database_id"] = db
            self.save_snapshot(snap)
        else:
            have = self._req("GET", f"/databases/{db}").get("properties", {})
            missing = {n: d for n, d in want.items() if n not in have and "title" not in d}
            if missing:
                self._req("PATCH", f"/databases/{db}", {"properties": missing})
        self._db = db
        return db

    # ---- values
    @staticmethod
    def _text(prop):
        t = prop.get("type")
        v = prop.get(t)
        if t in ("title", "rich_text"):
            return "".join(x.get("plain_text", "") for x in v or [])
        if t == "select":
            return (v or {}).get("name", "")
        if t == "date":
            return (v or {}).get("start", "") or ""
        if t == "number":
            return "" if v is None else str(v)
        if t == "checkbox":
            return "Yes" if v else "No"
        return ""

    def _props_for(self, row, columns, types):
        out = {}
        for c in columns:
            val, n = row.get(c, ""), prop_name(c)
            if c == "title":
                out[n] = {"title": [{"text": {"content": trunc(val)}}]}
            elif c in ("status", "epic"):
                out[n] = {"select": {"name": val[:99]} if val else None}
            elif c in ("started", "done", "created") or types.get(c) == "date":
                out[n] = {"date": {"start": val} if val else None}
            elif c == "cycle_days" or types.get(c) == "number":
                try:
                    out[n] = {"number": float(val) if val != "" else None}
                except ValueError:
                    out[n] = {"number": None}
            elif c == "locked" or types.get(c) == "bool":
                out[n] = {"checkbox": R.from_cell("locked", val, {"fields": {}}) is True}
            else:
                out[n] = {"rich_text": [{"text": {"content": trunc(val)}}] if val else []}
        return out

    def _query_all(self, db):
        pages, cursor = [], None
        while True:
            res = self._req("POST", f"/databases/{db}/query",
                            {"page_size": 100, **({"start_cursor": cursor} if cursor else {})})
            pages += res.get("results", [])
            if not res.get("has_more"):
                return pages
            cursor = res.get("next_cursor")

    def pull(self):
        db = (self.snapshot().get("meta") or {}).get("database_id") or page_id(self.cfg.get("database_id"))
        if not db:
            return []
        out = []
        for pg in self._query_all(db):
            props = pg.get("properties", {})
            row = {}
            for name, prop in props.items():
                col = "title" if prop.get("type") == "title" else \
                    ("id" if name == "ID" else name.lower().replace(" ", "_"))
                row[col] = self._text(prop)
            out.append(row)
        return out

    def push(self, columns, all_rows, changed_ids):
        types = getattr(self, "types", {})
        db = self._ensure_db(columns, types)
        existing, orphans = {}, {}
        for pg in self._query_all(db):
            rid = self._text(pg["properties"].get("ID", {}))
            if rid:
                existing[rid] = pg["id"]
            else:   # a row a human typed in Notion: it becomes a task, so adopt that page (no duplicate)
                title = self._text(pg["properties"].get("Name", {})).strip().lower()
                orphans.setdefault(title, []).append(pg["id"])
        for rid in getattr(self, "removed", ()):               # archived/deleted locally -> archive the Notion page
            if rid in existing:
                self._req("PATCH", f"/pages/{existing[rid]}", {"archived": True})
        for row in all_rows:
            rid = row["id"]
            if "*" not in changed_ids and rid not in changed_ids:
                continue
            props = self._props_for(row, columns, types)
            if rid not in existing and orphans.get(row["title"].strip().lower()):
                existing[rid] = orphans[row["title"].strip().lower()].pop(0)
            if rid in existing:
                self._req("PATCH", f"/pages/{existing[rid]}", {"properties": props})
            else:
                self._req("POST", "/pages", {"parent": {"database_id": db}, "properties": props})
