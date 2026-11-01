"""The sync pipeline. Idempotent: running it twice with no new evidence changes nothing.

pull mirrors (human edits) -> scan docs -> relations -> git evidence -> parent roll-up
-> schema evolution -> write notes -> dashboard -> push mirrors
"""
import datetime as dt
import difflib
import re
from .store import parse_ts, Store, now, iso
from . import security, scan as scanner, signals, dashboard, relations, config, rows as R, team, insights, github, activity, formulas
from . import mirrors as M
from .mirrors import base as mbase

RANK = {"todo": 0, "active": 1, "blocked": 1, "done": 2}


class Report:
    def __init__(self):
        self.changed = 0
        self.warnings = []
        self.mirrors = []     # [(name, location)]


def _days(a, b):
    try:
        return max(0, (parse_ts(b) - parse_ts(a)).days)
    except Exception:
        return None


def _finish(fm, state, when):
    if state == "active" and not fm.get("started"):
        fm["started"] = when
    if state == "done":
        fm["started"] = fm.get("started") or when
        fm["done"] = when
        fm["cycle_days"] = _days(fm["started"], when)


def advance(fm, state, when, why, store):
    """Automatic, forward-only transition. Locked tasks and regressions are ignored."""
    cur = fm["status"]
    if fm.get("locked") or RANK[state] <= RANK[cur]:
        return False
    fm["status"] = state
    _finish(fm, state, when)
    store.log(f"{fm['id']} **{fm['title']}**: {cur} → {state} ({why})")
    return True


def set_status(fm, state, why, store, when=None):
    """A human or agent said so. Can move backwards (which then locks it against automation)."""
    cur = fm["status"]
    if state == cur:
        return False
    when = when or iso(now())
    fm["status"] = state
    if RANK[state] < RANK[cur]:
        fm["locked"] = True
        if cur == "done":
            fm["done"], fm["cycle_days"] = "", None
    _finish(fm, state, when)
    store.log(f"{fm['id']} **{fm['title']}**: {cur} → {state} ({why})")
    return True


def new_task(store, tasks, title, epic="Inbox", source="manual", status="todo", key=None):
    from .scan import make_key
    tid = store.next_id()
    t0 = iso(now())
    fm = {"id": tid, "key": key or make_key(epic, title), "title": title, "epic": epic,
          "status": "todo", "source": source, "created": t0, "started": "", "done": "",
          "locked": False, "cycle_days": None, "relations": [], "unlinked": [], "owner": "", "archived": False,
          "priority": "", "due": "", "estimate": None}
    tasks[tid] = (fm, f"# {title}\n\nEpic: {epic}  \nSource: `{source}`\n\n## Notes\n")
    store.log(f"{tid} created: **{title}** in _{epic}_ (from {source})")
    if status != "todo":
        set_status(fm, status, "created with this status", store, t0)
    return tid


def _norm(s):
    return re.sub(r"\W+", " ", s.lower()).strip()


def resolve_ref(tasks, ref):
    if re.match(r"^T-\d{3,}$", ref):
        return ref if ref in tasks else None
    n = _norm(ref)
    for tid, (fm, _) in tasks.items():
        if _norm(fm["title"]) == n or _norm(fm["title"].replace("Implement:", "")) == n:
            return tid
    best = [(min(signals.similarity(ref, fm["title"]), signals.similarity(fm["title"], ref)), tid)
            for tid, (fm, _) in tasks.items()]
    best = sorted(best, reverse=True)
    if best and best[0][0] >= 0.8 and (len(best) == 1 or best[1][0] < 0.8):
        return best[0][1]
    return None


def rollup(tasks, store):
    """Parents follow their children: any child started => parent active; all done => parent done."""
    kids = relations.children(tasks)
    changed, moved = 0, True
    while moved:
        moved = False
        for pid, ks in sorted(kids.items()):
            if pid not in tasks:
                continue
            fm = tasks[pid][0]
            states = [tasks[k][0]["status"] for k in ks if k in tasks]
            if not states:
                continue
            if all(s == "done" for s in states):
                when = max((tasks[k][0].get("done") or iso(now()) for k in ks if k in tasks))
                ok = advance(fm, "done", when, f"all {len(states)} subtasks done", store)
            elif any(s in ("active", "done", "blocked") for s in states) and fm["status"] == "todo":
                ok = advance(fm, "active", iso(now()), "a subtask was started", store)
            else:
                ok = False
            if ok:
                changed += 1
                moved = True
    return changed


def build_mirrors(project, vault, cfg, report):
    out = []
    for item in cfg.get("mirrors", []):
        if item.get("enabled", True) is False:
            continue
        try:
            out.append(M.make(item, project, vault))
        except M.MirrorError as e:
            report.warnings.append(str(e))
    return out


def sync_report(project, vault, use_agent=None, cfg=None, force_publish=False):
    cfg = cfg if cfg is not None else config.load(project)
    use_agent = cfg.get("use_agent") if use_agent is None else use_agent
    report = Report()
    store = Store(vault)
    store.ensure()
    tasks = store.load_tasks()
    changed = 0
    mirror_list = build_mirrors(project, vault, cfg, report)

    # 0. human edits made in external trackers
    def create_from_row(tasks_, row, why):
        schema_ = store.schema()
        tid = new_task(store, tasks_, security.clean_text(row["title"]).strip(), security.clean_text(row.get("epic") or "Inbox").strip() or "Inbox",
                       source=f"mirror: {why}")
        fm_ = tasks_[tid][0]
        st = R.from_cell("status", row.get("status"), schema_)
        if st and st != "todo":
            set_status(fm_, st, why, store)
        for r in R.from_cell("relations", row.get("relations", ""), schema_):
            relations.add(fm_, *r.split(":"), store, why)
        return tid
    def adopt_row(tasks_, row, name):
        schema_ = store.schema()
        rid = row["id"].strip()
        if not security.valid_task_id(rid) or rid in tasks_:
            report.warnings.append(f"ignored a row from {name} with an unusable id")
            return
        title = security.clean_text(row["title"]).strip()
        fm_ = {"id": rid, "key": scanner.make_key((row.get("epic") or "Inbox"), title), "title": title,
               "epic": (row.get("epic") or "Inbox").strip() or "Inbox", "status": "todo", "source": f"shared tracker ({name})",
               "created": iso(now()), "started": "", "done": "", "locked": False, "cycle_days": None,
               "relations": [], "unlinked": [], "owner": (row.get("owner") or "").strip(), "archived": False,
               "priority": (row.get("priority") or "").strip(), "due": R.from_cell("due", row.get("due", ""), schema_) or "",
               "estimate": R.from_cell("estimate", row.get("estimate", ""), schema_) or None}
        for col in ("started", "done", "locked"):
            if col in row:
                fm_[col] = R.from_cell(col, row[col], schema_)
        st = R.from_cell("status", row.get("status"), schema_)
        if st:
            fm_["status"] = st
        fm_["relations"] = R.from_cell("relations", row.get("relations", ""), schema_)
        tasks_[rid] = (fm_, f"# {title}\n\nEpic: {fm_['epic']}  \nSource: shared tracker ({name})\n\n## Notes\n")
        n = re.match(r"^T-(\d+)$", rid)
        if n and int(n.group(1)) >= schema_["next_id"]:    # never hand out an ID a teammate already used
            schema_["next_id"] = int(n.group(1)) + 1
            store.save_schema(schema_)
        store.log(f"{rid} adopted from {name}: **{title}** (added by a teammate)")
    ops = {"create": create_from_row, "adopt": adopt_row,
           "set_status": lambda fm, st, why: int(set_status(fm, st, why, store))}
    pulled = set()
    for m in mirror_list:
        try:
            changed += mbase.merge_pull(m, tasks, store.schema(), store, ops)
            pulled.add(m.name)
        except M.MirrorError as e:
            report.warnings.append(f"{m.name}: {e} (skipped this time; nothing was lost)")

    # 1. discover tasks from docs (bootstrap + continuous)
    items = None
    if use_agent and not tasks:
        from . import agent
        items = agent.propose(project, vault)
    items = items or scanner.scan(project, vault, cold_start=not tasks)
    by_key = {fm.get("key"): tid for tid, (fm, _) in tasks.items()}
    t0 = iso(now())
    ignored = store.ignored()
    items = [it for it in items if it["key"] not in ignored and it.get("legacy_key") not in ignored]
    # tasks whose doc line changed: the old key vanished and a new one appeared -> same task, keep its ID/history
    current = {it["key"] for it in items} | {it.get("legacy_key") for it in items}
    doc_sources = {it["source"] for it in items}
    orphans = {tid: fm for tid, (fm, _) in tasks.items() if fm.get("source") in doc_sources
               and fm.get("key") not in current and not fm.get("archived")}
    for it in items:
        if by_key.get(it["key"]) or by_key.get(it.get("legacy_key")) or not orphans:
            continue
        cands = sorted(((difflib.SequenceMatcher(None, _norm(it["title"]), _norm(fm["title"])).ratio()
                         + (0.25 if _norm(it["title"]) == _norm(fm["title"]) else 0), tid)
                        for tid, fm in orphans.items() if fm["source"] == it["source"]), reverse=True)
        if cands and cands[0][0] >= 0.6 and (len(cands) == 1 or cands[0][0] - cands[1][0] >= 0.1):
            tid = cands[0][1]
            fm = tasks[tid][0]
            if fm["title"] != it["title"] or fm["epic"] != it["epic"]:
                store.log(f"{tid} renamed in docs: “{fm['title']}” → “{it['title']}”" +
                          (f" (moved to {it['epic']})" if fm["epic"] != it["epic"] else ""))
                changed += 1
            fm.update({"title": it["title"], "epic": it["epic"], "key": it["key"]})
            by_key[it["key"]] = tid
            orphans.pop(tid)
    for it in items:
        tid = by_key.get(it["key"]) or by_key.get(it.get("legacy_key"))
        if tid is None:
            tid = new_task(store, tasks, it["title"], it["epic"], it["source"], key=it["key"])
            by_key[it["key"]] = tid
            changed += 1
        by_key.setdefault(it["key"], tid)
        for f_, v_ in (it.get("attrs") or {}).items():          # due / estimate / priority written in the docs (never overwrite edits)
            if v_ not in ("", None) and not tasks[tid][0].get(f_):
                tasks[tid][0][f_] = v_
                store.log(f"{tid} {f_} → {v_} (from {it['source']})")
                changed += 1
        if it["status"] != "todo" and not tasks[tid][0].get("archived"):
            if advance(tasks[tid][0], it["status"], t0, f"checkbox in {it['source']}", store):
                changed += 1

    # 1b. relationships: doc structure and in-text references (by ID, "title" or [[title]])
    for it in items:
        tid = by_key.get(it["key"]) or by_key.get(it.get("legacy_key"))
        fm = tasks[tid][0]
        if it.get("parent_key") in by_key:
            changed += relations.add(fm, "parent", by_key[it["parent_key"]], store, "doc hierarchy")
        for rtype, ref in it.get("refs", []):
            target = resolve_ref(tasks, ref)
            if target:
                changed += relations.add(fm, rtype, target, store, f"referenced in {it['source']}")
    for a, b, why in signals.git_relations(project, {t: v for t, v in tasks.items() if not v[0].get("archived")}):
        changed += relations.add(tasks[a][0], "related", b, store, why)

    # 2. apply git evidence in chronological order
    events = signals.git_events(project, {t: f for t, (f, _) in tasks.items() if not f.get("archived")})
    if activity.uses_activity(project, cfg):
        _, act_events = activity.record(project, vault, cfg)
        events = sorted(events + [e for e in act_events if e[1] in tasks and not tasks[e[1]][0].get("archived")])
    gh = None
    if cfg.get("github"):
        try:
            gh = github.fetch(cfg["github"], project)
            github.save(vault, gh)
            events = sorted(events + [e for e in gh["events"] if e[1] in tasks and not tasks[e[1]][0].get("archived")])
        except M.MirrorError as e:
            report.warnings.append(f"GitHub: {e} (will retry next time)")
            gh = github.load(vault)
    for when, tid, state, why in events:
        if advance(tasks[tid][0], state, when, why, store):
            changed += 1
    live = {t: v for t, v in tasks.items() if not v[0].get("archived")}
    changed += rollup(live, store)

    # 2b. who is doing what (from commit history); fill empty owners from the people who worked on each task
    hist = signals.git_history(project, cfg.get("repos", []))
    analysis = team.analyze(hist, live, cfg, github=gh)
    for tid, key in analysis["owners"].items():
        fm = tasks[tid][0]
        if not fm.get("owner"):
            fm["owner"] = analysis["people"][key]["name"]
            store.log(f"{tid} owner → {fm['owner']} (from commits)")
            changed += 1

    # 2c. calculated fields (user- or agent-defined formulas)
    fdefs = store.schema().get("formulas") or {}
    if fdefs:
        kids, waits_ = relations.children(live), relations.waiting_on(live)
        bad = set()
        for tid_, (fm_, _) in live.items():
            env = formulas.task_env(fm_, [live[k][0] for k in kids.get(tid_, []) if k in live], waits_.get(tid_, []))
            for name_, spec in fdefs.items():
                try:
                    val = formulas.evaluate(spec["formula"], env)
                except formulas.FormulaError as e:
                    val = ""
                    bad.add(f"{name_}: {e}")
                env[name_] = val
                if fm_.get(name_) != val:
                    fm_[name_] = val
                    changed += 1
        report.warnings += [f"formula {b}" for b in sorted(bad)[:3]]

    # 3. schema evolution + persist
    schema = store.evolve_schema(tasks)
    for fm, body in tasks.values():
        if store.write_task(fm, body):
            changed += 1

    # 4. render
    dashboard.render(store, live, schema, known=set(tasks))
    insights.refresh(project, vault, live, schema, cfg, hist, analysis, store, report.warnings, gh)
    store.flush_log()

    # 5. push to external trackers
    waits = relations.waiting_on(live)
    for m in mirror_list:
        if m.name not in pulled and m.snapshot().get("rows"):
            continue                                  # could not read it; don't overwrite blindly
        try:
            mbase.push(m, live, schema, waits, report.warnings)
            if m.supports_publish:
                mbase.publish(m, insights.publishable(vault), force_publish)
            report.mirrors.append((m.name, m.where()))
        except M.MirrorError as e:
            report.warnings.append(f"{m.name}: {e} (will retry next time)")
    report.changed = changed
    report.tasks = live
    report.analysis, report.gh = analysis, gh
    return report


def sync(project, vault, use_agent=False, cfg=None):
    """Backward-compatible wrapper: returns (changed, tasks)."""
    r = sync_report(project, vault, use_agent, cfg)
    return r.changed, r.tasks
