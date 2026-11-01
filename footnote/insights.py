"""Everything beyond tasks: architecture, evidence, timeline, team, numbers, journal and the project report."""
import datetime as dt
import json
import re
from collections import Counter
from pathlib import Path
from . import llm, finance, roadmap, activity, architecture, journal, metrics, profiles, report, team, signals, config
from .mirrors.base import MirrorError
from .store import LABELS, now, iso


def project_info(vault, project_dir, arch=None):
    p = Path(vault) / "_project.json"
    info = {}
    try:
        info = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    kind = profiles.match_kind(info.get("kind", "")) if info.get("kind") else None
    if not kind and arch:
        names = " ".join(s["name"].lower() for s in arch["stack"])
        for k, keys in profiles.DETECT_DEPS.items():
            if any(x.split("/")[-1].strip("@") in names for x in keys):
                kind = k
                break
    return {"vault": str(vault), "name": info.get("name") or Path(project_dir).resolve().name, "kind": kind or info.get("kind") or "other",
            "goal": info.get("goal", ""), "declared": bool(info.get("kind"))}


def save_project(vault, name=None, kind=None, goal=None):
    p = Path(vault) / "_project.json"
    try:
        cur = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cur = {}
    for k, v in (("name", name), ("kind", kind), ("goal", goal)):
        if v:
            cur[k] = v
    Path(vault).mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cur, indent=1), encoding="utf-8")
    return cur


def write_if_changed(path, text):
    from .store import atomic_write
    if not path.exists() or path.read_text(encoding="utf-8") != text:
        atomic_write(path, text)


PUBLISH = [("Project Report", "Project Report.md"), ("Finance", "Finance.md"), ("Roadmap", "Roadmap.md"), ("Team", "Team.md"), ("Metrics", "Metrics.md"),
           ("Journal", "Journal.md"), ("Architecture", "Architecture.md")]


def publishable(vault):
    out = {}
    for name, f in PUBLISH:
        p = Path(vault) / f
        if p.exists():
            out[name] = p.read_text(encoding="utf-8")
    return out


def snapshot_prior(vault):
    """The most recent weekly snapshot that is at least 6 days old (for the week-on-week line)."""
    try:
        snaps = json.loads((Path(vault) / "_snapshots.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    today = dt.date.today()
    old = [d for d in snaps if (today - dt.date.fromisoformat(d)).days >= 6]
    return {"date": max(old), **snaps[max(old)]} if old else None


def snapshot_weekly(vault, text, tasks):
    """Keep a copy of the report every 7 days: Reports/YYYY-MM-DD.md, plus a tiny progress history."""
    from .store import atomic_write
    vault = Path(vault)
    p = vault / "_snapshots.json"
    try:
        snaps = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        snaps = {}
    today = dt.date.today()
    if snaps and (today - dt.date.fromisoformat(max(snaps))).days < 7:
        return
    fms = [fm for fm, _ in tasks.values()]
    done = sum(1 for f in fms if f["status"] == "done")
    snaps[today.isoformat()] = {"pct": round(100 * done / len(fms)) if fms else 0, "done": done, "total": len(fms)}
    (vault / "Reports").mkdir(exist_ok=True)
    atomic_write(vault / "Reports" / f"{today.isoformat()}.md", text)
    atomic_write(p, json.dumps(snaps, indent=1))


def built_md(vault, hist, tasks, analysis):
    ev = {}
    for c in hist:
        if c["merge"]:
            continue
        for tid in team.link_tasks(c, tasks):
            ev.setdefault(tid, []).append(c)
    o = ["# What was built, task by task", "", "_Evidence from the project history: which commits and files delivered each task._", ""]
    if not ev:
        o.append("_No commits are linked to tasks yet. Put the task ID in commit messages, e.g. “Add hero (T-003)”._")
    for tid in sorted(ev):
        fm = tasks[tid][0]
        cs = ev[tid]
        files = Counter(f for c in cs for f in c["files"] if not team.NOISE_FILES.search(f))
        o += [f"## [[{tid}]] {fm['title']} — {LABELS[fm['status']]}", "",
              f"Owner: {team.owner_name(fm, analysis, tid) or '—'} · {len(cs)} commit{'s' if len(cs) != 1 else ''} · "
              f"{cs[0]['when'][:10]} → {cs[-1]['when'][:10]}", ""]
        o += [f"- {c['when'][:10]} · {c['author']}: {c['subject']}" for c in cs[-6:]]
        if files:
            o += ["", "Files: " + ", ".join(f"`{f}`" for f, _ in files.most_common(8))]
        o.append("")
    return "\n".join(o)


CL = re.compile(r"^- (\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}) — (.*)$")


def timeline_md(vault, hist, entries):
    ev = []
    for c in hist:
        if not c["merge"]:
            ev.append((c["when"][:16].replace("T", " "), f"🔨 {c['author']}: {c['subject']}"))
    cl = Path(vault) / "Changelog.md"
    if cl.exists():
        for line in cl.read_text(encoding="utf-8").splitlines():
            m = CL.match(line)
            if m and " created:" not in m.group(3) and "+relation" not in m.group(3) and "-relation" not in m.group(3):
                ev.append((f"{m.group(1)} {m.group(2)}", f"✔ {m.group(3)}"))
    icon = {"decision": "🧭", "risk": "⚠", "learning": "💡", "milestone": "🏁", "architecture": "🏗", "note": "📝", "issue": "🐞"}
    for e in entries:
        if e["kind"] != "resolved":
            ev.append((e["ts"][:16].replace("T", " "), f"{icon.get(e['kind'], '•')} {e['kind'].title()}: {e['text']}"))
    for a in activity.read(vault):
        n = a["added"] + a["modified"] + a["deleted"]
        ev.append((a["ts"][:16].replace("T", " "), f"📁 {n} file{'s' if n != 1 else ''} changed in {', '.join('`' + x + '`' for x in a['areas'])}"
                   f" (e.g. {', '.join(a['sample'][:2])})"))
    ev.sort()
    ev = ev[-500:]
    o = ["# Timeline", "", "_Everything that happened, since the beginning (latest 500 events). "
         "🔨 code · ✔ task changes · 🧭 decisions · 🏗 architecture · 🏁 milestones · ⚠ risks_", ""]
    day = None
    for ts, text in ev:
        if ts[:10] != day:
            day = ts[:10]
            o += ["", f"### {day}", ""]
        o.append(f"- {ts[11:]} {text}")
    return "\n".join(o) + "\n"


def refresh(project, vault, tasks, schema, cfg, hist, analysis, store, warnings, gh=None):
    vault = Path(vault)
    # 1. architecture, with change detection -> journal
    arch = architecture.scan(project, vault)
    prev = architecture.load(vault)
    for line in architecture.diff(prev, arch):
        journal.add(vault, "architecture", line, source="auto")
    if prev != json.loads(json.dumps(arch)):
        architecture.save(vault, arch)
    architecture.render(vault, arch) if not (vault / "Architecture.md").exists() or prev != json.loads(json.dumps(arch)) else None

    for src_file, line in architecture.read_adrs(project):
        journal.add(vault, "decision", line, source=f"adr:{src_file}")

    # 2. connected number sources (Stripe...)
    for src in cfg.get("sources", []):
        pull = metrics.PULLS.get(src.get("type"))
        if pull:
            try:
                n = pull(vault, src)
                if n:
                    store.log(f"{src['type'].title()}: {n} new figure(s) imported")
            except MirrorError as e:
                warnings.append(f"{src['type'].title()}: {e} (will retry next time)")

    # 3. everything else is rendered from what we now know
    entries = journal.read(vault)
    journal.render(vault)
    metrics.render(vault, cfg)
    team.render(vault, analysis, tasks)
    if finance.has_data(vault, metrics.read(vault)):
        write_if_changed(vault / "Finance.md", finance.render(vault, cfg))
    if roadmap.facts(tasks)["any"]:
        write_if_changed(vault / "Roadmap.md", roadmap.render(tasks))
    write_if_changed(vault / "Built.md", built_md(vault, hist, tasks, analysis))
    write_if_changed(vault / "Timeline.md", timeline_md(vault, hist, entries))
    info = project_info(vault, project, arch)
    prior = snapshot_prior(vault)
    mets = metrics.summarize(metrics.read(vault), None, *metrics.settings(cfg))
    nutshell = llm.narrative(vault, cfg, project, llm.facts_for(tasks, mets, journal.open_risks(entries))) if llm.enabled(cfg, "narrative") else ""
    text = report.build(info, tasks, schema, arch, entries, mets, analysis, hist, "all", gh, prior, nutshell)
    write_if_changed(vault / "Project Report.md", text)
    snapshot_weekly(vault, text, tasks)
    return arch, info
