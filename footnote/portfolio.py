"""One page for someone who runs several projects: which need attention, and how each is doing.
Reads each project's existing tracker files (no sync needed); the list lives in ~/.footnote/portfolio.json."""
import datetime as dt
import json
import os
from pathlib import Path
from . import config, github, journal, metrics, relations
from .signals import _git
from .store import Store, atomic_write
from .dashboard import bar


def home():
    return Path(os.environ.get("FOOTNOTE_HOME") or Path.home() / ".footnote")


def _file():
    return home() / "portfolio.json"


def load():
    try:
        return json.loads(_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def save(items):
    home().mkdir(parents=True, exist_ok=True)
    atomic_write(_file(), json.dumps(items, indent=1))


def add(path):
    p = str(Path(path).expanduser().resolve())
    if not Path(p).is_dir():
        raise ValueError(f"I can't find the folder {path}")
    items = load()
    if p not in items:
        items.append(p)
        save(items)


def remove(path):
    p = str(Path(path).expanduser().resolve())
    save([x for x in load() if x != p])


def card(path, today=None):
    from .insights import project_info
    today = today or dt.date.today()
    cfg = config.load(path)
    vault = Path(path) / cfg["vault"]
    if not (vault / "_schema.json").exists():
        return {"path": path, "name": Path(path).name, "missing": True, "score": 0, "flags": ["not set up yet — run footnote in that folder"]}
    tasks = {k: v for k, v in Store(vault).load_tasks().items() if not v[0].get("archived")}
    fms = [fm for fm, _ in tasks.values()]
    info = project_info(vault, path)
    done = sum(1 for f in fms if f["status"] == "done")
    pct = round(100 * done / len(fms)) if fms else 0
    blocked = [f for f in fms if f["status"] == "blocked"]
    overdue = [f for f in fms if f.get("due") and f["status"] != "done" and f["due"] < today.isoformat()]
    d7 = sum(1 for f in fms if f.get("done") and (today - dt.date.fromisoformat(f["done"][:10])).days < 7)
    risks = journal.open_risks(journal.read(vault))
    gh = github.load(vault)
    ci = (gh or {}).get("ci", {}).get("state")
    last = _git(path, "log", "-1", "--format=%aI").strip()
    idle = (today - dt.date.fromisoformat(last[:10])).days if last else None
    mets = metrics.summarize(metrics.read(vault), None, *metrics.settings(cfg))
    rev = mets.get("revenue")
    flags = []
    score = 0
    for cond, pts, text in ((ci == "failing", 3, "build failing"), (bool(blocked), 2, f"{len(blocked)} blocked"),
                            (bool(overdue), 2, f"{len(overdue)} overdue"), (bool(risks), 1, f"{len(risks)} open risk(s)"),
                            (idle is not None and idle > 14 and pct < 100, 2, f"no activity for {idle} days"),
                            (bool(rev and rev["prev7"] > 0 and rev["last7"] < 0.7 * rev["prev7"]), 2, "revenue down week on week")):
        if cond:
            score += pts
            flags.append(text)
    return {"path": path, "name": info["name"], "kind": info["kind"], "pct": pct, "done": done, "total": len(fms), "d7": d7,
            "blocked": len(blocked), "overdue": len(overdue), "risks": len(risks), "ci": ci, "idle": idle,
            "revenue": (f"{metrics.fmt(rev['latest'])} {rev['unit']}".strip() if rev else ""), "flags": flags, "score": score}


def render(cards):
    cards = sorted(cards, key=lambda c: (-c["score"], c["name"].lower()))
    o = ["# Portfolio", "", f"_{len(cards)} project(s), most in need of attention first. Generated {dt.date.today().isoformat()}._", ""]
    needs = [c for c in cards if c["flags"]]
    o += ["## Needs attention", ""] + ([f"- **{c['name']}** — {', '.join(c['flags'])}" for c in needs] or ["_Nothing — all projects look healthy._"]) + [""]
    o += ["## All projects", "", "| Project | Kind | Progress | Last 7 days | Blocked | Overdue | Build | Revenue (30d) |", "|---|---|---|---|---|---|---|---|"]
    for c in cards:
        if c.get("missing"):
            o.append(f"| {c['name']} | | _not set up_ | | | | | |")
            continue
        o.append(f"| {c['name']} | {c['kind']} | {bar(c['pct'])} {c['pct']}% ({c['done']}/{c['total']}) | {c['d7']} done | {c['blocked'] or ''} | "
                 f"{c['overdue'] or ''} | {c['ci'] or ''} | {c['revenue']} |")
    return "\n".join(o) + "\n"


def build(paths=None):
    paths = paths if paths is not None else load()
    cards = []
    for p in paths:
        if not Path(p).is_dir():
            cards.append({"path": p, "name": Path(p).name, "missing": True, "score": 0, "flags": ["folder not found"]})
            continue
        try:
            cards.append(card(p))
        except Exception as e:                      # one broken project never hides the others
            cards.append({"path": p, "name": Path(p).name, "missing": True, "score": 1, "flags": [f"could not read tracker ({e})"]})
    md = render(cards)
    home().mkdir(parents=True, exist_ok=True)
    atomic_write(home() / "Portfolio.md", md)
    return md, cards
