"""The project report: one generated document for everyone who needs to know where things stand.

Sections are tagged by audience so the same facts can be shown as a manager view, a plain-language
view for non-developers, or a developer view. Sections with no data are simply left out.
"""
import datetime as dt
from pathlib import Path
from . import metrics as M, profiles, team, journal
from .store import LABELS
from .dashboard import bar
from .relations import waiting_on

AUDIENCES = {"all": None, "manager": {"glance", "schedule", "figures", "risks", "team", "handover"},
             "founder": {"glance", "schedule", "figures", "risks", "team", "handover"},
             "everyone": {"glance", "schedule", "built", "figures", "decisions"},
             "developer": {"glance", "schedule", "tech", "team", "decisions", "risks", "handover"}}


def _d(s):
    try:
        return team.parse_when(s)
    except Exception:
        return None


def build(info, tasks, schema, arch, entries, mets, analysis, hist, audience="all", gh=None, prior=None, nutshell=""):
    now = analysis["now"] if analysis else dt.datetime.now(dt.timezone.utc)
    want = AUDIENCES.get(audience, None)
    fms = [fm for fm, _ in tasks.values()]
    total, done = len(fms), sum(1 for f in fms if f["status"] == "done")
    pct = round(100 * done / total) if total else 0
    sec = {}

    # ---------- at a glance
    g = [f"_{nutshell}_  _(written by AI from the facts below)_", ""] if nutshell else []
    c = {s: sum(1 for f in fms if f["status"] == s) for s in LABELS}
    g.append(f"**Progress:** {bar(pct)} {pct}% — {done} of {total} tasks done · {c['active']} in progress · "
             f"{c['blocked']} blocked · {c['todo']} not started" if total else "**No tasks yet.**")
    if prior and total:
        dd = done - prior["done"]
        g.append(f"**Since {prior['date']}:** {prior['pct']}% → {pct}% ({'+' if dd >= 0 else ''}{dd} task{'s' if abs(dd) != 1 else ''} done"
                 f"{'' if total == prior['total'] else ', scope ' + str(prior['total']) + ' → ' + str(total) + ' tasks'}).")
    dates = [_d(f["done"]) for f in fms if f.get("done")]
    dates = [x for x in dates if x]
    d7 = sum(1 for x in dates if (now - x).days < 7)
    p7 = sum(1 for x in dates if 7 <= (now - x).days < 14)
    d28 = sum(1 for x in dates if (now - x).days < 28)
    if dates:
        g.append(f"**Momentum:** {d7} task{'s' if d7 != 1 else ''} finished in the last 7 days (previous week: {p7}).")
    left = total - done
    if d28 >= 3 and left:
        weeks = left / (d28 / 4)
        g.append(f"**Rough estimate:** at the last 4 weeks' pace, the remaining {left} tasks take about "
                 f"{weeks:.0f} week{'s' if round(weeks) != 1 else ''}. (A guide, not a promise: tasks differ in size.)")
    if not hist:
        from . import activity
        acts = activity.read(Path(info.get("vault", ".")))
        if acts:
            g.append(f"**Activity:** {len(acts)} change batches since {acts[0]['ts'][:10]}, last {team.ago(_d(acts[-1]['ts']), now)}.")
    if hist:
        first, last = _d(hist[0]["when"]), _d(hist[-1]["when"])
        g.append(f"**History:** started {first:%d %b %Y}, last change {team.ago(last, now)}, {len(hist)} commits.")
    recent = sorted([(f.get("done"), f) for f in fms if f.get("done")], key=lambda x: x[0], reverse=True)[:5]
    if recent:
        g += ["", "**Recently finished:** " + "; ".join(f"{f['title']} ({d[:10]})" for d, f in recent)]
    waits = waiting_on(tasks)
    ready = [f for f in fms if f["status"] == "todo" and f["id"] not in waits][:5]
    if ready:
        g.append("**Up next:** " + "; ".join(f"{f['id']} {f['title']}" for f in ready))
    blocked = [f for f in fms if f["status"] == "blocked"]
    if blocked:
        g.append("**Blocked:** " + "; ".join(f"{f['id']} {f['title']}" for f in blocked))
    if gh:
        ci = gh.get("ci", {})
        if ci.get("state") == "failing":
            g.insert(1, f"**⚠ Build is failing on `{ci['branch']}`:** {', '.join(ci['failing'][:4])}")
        elif ci.get("state") == "passing":
            g.insert(1, f"**Build:** passing on `{ci['branch']}`")
        from . import github as gh_mod
        wait = gh_mod.waiting_prs(gh, now)
        if wait:
            g.append("**Waiting on review/merge:** " + "; ".join(f"#{w['number']} {w['title']} ({w['state']}, {w['age']}d)" for w in wait[:4]))
    sec["glance"] = ("At a glance", g)

    # ---------- schedule
    from . import roadmap as rm
    rf = rm.facts(tasks)
    sc = []
    if rf["overdue"]:
        sc.append(f"- ⚠ **Overdue ({len(rf['overdue'])}):** " + "; ".join(f"{x['title']} (due {x['due']})" for x in rf["overdue"][:5]))
    if rf["soon"]:
        sc.append("- **Due in the next 14 days:** " + "; ".join(f"{x['title']} ({x['due']})" for x in rf["soon"][:6]))
    if rf["projected"]:
        sc.append(f"- **Projected finish:** about {rf['projected'].isoformat()} (remaining estimate {rf['left']:g} days at {rf['velocity_per_week']:g} days/week)")
    sec["schedule"] = ("Schedule", sc)

    # ---------- what's built
    b = []
    epics = {}
    for f in fms:
        epics.setdefault(f["epic"], []).append(f)
    for e, fs in sorted(epics.items()):
        dn = [f for f in fs if f["status"] == "done"]
        ip = [f for f in fs if f["status"] in ("active", "blocked")]
        b.append(f"**{e}** — {bar(round(100 * len(dn) / len(fs)))} {len(dn)}/{len(fs)}")
        b += [f"  - ✔ {f['title']}" for f in dn[:12]] + [f"  - … {f['title']} ({LABELS[f['status']]})" for f in ip[:6]]
    sec["built"] = ("What has been built", b)

    # ---------- figures
    fg = []
    kind = profiles.match_kind(info["kind"]) or "other"
    defs = {m[0]: m for m in profiles.PROFILES[kind]["metrics"]}
    for name in list(defs) + [n for n in mets if n not in defs]:
        if name in mets:
            m = mets[name]
            main = f"{M.fmt(m['latest'])}{' ' + m['unit'] if m['unit'] else ''}" + (" in the last 30 days" if m["kind"] == "sum" else " (latest)")
            trend = ""
            if m["kind"] == "sum" and m["prev7"]:
                ch = (m["last7"] - m["prev7"]) / m["prev7"] * 100
                trend = f" · this week {M.fmt(m['last7'])} ({'+' if ch >= 0 else ''}{ch:.0f}% vs last week)"
            warn = (" ⚠ not included: " + ", ".join(f"{M.fmt(v)} {u}" for u, v in m["excluded"].items()) +
                    " — different currency; set exchange rates with `footnote currency USD --rate EUR=1.08`") if m["excluded"] else ""
            fg.append(f"- **{defs[name][1] if name in defs else name.replace('_', ' ').title()}:** {main}{trend} {M.spark(m['series'])}{warn}")
        else:
            fg.append(f"- {defs[name][1]}: _not connected yet — {defs[name][4]}_")
    from . import finance as fin
    vault_dir = info.get("vault")
    if vault_dir:
        ag = fin.aging(vault_dir)
        if ag["open"]:
            fg.append(f"- **Unpaid invoices:** {len(ag['open'])} totalling {M.fmt(ag['total'])}" +
                      (f" — ⚠ {len(ag['overdue'])} overdue ({M.fmt(ag['overdue_total'])})" if ag["overdue"] else ""))
    for label, v, u in M.derived(mets):
        fg.append(f"- **{label}:** {M.fmt(v, u)}")
    sec["figures"] = ("Business figures", fg)

    # ---------- decisions / risks
    ds = [f"- {e['ts'][:10]} · {e['text']}" for e in entries if e["kind"] in ("decision", "learning", "milestone")][-12:]
    sec["decisions"] = ("Decisions, learnings & milestones", ds)
    rk = journal.open_risks(entries)
    sec["risks"] = ("Open risks & issues", [f"- {e['ts'][:10]} · {e['text']}" for e in rk])

    # ---------- technical
    t = []
    if arch and arch["code_files"]:
        for kk in sorted({s["kind"] for s in arch["stack"]}):
            t.append(f"- **{kk.title()}:** " + ", ".join(s["name"] for s in arch["stack"] if s["kind"] == kk))
        t.append(f"- **Size:** {arch['code_files']} code files; {len(arch['pages'])} pages, {len(arch['api'])} API routes, "
                 f"{len(arch['models'])} data models, {len(arch['components'])} components")
        if arch["pages"]:
            t.append("- **Pages:** " + ", ".join(f"`{p}`" for p in arch["pages"][:12]))
        if arch["api"]:
            t.append("- **API:** " + ", ".join(f"`{p}`" for p in arch["api"][:10]))
        if arch["models"]:
            t.append("- **Data:** " + ", ".join(arch["models"][:12]))
        if arch["scripts"]:
            t.append("- **Run it:** " + ", ".join(f"`{k}`" for k in list(arch["scripts"])[:6]))
        t.append("- Full detail: [[Architecture]] · per-task evidence: [[Built]] · history: [[Timeline]]")
    sec["tech"] = ("Technical overview", t)

    # ---------- team
    tm = []
    if analysis and analysis["people"]:
        for p in sorted(analysis["people"].values(), key=lambda x: -x["last"].timestamp()):
            tm.append(f"- **{p['name']}** (last active {team.ago(p['last'], now)}): {team.person_summary(p, tasks, analysis['owners'])}")
        for o in analysis["overlaps"][:3]:
            tm.append(f"- ⚠ Overlap: `{o['area']}` touched by {', '.join(analysis['people'][k]['name'] for k in o['people'])}")
        for s in analysis["stale"][:5]:
            tm.append(f"- ⚠ {s['id']} “{s['title']}” has had no activity for {s['days']} days")
    sec["team"] = ("Team", tm)

    # ---------- handover checklist
    h = []

    def chk(ok, good, bad):
        h.append(f"- {'✅' if ok else '⚠'} {good if ok else bad}")
    if total:
        chk(left == 0, "All planned tasks are done", f"{left} tasks are not finished yet")
    if gh and gh.get("ci", {}).get("state") in ("passing", "failing"):
        chk(gh["ci"]["state"] == "passing", "Build is passing", f"Build is failing on {gh['ci']['branch']}: {', '.join(gh['ci']['failing'][:3])}")
    if any(f.get("due") for f in fms):
        chk(not rf["overdue"], "Nothing is overdue", f"{len(rf['overdue'])} task(s) are past their due date")
    chk(not blocked, "Nothing is blocked", f"{len(blocked)} task(s) blocked: {', '.join(f['id'] for f in blocked)}")
    chk(not rk, "No open risks", f"{len(rk)} open risk(s) — resolve or accept them before handover")
    if any(e["kind"] == "decision" for e in entries) or total:
        chk(any(e["kind"] == "decision" for e in entries), "Key decisions are recorded",
            "No decisions recorded — future you will wonder why things were built this way")
    if arch and arch["code_files"]:
        tl = arch["tooling"]
        chk(tl.get("readme"), "README exists", "No README — add how to run and deploy it")
        chk(tl.get("tests"), "Automated tests exist", "No automated tests found")
        chk(bool(tl.get("deploy") or tl.get("docker")), "Deployment is configured", "No deployment configuration found")
        if arch["env"]:
            chk(True, f"Required settings are documented ({len(arch['env'])} variables in .env.example)", "")
    if defs:
        chk(any(n in mets for n in defs), "Business figures are being recorded",
            "No business figures yet — see “Business figures” above for how to connect them")
    if analysis and len(analysis["people"]) > 1:
        un = [f for f in fms if f["status"] == "active" and not team.owner_name(f, analysis, f["id"])]
        chk(not un, "Every task in progress has an owner", f"{len(un)} task(s) in progress have no owner")
        chk(not analysis["bus"], "Knowledge is spread across the team",
            "Knowledge concentrated: " + "; ".join(f"{x['person']} in `{x['area']}`" for x in analysis["bus"][:3]))
    if hist:
        humans = [c for c in hist if not c["merge"] and (now - team.parse_when(c["when"])).days < 30]
        if humans:
            lk = sum(1 for c in humans if not team.link_tasks(c, tasks))
            chk(lk / len(humans) <= 0.4, "Most recent work is linked to tasks",
                f"{lk} of {len(humans)} recent commits are not linked to any task (put the task ID in commit messages)")
    sec["handover"] = ("Handover checklist", h)

    order = ["glance", "schedule", "built", "figures", "decisions", "risks", "tech", "team", "handover"]
    heading = {"glance": "For everyone", "schedule": "For founders & managers", "built": "For everyone", "figures": "For founders & managers",
               "decisions": "For everyone", "risks": "For founders & managers", "tech": "For developers",
               "team": "For everyone working together", "handover": "Before you call it done"}
    out = [f"# {info['name']} — project report", "",
           f"_{info['kind'].title()}{' · ' + info['goal'] if info['goal'] else ''} · generated {now:%d %b %Y}. "
           f"Updates itself; do not edit._", ""]
    for k in order:
        title, lines = sec[k]
        if (want is not None and k not in want) or not lines:
            continue
        out += [f"## {title}" + (f"  _({heading[k]})_" if audience == "all" else ""), ""] + lines + [""]
    return "\n".join(out)
