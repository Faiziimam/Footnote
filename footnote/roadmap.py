"""Schedule view: what is overdue, what is coming, a Gantt chart, and a projected finish from estimates."""
import datetime as dt
import re


def _d(s):
    try:
        return dt.date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def facts(tasks, today=None):
    today = today or dt.date.today()
    fms = [fm for fm, _ in tasks.values()]
    open_ = [f for f in fms if f["status"] != "done"]
    overdue = sorted([f for f in open_ if f.get("due") and _d(f["due"]) and _d(f["due"]) < today], key=lambda f: f["due"])
    soon = sorted([f for f in open_ if f.get("due") and _d(f["due"]) and today <= _d(f["due"]) <= today + dt.timedelta(days=14)],
                  key=lambda f: f["due"])
    unsched = [f for f in open_ if not f.get("due")]
    # velocity: estimate-days finished in the last 28 days
    done28 = sum((f.get("estimate") or 0) for f in fms if f["status"] == "done" and f.get("done") and _d(f["done"])
                 and (today - _d(f["done"])).days < 28)
    left = sum((f.get("estimate") or 0) for f in open_)
    unest = sum(1 for f in open_ if not f.get("estimate"))
    projected = None
    if done28 > 0 and left > 0:
        projected = today + dt.timedelta(days=round(left / (done28 / 28)))
    return {"overdue": overdue, "soon": soon, "unscheduled": unsched, "left": left, "velocity_per_week": round(done28 / 4, 1),
            "unestimated": unest, "projected": projected, "any": any(f.get("due") or f.get("estimate") for f in fms)}


def render(tasks, today=None):
    today = today or dt.date.today()
    f = facts(tasks, today)
    o = ["# Roadmap", "", f"_Built from due dates and estimates ({today.isoformat()}). Set them with `footnote due T-004 next friday`, "
         "or write `due:2026-12-01 ~3d !high` after a checklist item._", ""]
    if f["overdue"]:
        o += ["## Overdue", ""] + [f"- [[{x['id']}]] {x['title']} — due {x['due']} ({(today - _d(x['due'])).days} days ago)" for x in f["overdue"]] + [""]
    if f["soon"]:
        o += ["## Due in the next 14 days", ""] + [f"- [[{x['id']}]] {x['title']} — {x['due']}" + (f" · {x['owner']}" if x.get("owner") else "") for x in f["soon"]] + [""]
    if f["projected"]:
        o += ["## Projected finish", "",
              f"Remaining estimate: **{f['left']:g} days** · recent pace: **{f['velocity_per_week']:g} estimate-days/week** → "
              f"roughly **{f['projected'].isoformat()}**" + (f" ({f['unestimated']} open tasks have no estimate yet, so this is optimistic)" if f["unestimated"] else "") + ".", ""]
    dated = [fm for fm, _ in tasks.values() if fm.get("due") and _d(fm["due"])]
    if dated:
        o += ["## Timeline", "", "```mermaid", "gantt", "    dateFormat YYYY-MM-DD", "    title Roadmap"]
        by = {}
        for fm in sorted(dated, key=lambda x: (x["epic"], x["due"])):
            by.setdefault(fm["epic"], []).append(fm)
        for epic, fs in by.items():
            o.append(f"    section {re.sub(r'[:;#]', ' ', epic)[:40]}")
            for fm in fs:
                end = _d(fm["due"])
                start = _d(fm.get("started")) or (end - dt.timedelta(days=max(1, int(fm.get("estimate") or 1)))) if fm.get("estimate") or fm.get("started") else end - dt.timedelta(days=1)
                if start >= end:
                    start = end - dt.timedelta(days=1)
                tag = "done" if fm["status"] == "done" else ("crit" if end < today else ("active" if fm["status"] == "active" else ""))
                name = re.sub(r"[:;#]", " ", fm["title"])[:45]
                o.append(f"    {name} :{tag + ', ' if tag else ''}{fm['id'].replace('-', '')}, {start.isoformat()}, {end.isoformat()}")
        o += ["```", ""]
    o.append(f"_{len(f['unscheduled'])} open task(s) have no due date._")
    return "\n".join(o) + "\n"
