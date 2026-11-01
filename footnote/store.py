"""Obsidian-vault storage: task notes (markdown + frontmatter), schema, changelog."""
import json
import os
import re
import datetime as dt
from pathlib import Path
from .security import valid_task_id, FIELD_NAME, clean_text


def atomic_write(path, text):
    """Write via a temp file + rename, so a crash or a concurrent reader never sees half a file."""
    path = Path(path)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(clean_text(text) if not text.isascii() else text, encoding="utf-8")   # safety net for every file we write
    os.replace(tmp, path)

STATES = ["todo", "active", "blocked", "done"]
CORE_FIELDS = {
    "id": "string", "key": "string", "title": "string", "epic": "string",
    "status": "status", "source": "string", "created": "date",
    "started": "date", "done": "date", "locked": "bool",
    "cycle_days": "number",
    "relations": "list", "unlinked": "list", "owner": "string", "archived": "bool",
    "priority": "string", "due": "date", "estimate": "number",
}
COMPUTED = {"cycle_days": "days between started and done"}


LABELS = {"todo": "Not started", "active": "In progress", "blocked": "Blocked", "done": "Done"}
ALIASES = {
    "todo": "todo", "to do": "todo", "not started": "todo", "backlog": "todo", "open": "todo",
    "new": "todo", "planned": "todo",
    "active": "active", "in progress": "active", "doing": "active", "started": "active",
    "wip": "active", "ongoing": "active", "in-progress": "active",
    "blocked": "blocked", "stuck": "blocked", "on hold": "blocked", "waiting": "blocked",
    "done": "done", "complete": "done", "completed": "done", "finished": "done",
    "closed": "done", "shipped": "done",
}


def norm_status(s):
    """Accept friendly words ('In progress', 'wip', 'finished') -> internal state or None."""
    return ALIASES.get(str(s or "").strip().lower())


def parse_ts(s):
    """Read a timestamp from anywhere (git, GitHub, Notion, our own files). Older Pythons (3.9/3.10) cannot read a trailing 'Z'
    or fractions that are not 3/6 digits, so normalise first. Always returns a timezone-aware datetime."""
    s = str(s).strip()
    if s[-1:] in ("Z", "z"):
        s = s[:-1] + "+00:00"
    m = re.match(r"^(.*T\d{2}:\d{2}:\d{2})\.(\d+)(.*)$", s)
    if m:
        s = f"{m.group(1)}.{(m.group(2) + '000000')[:6]}{m.group(3)}"
    d = dt.datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def now():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def iso(t):
    return t.isoformat() if t else ""


def parse_frontmatter(text):
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.S)
    if not m:
        return {}, text
    fm = {}
    for line in m.group(1).splitlines():
        if ":" not in line or line.startswith("#"):
            continue
        k, v = line.split(":", 1)
        v = v.strip()
        try:
            fm[k.strip()] = json.loads(v)
        except ValueError:
            fm[k.strip()] = v  # hand-written unquoted YAML scalar
    return fm, m.group(2)


def dump_frontmatter(fm, body):
    lines = [f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in fm.items()]
    return "---\n" + "\n".join(lines) + "\n---\n" + body


def infer_type(v):
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "number"
    if isinstance(v, list):
        return "list"
    if isinstance(v, str) and re.match(r"^\d{4}-\d{2}-\d{2}", v):
        return "date"
    return "string"


class Store:
    def __init__(self, vault):
        self.vault = Path(vault)
        self.tasks_dir = self.vault / "Tasks"
        self.schema_path = self.vault / "_schema.json"
        self.changelog_path = self.vault / "Changelog.md"
        self.pending_log = []

    # ---- setup / schema
    def ensure(self):
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        if not self.schema_path.exists():
            self.save_schema({"next_id": 1, "fields": dict(CORE_FIELDS),
                              "computed": COMPUTED})
        s = self.schema()  # migrate older vaults: add core fields they predate
        missing = {k: v for k, v in CORE_FIELDS.items() if k not in s["fields"]}
        if missing:
            s["fields"].update(missing)
            self.save_schema(s)

    def schema(self):
        return json.loads(self.schema_path.read_text(encoding="utf-8"))

    def save_schema(self, s):
        atomic_write(self.schema_path, json.dumps(s, indent=2) + "\n")

    def next_id(self):
        s = self.schema()
        n = s["next_id"]
        s["next_id"] = n + 1
        self.save_schema(s)
        return f"T-{n:03d}"

    def evolve_schema(self, tasks):
        """Discover user/agent-added frontmatter fields and register them."""
        s = self.schema()
        added = []
        for fm, _ in tasks.values():
            for k, v in fm.items():
                if k not in s["fields"] and FIELD_NAME.match(str(k)):
                    s["fields"][k] = infer_type(v)
                    added.append(k)
        if added:
            self.save_schema(s)
            for k in added:
                self.log(f"schema: new field `{k}` ({s['fields'][k]})")
        return s

    # ---- tasks
    def path(self, tid):
        if not valid_task_id(tid):
            raise ValueError(f"refusing to use {tid!r} as a task id")
        return self.tasks_dir / f"{tid}.md"

    def load_tasks(self):
        out = {}
        for p in sorted(self.tasks_dir.glob("T-*.md")):
            fm, body = parse_frontmatter(p.read_text(encoding="utf-8"))
            if valid_task_id(fm.get("id")) and p.stem == fm["id"]:
                fm.setdefault("relations", [])
                fm.setdefault("unlinked", [])
                fm.setdefault("owner", "")
                fm.setdefault("archived", False)
                fm.setdefault("priority", "")
                fm.setdefault("due", "")
                fm.setdefault("estimate", None)
                out[fm["id"]] = (fm, body)
        return out

    def write_task(self, fm, body):
        p = self.path(fm["id"])
        new = dump_frontmatter(fm, body)
        if p.exists() and p.read_text(encoding="utf-8") == new:
            return False
        atomic_write(p, new)
        return True

    def ignored(self):
        try:
            return set(json.loads((self.vault / "_ignored.json").read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return set()

    def set_ignored(self, keys):
        atomic_write(self.vault / "_ignored.json", json.dumps(sorted(keys)))

    # ---- changelog
    def log(self, msg):
        self.pending_log.append(msg)

    def flush_log(self):
        if not self.pending_log:
            return
        stamp = now().strftime("%Y-%m-%d %H:%M")
        existing = self.changelog_path.read_text(encoding="utf-8") if self.changelog_path.exists() \
            else "# Changelog\n\nEvery automatic change, newest last.\n\n"
        add = "".join(f"- {stamp} — {m}\n" for m in self.pending_log)
        self.changelog_path.write_text(existing + add, encoding="utf-8")
        self.pending_log = []
