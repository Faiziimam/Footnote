"""Render Dashboard.md (works in plain Obsidian, no plugins required)."""
import datetime as dt
from .store import now, CORE_FIELDS
from . import relations

COLS = ["todo", "active", "blocked", "done"]


def bar(pct, n=10):
    f = round(pct / 100 * n)
    return "█" * f + "░" * (n - f)


def render(store, tasks, schema, known=None):
    items = [fm for fm, _ in tasks.values()]
    total = len(items)
    done = sum(1 for f in items if f["status"] == "done")
    pct = round(100 * done / total) if total else 0
    extra = [k for k in schema["fields"] if k not in CORE_FIELDS]

    waits = relations.waiting_on(tasks)
    kids = relations.children(tasks)
    problems = relations.validate(tasks, known)
    out = ["# Dashboard", "",
           f"_Auto-generated {now().strftime('%Y-%m-%d %H:%M UTC')} — do not edit; edit task notes instead._", "",
           f"**Overall:** {bar(pct)} {pct}% ({done}/{total} done)", ""]
    counts = {c: sum(1 for f in items if f["status"] == c) for c in COLS}
    out += ["| " + " | ".join(COLS) + " |", "|" + "---|" * len(COLS),
            "| " + " | ".join(str(counts[c]) for c in COLS) + " |", ""]

    epics = {}
    for f in items:
        epics.setdefault(f["epic"], []).append(f)
    out += ["## Epics", "", "| Epic | Progress | Done | Active |", "|---|---|---|---|"]
    for e, fs in sorted(epics.items()):
        d = sum(1 for f in fs if f["status"] == "done")
        a = sum(1 for f in fs if f["status"] == "active")
        p = round(100 * d / len(fs))
        out.append(f"| {e} | {bar(p)} {p}% | {d}/{len(fs)} | {a} |")
    out.append("")

    if problems:
        out += ["## ⚠ Relationship problems", ""] + [f"- {p}" for p in problems] + [""]
    parents = {t: ks for t, ks in kids.items() if t in tasks}
    if parents:
        out += ["## Parent roll-up", "", "| Parent | Children done |", "|---|---|"]
        for t, ks in sorted(parents.items()):
            d = sum(1 for k in ks if tasks[k][0]["status"] == "done")
            out.append(f"| [[{t}\\|{tasks[t][0]['title']}]] | {bar(round(100*d/len(ks)))} {d}/{len(ks)} |")
        out.append("")

    for c in COLS:
        fs = [f for f in items if f["status"] == c]
        out += [f"## {c.title()} ({len(fs)})", ""]
        if not fs:
            out += ["_none_", ""]
            continue
        head = ["Task", "Epic", "Owner"] + (["Priority"] if any(x.get("priority") for x in items) else []) + \
               (["Due"] if any(x.get("due") for x in items) else []) + ["Waiting on"] + extra
        out += ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
        for f in fs:
            wait = ", ".join(f"[[{w}]]" for w in waits.get(f["id"], [])) if c in ("todo", "active") else ""
            row = [f"[[{f['id']}\\|{f['title']}]]", f["epic"], f.get("owner", "")] + \
                  ([f.get("priority", "")] if "Priority" in head else []) + ([f.get("due", "")] if "Due" in head else []) + \
                  [wait] + [str(f.get(k, "")) for k in extra]
            out.append("| " + " | ".join(row) + " |")
        out.append("")
    (store.vault / "Dashboard.md").write_text("\n".join(out), encoding="utf-8")
    render_relations(store, tasks)


def render_relations(store, tasks):
    rows = ["# Relations", "", "_Edge table, auto-generated. Columns: from → type → to (like a SQL join table)._", "",
            "| From | Type | To | From status | To status |", "|---|---|---|---|---|"]
    for src, t, dst in relations.edges(tasks):
        ts = tasks[dst][0]["status"] if dst in tasks else "MISSING"
        rows.append(f"| [[{src}]] | {t} | [[{dst}]] | {tasks[src][0]['status']} | {ts} |")
    (store.vault / "Relations.md").write_text("\n".join(rows) + "\n", encoding="utf-8")
