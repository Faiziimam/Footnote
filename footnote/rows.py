"""Flat, human-friendly rows: the shape every external tracker (Notion, Sheets, CSV, SQL) sees."""
import datetime as dt
import re
from .store import LABELS, norm_status, CORE_FIELDS
from . import relations as rel

HIDDEN = {"key", "unlinked", "archived"}                 # internal bookkeeping, never shown externally
READONLY = {"id", "waiting_on", "cycle_days", "created", "source"}
LEAD = ["id", "title", "status", "epic", "owner", "priority", "due", "estimate", "relations", "waiting_on",
        "started", "done", "cycle_days", "locked", "created", "source"]
YES = {"yes", "true", "1", "y", "x", "✓", "checked"}


def columns(schema):
    extras = [k for k in schema["fields"] if k not in LEAD and k not in HIDDEN]
    return LEAD + extras


def ctype(col, schema):
    if col == "waiting_on":
        return "list"
    return schema["fields"].get(col, "string")


def to_cell(col, value):
    if col == "status":
        return LABELS.get(value, str(value))
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return "" if value is None else str(value)


def to_row(fm, schema, waits):
    row = {}
    for c in columns(schema):
        v = waits.get(fm["id"], []) if c == "waiting_on" else fm.get(c, "")
        row[c] = to_cell(c, v)
    return row


def norm_relation(token):
    token = token.strip()
    if not token:
        return None
    if rel.REL.match(token):
        return token
    m = re.match(r"^([A-Za-z][A-Za-z _-]*?)\s*[: ]\s*(T-\d{3,})$", token)
    if m:
        return f"{re.sub(r'[ -]+', '_', m.group(1).strip().lower())}:{m.group(2).upper()}"
    if re.match(r"^T-\d{3,}$", token, re.I):
        return f"related:{token.upper()}"
    return None


def norm_date(v):
    v = str(v or "").strip()
    if not v:
        return ""
    try:
        d = dt.datetime.fromisoformat(v.replace("Z", "+00:00"))
        if d.tzinfo:
            d = d.astimezone(dt.timezone.utc)
        return d.replace(microsecond=0, tzinfo=None).isoformat() if len(v) > 10 else d.date().isoformat()
    except ValueError:
        return v


def from_cell(col, cell, schema):
    """Parse an externally edited cell back to a canonical python value (None = unparseable)."""
    s = "" if cell is None else str(cell).strip()
    if col == "status":
        return norm_status(s)
    if col == "relations":
        return sorted({r for r in (norm_relation(t) for t in re.split(r"[,;\n]", s)) if r})
    t = ctype(col, schema)
    if col == "locked" or t == "bool":
        return s.lower() in YES
    if t == "number":
        try:
            f = float(s)
            return int(f) if f == int(f) else f
        except ValueError:
            return None if s else ""
    if t == "list":
        return sorted(x.strip() for x in s.split(",") if x.strip())
    if t == "date":
        return norm_date(s)
    return s
