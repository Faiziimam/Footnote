"""Cross-team awareness from git history: who did what, who owns what, where people might collide.

This is for shared visibility and handoffs, NOT for ranking people: there is deliberately no leaderboard.
"""
import datetime as dt
import re
from collections import Counter
from pathlib import Path
from .signals import ID, similarity
from .store import parse_ts, LABELS

BOT = re.compile(r"\[bot\]|dependabot|renovate|github-actions|^bot@|-bot@", re.I)
NOISE_FILES = re.compile(r"(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|poetry\.lock|Gemfile\.lock|\.min\.|^Tracker/|^\.footnote/)")
ROOTS = {"src", "app", "lib", "packages", "apps", "services", "pages", "components", "server", "client"}
KINDS = [("feature", r"^(feat|feature)\b|\b(add|added|adds|implement|implemented|create|created|build|built|introduce|new)\b"),
         ("fix", r"^fix\b|\b(fix|fixed|fixes|bug|patch|resolve|resolved|hotfix)\b"),
         ("docs", r"^docs?\b|\b(readme|documentation|docs)\b"), ("tests", r"^test\b|\b(tests?|spec)\b"),
         ("refactor", r"^(refactor|chore|style|perf|build|ci)\b|\b(refactor|cleanup|clean up|rename|move|bump|upgrade)\b")]


def parse_when(s):
    d = parse_ts(s)
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def norm_email(e):
    e = e.lower().strip()
    m = re.match(r"^\d+\+(.+)@users\.noreply\.github\.com$", e)
    return f"{m.group(1)}@github" if m else e


def area(path):
    parts = path.split("/")
    if len(parts) == 1:
        return "(root)"
    return f"{parts[0]}/{parts[1]}" if parts[0] in ROOTS and len(parts) > 2 else parts[0]


def kind(subject):
    s = subject.strip().lower()
    s = re.sub(r"\(.*?\)", "", s)
    for k, rx in KINDS:
        if re.search(rx, s):
            return k
    return "other"


def clean_subject(s):
    s = re.sub(r"^\w+(\(.+?\))?!?:\s*", "", s.strip())
    s = re.sub(r"\s*\(?\bT-\d{3,}\)?", "", s).strip(" -:")
    return s[:1].upper() + s[1:] if s else s


def link_tasks(c, tasks):
    ids = {t.upper() for t in ID.findall(c["subject"] + "\n" + c["body"])} & set(tasks)
    if not ids and not c["merge"]:
        for tid, (fm, _) in tasks.items():
            if fm["status"] != "done" and similarity(c["subject"], fm["title"].replace("Implement:", "")) >= 0.7:
                ids.add(tid)
    return ids


def grp(p):
    return " (%s)" % p["group"] if p.get("group") else ""


def analyze(history, tasks, cfg=None, now=None, window_days=7, github=None):
    cfg = (cfg or {}).get("team", {})
    aliases = {norm_email(k): norm_email(v) for k, v in cfg.get("aliases", {}).items()}
    groups = {g: {m.lower() for m in ms} for g, ms in cfg.get("groups", {}).items()}
    now = now or dt.datetime.now(dt.timezone.utc)
    since = now - dt.timedelta(days=window_days)
    names, people = {}, {}
    contrib, last_touch = {}, {}
    area_commits, file_people = {}, {}
    for c in history:
        key = aliases.get(norm_email(c["email"]), norm_email(c["email"]))
        names.setdefault(key, Counter())[c["author"]] += 1
        if BOT.search(c["author"] + " " + c["email"]) or key in {norm_email(x) for x in cfg.get("ignore", [])}:
            continue
        when = parse_when(c["when"])
        p = people.setdefault(key, {"key": key, "commits": 0, "recent": 0, "first": when, "last": when, "ai": 0,
                                    "areas": Counter(), "recent_areas": Counter(), "files": set(), "kinds": Counter(),
                                    "recent_kinds": Counter(), "tasks": Counter(), "recent_subjects": [], "repos": set()})
        p["commits"] += 1
        p["ai"] += c["ai"]
        p["first"], p["last"] = min(p["first"], when), max(p["last"], when)
        p["repos"].add(c["repo"])
        files = [f for f in c["files"] if not NOISE_FILES.search(f)]
        k = kind(c["subject"])
        if not c["merge"]:
            p["kinds"][k] += 1
        for f in files:
            a = area(f)
            p["areas"][a] += 1
            p["files"].add(f)
            area_commits.setdefault(a, Counter())[key] += 1
            if (now - when).days < 14:
                file_people.setdefault(f, {})[key] = max(file_people.get(f, {}).get(key, when), when)
        for tid in link_tasks(c, tasks):
            p["tasks"][tid] += 1
            contrib.setdefault(tid, Counter())[key] += 1
            last_touch[tid] = max(last_touch.get(tid, when), when)
        if when >= since and not c["merge"]:
            p["recent"] += 1
            p["recent_kinds"][k] += 1
            for f in files:
                p["recent_areas"][area(f)] += 1
            p["recent_subjects"].append((k, clean_subject(c["subject"])))
    for key, p in people.items():
        p["name"] = names[key].most_common(1)[0][0]
        p["group"] = next((g for g, ms in groups.items() if key in ms or p["name"].lower() in ms), "")
    owners = {tid: cnt.most_common(1)[0][0] for tid, cnt in contrib.items()}

    overlaps = []
    for f, who in file_people.items():
        if len(who) > 1:
            overlaps.append({"file": f, "people": sorted(who), "area": area(f)})
    by_area = {}
    for o in overlaps:
        by_area.setdefault(o["area"], []).append(o)
    overlaps = [{"area": a, "people": sorted({p for o in os_ for p in o["people"]}), "files": [o["file"] for o in os_][:5]}
                for a, os_ in sorted(by_area.items(), key=lambda kv: -len(kv[1]))]

    stale = []
    for tid, (fm, _) in tasks.items():
        if fm["status"] == "active":
            lt = last_touch.get(tid)
            days = (now - lt).days if lt else None
            ref = lt or (parse_when(fm["started"]) if fm.get("started") else None)
            if ref and (now - ref).days >= 7:
                stale.append({"id": tid, "title": fm["title"], "days": (now - ref).days,
                              "owner": fm.get("owner") or (people[owners[tid]]["name"] if tid in owners else "")})
    bus = []
    if len(people) > 1:
        for a, cnt in area_commits.items():
            total = sum(cnt.values())
            top, n = cnt.most_common(1)[0]
            if total >= 6 and n / total >= 0.85 and a != "(root)":
                bus.append({"area": a, "person": people[top]["name"], "share": round(100 * n / total)})
    from . import github as gh_mod
    reviews = gh_mod.review_counts(github, people)
    for k, n in reviews.items():
        people[k]["reviews"] = n
    return {"github": github, "people": people, "owners": owners, "contrib": contrib, "overlaps": overlaps, "stale": stale,
            "bus": sorted(bus, key=lambda b: -b["share"]), "since": since, "now": now, "window": window_days,
            "group_names": sorted(groups)}


def person_summary(p, tasks, owners, recent=True, label="in the last 7 days"):
    n = p["recent"] if recent else p["commits"]
    kinds = p["recent_kinds"] if recent else p["kinds"]
    areas = p["recent_areas"] if recent else p["areas"]
    span = label if recent else "overall"
    if not n:
        return f"No commits {span}."
    top = [a for a, _ in areas.most_common(3)]
    bits = [f"{n} commit{'s' if n != 1 else ''} {span}"]
    if top:
        bits.append("mostly in " + ", ".join(f"`{a}`" for a in top))
    parts = []
    if kinds["feature"]:
        parts.append(f"{kinds['feature']} new thing{'s' if kinds['feature'] != 1 else ''}")
    if kinds["fix"]:
        parts.append(f"{kinds['fix']} fix{'es' if kinds['fix'] != 1 else ''}")
    for k, w in (("docs", "docs"), ("tests", "tests"), ("refactor", "cleanup")):
        if kinds[k]:
            parts.append(f"{kinds[k]} {w}")
    s = bits[0] + (", " + bits[1] if len(bits) > 1 else "")
    if parts:
        s += " — " + ", ".join(parts)
    ex = [t for k, t in reversed(p["recent_subjects"]) if k == "feature"][:2] if recent else []
    if ex:
        s += ". E.g. " + "; ".join(f"“{e}”" for e in ex)
    return s + "."


def tasks_of(key, tasks, owners):
    mine = {t: fm for t, (fm, _) in tasks.items()
            if fm.get("owner_key") == key or (owners.get(t) == key and not fm.get("owner"))}
    return mine


def owner_name(fm, analysis, tid):
    if fm.get("owner"):
        return fm["owner"]
    k = analysis["owners"].get(tid)
    return analysis["people"][k]["name"] if k in analysis["people"] else ""


def ago(d, now):
    n = (now - d).days
    return "today" if n == 0 else "yesterday" if n == 1 else f"{n} days ago"


def match_person(analysis, q):
    q = q.lower().strip()
    hits = [p for p in analysis["people"].values() if q in p["name"].lower() or q in p["key"]]
    exact = [p for p in hits if q in (p["name"].lower(), p["key"])]
    return exact or hits


def whois(analysis, tasks, query):
    q = query.strip()
    now = analysis["now"]
    if re.fullmatch(r"T-\d{3,}", q, re.I):
        tid = q.upper()
        if tid not in tasks:
            return f"There is no task {tid}."
        fm = tasks[tid][0]
        who = analysis["contrib"].get(tid, Counter())
        lines = [f"{tid} “{fm['title']}” — {LABELS[fm['status']]}",
                 f"Owner: {owner_name(fm, analysis, tid) or 'nobody yet'}"]
        if who:
            lines.append("Worked on by: " + ", ".join(f"{analysis['people'][k]['name']} ({n} commits)" for k, n in who.most_common()))
        return "\n".join(lines)
    hits = match_person(analysis, q)
    if hits:
        out = []
        for p in hits[:3]:
            mine = [f"{t} “{fm['title']}” ({LABELS[fm['status']]})" for t, (fm, _) in sorted(tasks.items())
                    if owner_name(fm, analysis, t) == p["name"] and fm["status"] != "done"]
            out.append(f"{p['name']}{grp(p)} — last active {ago(p['last'], now)}\n"
                       f"  Recently: {person_summary(p, tasks, analysis['owners'])}\n"
                       f"  Knows best: {', '.join(f'`{a}`' for a, _ in p['areas'].most_common(4)) or 'n/a'}\n"
                       f"  Open tasks: {'; '.join(mine) or 'none'}")
        return "\n\n".join(out)
    # a folder or file: who has worked on it?
    cnt, last = Counter(), {}
    for k, p in analysis["people"].items():
        for a, n in p["areas"].items():
            if q.strip("/") in a or a.startswith(q.strip("/")):
                cnt[k] += n
                last[k] = p["last"]
    if cnt:
        return f"People who have worked on `{q}`:\n" + "\n".join(
            f"  - {analysis['people'][k]['name']}: {n} change{'s' if n != 1 else ''}, last active {ago(last[k], now)}"
            for k, n in cnt.most_common(5))
    return f"I couldn't find a person, task or area matching “{q}”."


def catchup(analysis, tasks, journal_entries, since, now=None):
    now = now or analysis["now"]
    out = [f"# Catch-up since {since.strftime('%a %d %b %Y')}", ""]
    done = [(fm, t) for t, (fm, _) in tasks.items() if fm.get("done") and parse_when(fm["done"]) >= since]
    started = [(fm, t) for t, (fm, _) in tasks.items() if fm["status"] == "active" and fm.get("started")
               and parse_when(fm["started"]) >= since]
    blocked = [(fm, t) for t, (fm, _) in tasks.items() if fm["status"] == "blocked"]
    if done:
        out += ["## Finished", ""] + [f"- {t} “{fm['title']}”" + (f" — {owner_name(fm, analysis, t)}" if owner_name(fm, analysis, t) else "")
                                       for fm, t in done] + [""]
    if started:
        out += ["## Started", ""] + [f"- {t} “{fm['title']}”" + (f" — {owner_name(fm, analysis, t)}" if owner_name(fm, analysis, t) else "")
                                      for fm, t in started] + [""]
    if blocked:
        out += ["## Blocked", ""] + [f"- {t} “{fm['title']}”" for fm, t in blocked] + [""]
    ppl = [p for p in sorted(analysis["people"].values(), key=lambda x: x["name"].lower()) if p["recent"]]
    if ppl:   # `analysis` was built for exactly this window, so "recent" == since the cut-off
        out += ["## What people did", ""] + [
            f"- **{p['name']}**{grp(p)}: {person_summary(p, tasks, analysis['owners'], label='since ' + since.strftime('%d %b'))}"
            for p in ppl] + [""]
    new = [e for e in journal_entries if parse_when(e["ts"]) >= since and e["kind"] != "resolved"]
    for k, title in (("decision", "Decisions made"), ("risk", "New risks"), ("learning", "Learnings"),
                     ("architecture", "Architecture changes"), ("milestone", "Milestones")):
        items = [e for e in new if e["kind"] == k]
        if items:
            out += [f"## {title}", ""] + [f"- {e['text']}" for e in items] + [""]
    if analysis["overlaps"]:
        out += ["## Heads-up: possible overlap", ""] + [
            f"- `{o['area']}` was changed by {', '.join(analysis['people'][p]['name'] for p in o['people'])} recently — check you're not duplicating work"
            for o in analysis["overlaps"][:5]] + [""]
    if analysis["stale"]:
        out += ["## May be stalled", ""] + [f"- {s['id']} “{s['title']}” — no activity for {s['days']} days"
                                           + (f" ({s['owner']})" if s["owner"] else "") for s in analysis["stale"]] + [""]
    if len(out) == 2:
        out.append("Nothing new recorded in this period.")
    return "\n".join(out)


def render(vault, analysis, tasks):
    vault = Path(vault)
    now = analysis["now"]
    ppl = sorted(analysis["people"].values(), key=lambda p: p["name"].lower())
    o = ["# Team", "", "_Who is doing what — built from commit history, for visibility and handoffs "
         f"(not for ranking). Refreshed {now.strftime('%Y-%m-%d')}._", ""]
    if not ppl:
        o.append("_No commit history yet._")
    else:
        o += ["| Person | Team | Last active | Last 7 days | Knows best | Open tasks |", "|---|---|---|---|---|---|"]
        for p in ppl:
            mine = [t for t, (fm, _) in sorted(tasks.items()) if owner_name(fm, analysis, t) == p["name"] and fm["status"] != "done"]
            o.append(f"| [[{p['name']}]] | {p['group']} | {ago(p['last'], now)} | {p['recent']} commits | "
                     f"{', '.join(a for a, _ in p['areas'].most_common(3))} | {', '.join(mine[:5])} |")
        o.append("")
        o += ["## This week in plain words", ""] + [f"- **{p['name']}** — {person_summary(p, tasks, analysis['owners'])}" for p in ppl if p["recent"]]
        if not any(p["recent"] for p in ppl):
            o.append("_No commits in the last 7 days._")
        o.append("")
    if analysis["overlaps"]:
        o += ["## Possible overlap (same files, last 14 days)", ""] + [
            f"- `{x['area']}` — {', '.join(analysis['people'][k]['name'] for k in x['people'])} (e.g. {', '.join(f'`{f}`' for f in x['files'][:2])})"
            for x in analysis["overlaps"][:10]] + [""]
    if analysis["stale"]:
        o += ["## May be stalled", ""] + [f"- {s['id']} “{s['title']}” — {s['days']} days without activity"
                                          + (f" ({s['owner']})" if s["owner"] else "") for s in analysis["stale"]] + [""]
    gh = analysis.get("github")
    if gh:
        from . import github as gh_mod
        wait = gh_mod.waiting_prs(gh, now)
        if wait:
            o += ["## Pull requests waiting on someone", ""] + [
                f"- #{w['number']} {w['title']} — {w['user']}, {w['age']} days, {w['state']}" for w in wait] + [""]
        revs = [(p["name"], p.get("reviews", 0)) for p in ppl if p.get("reviews")]
        if revs:
            o += ["## Reviews given (recent PRs)", "", ", ".join(f"{n}: {c}" for n, c in sorted(revs, key=lambda x: x[0])), ""]
    if analysis["bus"]:
        o += ["## Knowledge concentrated in one person", ""] + [
            f"- `{b['area']}` — {b['share']}% of changes by {b['person']}; consider pairing or documenting" for b in analysis["bus"]] + [""]
    (vault / "Team.md").write_text("\n".join(o) + "\n", encoding="utf-8")
    pdir = vault / "People"
    for p in ppl:
        pdir.mkdir(exist_ok=True)
        safe = re.sub(r"[^\w .\-]", "", p["name"]).strip() or p["key"]
        mine = [(t, fm) for t, (fm, _) in sorted(tasks.items()) if owner_name(fm, analysis, t) == p["name"]]
        body = [f"# {p['name']}", "", f"- Active {p['first'].strftime('%Y-%m-%d')} → {p['last'].strftime('%Y-%m-%d')}, "
                f"{p['commits']} commits overall" + (f", {p['ai']} with an AI co-author" if p["ai"] else ""),
                f"- Repos: {', '.join(sorted(p['repos']))}", "", "## Recently", "", person_summary(p, tasks, analysis["owners"]), "",
                "## Knows best", ""] + [f"- `{a}` ({n} changes)" for a, n in p["areas"].most_common(8)] + ["", "## Tasks", ""] + \
               ([f"- [[{t}]] {fm['title']} — {LABELS[fm['status']]}" for t, fm in mine] or ["_none_"])
        (pdir / f"{safe}.md").write_text("\n".join(body) + "\n", encoding="utf-8")
