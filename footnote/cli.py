import argparse
import json
import sys
from pathlib import Path
from . import config, setup, connect as connect_mod
from .api import Tracker, TrackerError
from .store import LABELS



def say(msg=""):
    print(msg)


def _report(r, tr):
    say(f"Done. {len(r.tasks)} tasks, {sum(1 for f, _ in r.tasks.values() if f['status'] == 'done')} finished.")
    say(f"Notes folder: {tr.vault}")
    for name, where in r.mirrors:
        say(f"Synced with {name}: {where}")
    for w in r.warnings:
        say(f"⚠ {w}")


def cmd_sync(a, tr):
    if a.quiet:                      # hooks: never block or disturb the AI tool
        tr.lock_timeout = 20.0
        try:
            tr.sync(use_agent=True if a.agent else None)
        except Exception as e:
            import traceback
            from . import log
            for l in traceback.format_exc().splitlines()[-6:]:
                log.write(tr.project, "debug", l)
            log.write(tr.project, "error", f"hook sync failed: {type(e).__name__}: {e}")
        return 0
    r = tr.sync(use_agent=True if a.agent else None)
    if not a.quiet:
        _report(r, tr)
    return 0


def cmd_status(a, tr):
    ts = tr.tasks()
    if not ts:
        say("No tasks yet. Add one with:  footnote add \"My first task\"")
    for t in ts:
        wait = f"  (waiting on {', '.join(t['waiting_on'])})" if t["waiting_on"] else ""
        say(f"{t['id']}  {t['status_label']:<12} {t['epic']} :: {t['title']}{wait}")
    return 0


def cmd_say(a, tr):
    for r in tr.say(" ".join(a.text), who="cli"):
        say(("✓ " if r["ok"] else "? ") + r["message"])
    return 0


def cmd_add(a, tr):
    tid = tr.add_task(" ".join(a.title), a.epic, a.parent, a.depends_on or (), who="cli")
    say(f"Added {tid}")
    return 0


def cmd_set(a, tr):
    tid = tr.set_status(a.id, " ".join(a.status), who="cli")
    say(f"{tid} updated.")
    return 0


def cmd_link(a, tr):
    tr.link(a.id, a.type, a.target, a.remove)
    say("Done.")
    return 0


def cmd_add_tracker(a, tr):
    opts = dict(kv.split("=", 1) for kv in (a.opt or []))
    setup.add_tracker(tr.project, a.type, **opts)
    r = Tracker(tr.project).sync()
    _report(r, tr)
    if a.type in ("notion", "gsheets", "sheets"):
        say("\nTeam tip: everyone on the team runs `footnote add-tracker` pointing at this SAME "
            f"{'Notion database' if a.type == 'notion' else 'sheet'}, and keeps Tracker/ out of git "
            "(add `Tracker/` and `.footnote/` to .gitignore). The shared tracker is then the single source of truth.")
    return 0


def cmd_connect(a, tr):
    wrote, notes = connect_mod.connect(a.tool, tr.project)
    for w in wrote:
        say(f"✓ wrote {w}")
    for n in notes:
        say("\n" + n)
    return 0


def cmd_install_hook(a, tr):
    """Claude Code: sync after commands and when Claude stops."""
    try:
        cmd = connect_mod.hook_command(tr.project)
    except ValueError as e:
        raise TrackerError(str(e))
    p = tr.project / ".claude" / "settings.json"
    p.parent.mkdir(exist_ok=True)
    cfg = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    hook = {"type": "command", "command": cmd}
    for event, matcher in (("PostToolUse", "Bash"), ("Stop", None)):
        entry = {"hooks": [hook]}
        if matcher:
            entry["matcher"] = matcher
        lst = cfg.setdefault("hooks", {}).setdefault(event, [])
        lst[:] = [e for e in lst if not any("autotracker" in h.get("command", "") for h in e.get("hooks", []))]   # drop pre-rename hooks
        if not any(hook in e.get("hooks", []) for e in lst):
            lst.append(entry)
    p.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    say(f"✓ installed hooks in {p}")
    return 0


def cmd_ui(a, tr):
    from . import server
    server.serve(tr.project, a.port, not a.no_browser, a.read_only)
    return 0


def cmd_mcp(a, tr):
    from . import mcp_server
    mcp_server.serve(tr.project, tr.vault if a.vault else None)
    return 0


def cmd_script(a, tr):
    import pkgutil
    say(pkgutil.get_data("footnote", "appscript.gs").decode("utf-8"))
    return 0


def ask(prompt, default=""):
    try:
        v = input(f"{prompt}{f' [{default}]' if default else ''} ").strip()
    except EOFError:
        v = ""
    return v or default


def cmd_setup(a, tr):
    interactive = sys.stdin.isatty()
    say("Welcome! Let's set up your tracker. It reads your project notes, watches your work,")
    say("and keeps a tracker up to date for you. You can change any answer later.\n")
    types = list(setup.TYPES)
    if interactive:
        say("Where would you like your tracker to live?")
        for i, t in enumerate(types, 1):
            say(f"  {i}. {setup.TYPES[t]}")
        pick = ask("Type a number (or several, like 1,2):", "1")
        chosen = [types[int(x) - 1] for x in pick.replace(" ", "").split(",")
                  if x.isdigit() and 0 < int(x) <= len(types)] or ["obsidian"]
    else:
        chosen = ["obsidian"]
    for t in chosen:
        opts = {}
        if interactive:
            for key, label, required in setup.FIELDS[t]:
                v = ask(f"{label}{' (required)' if required else ''}:")
                if v:
                    opts[key] = v
        try:
            setup.add_tracker(tr.project, t, **opts)
        except TrackerError as e:
            say(f"⚠ {e}")
            say(f"  (skipping {t}; you can retry with:  footnote add-tracker {t})")
    tool_names = connect_mod.TOOLS
    if interactive:
        say("\nWhich AI tool do you use? It will update the tracker for you while you work.")
        say("  " + ", ".join(tool_names) + "  (or press Enter to skip)")
        for tool in [x.strip() for x in ask("Tool(s):").split(",") if x.strip()]:
            try:
                wrote, notes = connect_mod.connect(tool, tr.project)
                for w in wrote:
                    say(f"✓ wrote {w}")
                for n in notes:
                    say("\n" + n)
            except ValueError as e:
                say(f"⚠ {e}")
    if interactive:
        what = ask("\nIn a few words, what are you building or running? (e.g. portfolio website, online store, bakery):")
        if what:
            tr.set_project(None, what, None)
    say("\nBuilding your tracker…")
    tr2 = Tracker(tr.project)
    _report(tr2.sync(), tr2)
    say("\nNext steps:")
    say("  • footnote ui                     open the tracker in your browser")
    say("  • footnote say \"finished the logo\"   update it in plain English")
    return 0


def cmd_project(a, tr):
    say(tr.set_project(" ".join(a.name) if a.name else None, a.kind, a.goal))
    return 0


def cmd_record(a, tr):
    tr.record(a.kind, " ".join(a.text), a.task, who="cli")
    say("Recorded.")
    return 0


def cmd_metric(a, tr):
    say("Recorded." if tr.metric(a.name, a.value, a.date, a.unit, "cli") else "Already recorded.")
    return 0


def cmd_metrics_import(a, tr):
    r = tr.import_metrics(a.file, a.mode)
    say(f"Imported as {r['mode']}: {r['added']} new figure(s), {r['skipped']} skipped (duplicates or unreadable rows).")
    say("See them in Tracker/Metrics.md and Tracker/Project Report.md")
    return 0


def cmd_report(a, tr):
    if a.email:
        to = tr.mail_report(a.audience if a.audience != "all" else "manager", a.attach or ())
        say(f"Sent to {', '.join(to)}.")
        return 0
    if a.html:
        say(f"Saved {tr.report_html(a.html, a.audience)}  (open it in a browser; print to PDF to share)")
        return 0
    say(tr.report(a.audience))
    return 0


def cmd_deck(a, tr):
    say(f"Saved {tr.deck(a.file, a.audience)}  (open it in PowerPoint, Keynote or Google Slides)")
    return 0


def cmd_portfolio(a, tr):
    from . import portfolio
    if a.action == "add":
        portfolio.add(a.path or tr.project)
        say("Added.")
    elif a.action == "remove":
        portfolio.remove(a.path or tr.project)
        say("Removed.")
    md, cards = portfolio.build()
    if a.html:
        from . import export
        Path(a.html).write_text(export.convert(md, "Portfolio"), encoding="utf-8")
        say(f"Saved {a.html}")
    elif a.action == "show":
        say(md)
    return 0


def cmd_catchup(a, tr):
    say(tr.catchup(a.since, a.peek))
    return 0


def cmd_team(a, tr):
    tr.sync()
    say((tr.vault / "Team.md").read_text(encoding="utf-8"))
    return 0


def cmd_whois(a, tr):
    say(tr.whois(" ".join(a.query)))
    return 0


def cmd_assign(a, tr):
    t, who = tr.assign(a.id, " ".join(a.person))
    say(f"{t} is now owned by {who}.")
    return 0


def cmd_add_repo(a, tr):
    setup.add_repo(tr.project, a.path)
    say(f"Added {a.path}. Its history will be included in the team view and report.")
    return 0


def cmd_add_source(a, tr):
    setup.add_source(tr.project, a.type, **dict(kv.split("=", 1) for kv in (a.opt or [])))
    r = Tracker(tr.project).sync()
    _report(r, tr)
    return 0


def cmd_metrics(a, tr):
    for e in tr.metrics_list(a.name, a.limit):
        say(f"{e['id']:<10} {e['date']}  {e['name']:<18} {e['value']:>12,.2f} {e.get('unit', ''):<4} {e.get('source', '')}")
    return 0


def cmd_metric_fix(a, tr):
    tr.metric_fix(a.id, a.value)
    say("Corrected.")
    return 0


def cmd_metric_delete(a, tr):
    tr.metric_delete(a.id)
    say("Removed.")
    return 0


def cmd_currency(a, tr):
    tr.set_currency(a.base, dict(kv.split("=", 1) for kv in (a.rate or [])))
    say(f"Base currency {a.base.upper()}" + (f" with rates {', '.join(a.rate)}" if a.rate else "") + ". Figures recalculated.")
    return 0


def cmd_archive(a, tr):
    tr.archive(a.id, " ".join(a.reason))
    say(f"{a.id.upper()} archived. Bring it back with: footnote unarchive {a.id.upper()}")
    return 0


def cmd_unarchive(a, tr):
    say(f"{tr.unarchive(a.id)} restored.")
    return 0


def cmd_rename(a, tr):
    say(f"{tr.rename(a.id, ' '.join(a.title))} renamed.")
    return 0


def cmd_unlock(a, tr):
    say(f"{tr.unlock(a.id)} unlocked: automation may update it again.")
    return 0


def cmd_history(a, tr):
    rows = tr.history()
    if not rows:
        say("No history yet.")
    for r in rows[:30]:
        say(f"{r['id']}  {r['ts'][:16]}  {r['tasks']:>3} tasks  before: {r['label']}")
    say("\nUndo the last change: footnote undo     Go back to a state: footnote undo --to <id>")
    return 0


def cmd_undo(a, tr):
    lines, locked = tr.undo(a.steps, a.to)
    if not lines:
        say("Nothing to undo.")
        return 0
    say("Undone:")
    for l in lines:
        say("  • " + l)
    if locked:
        say(f"\n{', '.join(sorted(locked))} are now locked so automation won't redo the change. "
            "Unlock with: footnote unlock T-001")
    return 0


def cmd_doctor(a, tr):
    from . import doctor
    say(doctor.render(doctor.run(tr, a.live)))
    return 0


def cmd_log(a, tr):
    from . import log
    for l in log.tail(tr.project, a.lines):
        say(l)
    return 0


def cmd_publish(a, tr):
    r = tr.sync(force_publish=True)
    say("Published the report, team view, figures, journal and architecture to: " +
        (", ".join(n for n, _ in r.mirrors) or "(no connected tracker supports pages)"))
    for w in r.warnings:
        say("⚠ " + w)
    return 0


def cmd_relay(a, tr):
    from . import relay
    relay.serve(a.port, a.host, a.push_key, a.pull_token, a.store)
    return 0


def cmd_add_relay(a, tr):
    setup.add_relay(tr.project, a.url, a.pull_token, a.pull_token_env)
    r = Tracker(tr.project).sync()
    say("Relay connected. Events posted to it (Zapier, Make, GitHub…) now reach this tracker." +
        (f"\n⚠ {r.warnings[0]}" if r.warnings else ""))
    return 0


def cmd_add_notify(a, tr):
    setup.add_notify(tr.project, a.slack, a.email_to, a.smtp_host, a.smtp_port, a.smtp_user, a.email_from, a.digest, not a.no_tls,
                     a.content, a.report_for, a.attach)
    say("Alerts are on: you'll hear once about blocked or stalled work, new risks, a failing build, waiting reviews and "
        "revenue drops. Existing items are noted silently so you aren't flooded.\nSend a test now with: footnote digest")
    return 0


def cmd_digest(a, tr):
    text, errs = tr.digest(a.dry_run)
    say(text)
    for e in errs:
        say("⚠ " + e)
    return 1 if errs and not a.dry_run else 0


def cmd_field_set(a, tr):
    say(f"{tr.set_field(a.id, a.field, ' '.join(a.value))} updated.")
    return 0


def cmd_due(a, tr):
    say(f"{tr.set_field(a.id, 'due', ' '.join(a.when))} updated.")
    return 0


def cmd_field(a, tr):
    if a.action == "add":
        if not a.name:
            raise TrackerError("Which field? e.g.  footnote field add budget --type number")
        sample = tr.add_field(a.name, a.type, a.formula)
        say(f"Field “{a.name}” added." + (f" Example value: {sample}" if sample is not None else ""))
    elif a.action == "remove":
        tr.remove_field(a.name)
        say("Field removed.")
    else:
        for f in tr.fields():
            say(f"{f['name']:<18} {f['type']:<7} {('= ' + f['formula']) if f['formula'] else ''}")
    return 0


def cmd_invoice(a, tr):
    if a.action == "add":
        if not (a.client and a.amount and a.due):
            raise TrackerError("e.g.  footnote invoice add --client Acme --amount 1200 --due \"in 30 days\"")
        say(f"Added {tr.add_invoice(a.client, a.amount, a.due, a.currency or '')}.")
    elif a.action == "paid":
        i = tr.invoice_paid(a.id, a.date)
        say(f"{i['id']} marked as paid. (Record the money itself via your bank import so it isn't counted twice.)")
    else:
        for i in tr.invoices():
            say(f"{i['id']}  {i['client']:<20} {i['amount']:>10,.2f} {i['currency']:<4} due {i['due']}  {i['status']}")
    return 0


def cmd_categorize(a, tr):
    tr.categorize(a.keyword, " ".join(a.category))
    say(f"Done: anything with “{a.keyword}” in its description is now “{' '.join(a.category)}” (past and future).")
    return 0


def cmd_add_llm(a, tr):
    setup.add_llm(tr.project, a.command, not a.no_summary, not a.no_fuzzy)
    say("AI help is on. It can: understand updates the simple matcher can't (other languages, loose wording), write the one-paragraph "
        "summary at the top of the report, and suggest calculated fields (footnote suggest-fields).\n"
        "It uses the command you set (default `claude -p`). What it sees: task titles/statuses and report numbers; never your files or secrets.\n"
        "Check it works: footnote doctor")
    return 0


def cmd_suggest_fields(a, tr):
    found = tr.suggest_fields(a.apply)
    if not found:
        say("No suggestions this time.")
    for f in found:
        say(f"• {f['name']} ({f['type']}) = {f['formula']}\n    {f['why']}")
    if found and not a.apply:
        say("\nAdd them all with: footnote suggest-fields --apply   (undo anytime with: footnote undo)")
    return 0


def cmd_default(a, tr):
    if not config.exists(tr.project):
        return cmd_setup(a, tr)
    s = tr.summary()
    say(f"{s['percent_done']}% done — {s['counts']['done']}/{s['total']} tasks "
        f"({s['counts']['active']} in progress, {s['counts']['blocked']} blocked)")
    say("Open the tracker:  footnote ui     |  See tasks:  footnote status     |  Help:  footnote --help")
    return 0


def build():
    ap = argparse.ArgumentParser(prog="footnote", description="A tracker that keeps itself up to date.")
    ap.add_argument("--project", default=".", help="project folder (default: here)")
    ap.add_argument("--vault", default=None, help="notes folder (default: ./Tracker)")
    sub = ap.add_subparsers(dest="cmd")

    def add(name, fn, help_, **kw):
        p = sub.add_parser(name, help=help_, **kw)
        p.set_defaults(fn=fn, quiet=False, agent=False)
        return p
    add("setup", cmd_setup, "guided first-time setup")
    p = add("sync", cmd_sync, "refresh the tracker from your docs, git and connected apps")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--agent", action="store_true", help="let Claude propose tasks on first run")
    add("status", cmd_status, "show all tasks")
    add("list", cmd_status, "show all tasks")
    p = add("say", cmd_say, "update in plain English: footnote say \"finished the logo\"")
    p.add_argument("text", nargs="+")
    p = add("add", cmd_add, "add a task")
    p.add_argument("title", nargs="+")
    p.add_argument("--epic", default="Inbox")
    p.add_argument("--parent")
    p.add_argument("--depends-on", action="append")
    p = add("set", cmd_set, "set a task's status: footnote set T-001 done")
    p.add_argument("id")
    p.add_argument("status", nargs="+")
    p = add("link", cmd_link, "relate tasks: footnote link T-003 depends_on T-001 [--remove]")
    p.add_argument("id"); p.add_argument("type"); p.add_argument("target")
    p.add_argument("--remove", action="store_true")
    p = add("add-tracker", cmd_add_tracker, "connect Notion / Google Sheets / Excel / database")
    p.add_argument("type", choices=sorted(set(setup.TYPES)))
    p.add_argument("--opt", action="append", metavar="KEY=VALUE")
    p = add("connect", cmd_connect, "set up an AI tool (claude, cursor, codex, gemini, copilot, windsurf, generic)")
    p.add_argument("tool", choices=connect_mod.TOOLS)
    p = add("project", cmd_project, "describe the project: footnote project --kind \"online store\" --goal \"sell mugs\"")
    p.add_argument("name", nargs="*"); p.add_argument("--kind", required=True); p.add_argument("--goal")
    p = add("record", cmd_record, "save a decision/risk/learning: footnote record decision \"Using Stripe Checkout\"")
    p.add_argument("kind", choices=["decision", "risk", "learning", "milestone", "note", "issue"])
    p.add_argument("text", nargs="+"); p.add_argument("--task")
    p = add("metric", cmd_metric, "record a number: footnote metric revenue 120.50")
    p.add_argument("name"); p.add_argument("value"); p.add_argument("--date"); p.add_argument("--unit", default="")
    p = add("metrics-import", cmd_metrics_import, "import sales / analytics / bank CSV exports")
    p.add_argument("file"); p.add_argument("--mode", default="auto", choices=["auto", "sales", "bank", "wide", "long"])
    p = add("metrics", cmd_metrics, "list recorded numbers with their IDs")
    p.add_argument("name", nargs="?"); p.add_argument("--limit", type=int, default=50)
    p = add("metric-fix", cmd_metric_fix, "correct a recorded number: footnote metric-fix 3fa9c2d1 150")
    p.add_argument("id"); p.add_argument("value")
    p = add("metric-delete", cmd_metric_delete, "remove a recorded number")
    p.add_argument("id")
    p = add("currency", cmd_currency, "set base currency and exchange rates: footnote currency USD --rate EUR=1.08")
    p.add_argument("base"); p.add_argument("--rate", action="append", metavar="CODE=RATE")
    p = add("archive", cmd_archive, "hide a task (nothing is lost): footnote archive T-004 no longer needed")
    p.add_argument("id"); p.add_argument("reason", nargs="*")
    p = add("unarchive", cmd_unarchive, "bring an archived task back")
    p.add_argument("id")
    p = add("rename", cmd_rename, "rename a task: footnote rename T-004 New title")
    p.add_argument("id"); p.add_argument("title", nargs="+")
    p = add("unlock", cmd_unlock, "let automation update a task again")
    p.add_argument("id")
    add("history", cmd_history, "list earlier states you can go back to")
    p = add("undo", cmd_undo, "undo the last change (yours or automatic)")
    p.add_argument("--steps", type=int, default=1); p.add_argument("--to", help="a state id from `footnote history`")
    p = add("doctor", cmd_doctor, "check that everything is working (add --live to test connections)")
    p.add_argument("--live", action="store_true", help="also test Notion / Sheets / Stripe connections (read-only)")
    p = add("log", cmd_log, "show recent activity and problems")
    p.add_argument("--lines", type=int, default=30)
    add("publish", cmd_publish, "update the report pages in Notion / Google Sheets now")
    p = add("relay", cmd_relay, "run the webhook relay on a server (so Zapier/Make can reach you)")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--host", default="127.0.0.1", help="use 0.0.0.0 only behind HTTPS (a reverse proxy or your host's TLS)")
    p.add_argument("--push-key"); p.add_argument("--pull-token"); p.add_argument("--store", help="file to keep the queue in")
    p = add("add-relay", cmd_add_relay, "pull events from a hosted relay")
    p.add_argument("url"); p.add_argument("--pull-token"); p.add_argument("--pull-token-env")
    p = add("add-notify", cmd_add_notify, "get alerts and a digest in Slack and/or email")
    p.add_argument("--slack", help="Slack incoming-webhook URL"); p.add_argument("--email-to", help="comma-separated addresses")
    p.add_argument("--smtp-host"); p.add_argument("--smtp-port", default=587); p.add_argument("--smtp-user"); p.add_argument("--email-from")
    p.add_argument("--digest", choices=["daily", "weekly", "monthly", "off"], help="how often to send it")
    p.add_argument("--content", choices=["catchup", "report"], help="a short catch-up (default) or the full project report")
    p.add_argument("--report-for", choices=["manager", "everyone", "developer", "all"], help="which version of the report")
    p.add_argument("--attach", nargs="+", choices=["deck", "html"], help="attach slides (.pptx) and/or an HTML copy")
    p.add_argument("--no-tls", action="store_true")
    p = add("digest", cmd_digest, "send the catch-up now (or --dry-run to just show it)")
    p.add_argument("--dry-run", action="store_true")
    p = add("due", cmd_due, "set a due date in plain words: footnote due T-004 next friday")
    p.add_argument("id"); p.add_argument("when", nargs="+")
    p = add("set-field", cmd_field_set, "set any field: footnote set-field T-004 priority high")
    p.add_argument("id"); p.add_argument("field"); p.add_argument("value", nargs="+")
    p = add("field", cmd_field, "add/remove/list custom fields, optionally calculated")
    p.add_argument("action", choices=["add", "remove", "list"]); p.add_argument("name", nargs="?")
    p.add_argument("--type", default="string"); p.add_argument("--formula", help='e.g. "days_since(created)" or \'"Late" if is_overdue else "OK"\'')
    p = add("portfolio", cmd_portfolio, "one view of several projects: footnote portfolio add ../shop ; footnote portfolio")
    p.add_argument("action", nargs="?", default="show", choices=["show", "add", "remove"]); p.add_argument("path", nargs="?")
    p.add_argument("--html")
    p = add("invoice", cmd_invoice, "track invoices: invoice add --client X --amount 1200 --due 'in 30 days' | invoice paid INV-001 | invoice list")
    p.add_argument("action", choices=["add", "paid", "list"]); p.add_argument("id", nargs="?")
    p.add_argument("--client"); p.add_argument("--amount"); p.add_argument("--due"); p.add_argument("--currency"); p.add_argument("--date")
    p = add("categorize", cmd_categorize, "teach a money category: footnote categorize aws Hosting")
    p.add_argument("keyword"); p.add_argument("category", nargs="+")
    p = add("add-llm", cmd_add_llm, "optional AI help (understands loose/multilingual updates, writes the summary paragraph)")
    p.add_argument("--command", help='the command to run, default: claude -p'); p.add_argument("--no-summary", action="store_true"); p.add_argument("--no-fuzzy", action="store_true")
    p = add("suggest-fields", cmd_suggest_fields, "ask the AI for useful calculated fields")
    p.add_argument("--apply", action="store_true")
    p = add("report", cmd_report, "the project report (for managers, everyone, or developers)")
    p.add_argument("--html", help="save as a single HTML file you can print to PDF or email")
    p.add_argument("--email", action="store_true", help="send it now to the email address from add-notify")
    p.add_argument("--attach", nargs="+", choices=["deck", "html"])
    p.add_argument("--for", dest="audience", default="all", choices=["all", "manager", "founder", "everyone", "developer"])
    p = add("deck", cmd_deck, "make a PowerPoint for a review or presentation: footnote deck review.pptx --for manager")
    p.add_argument("file"); p.add_argument("--for", dest="audience", default="all", choices=["all", "manager", "everyone", "developer"])
    p = add("catchup", cmd_catchup, "what changed since you last looked (or --since 3d)")
    p.add_argument("--since"); p.add_argument("--peek", action="store_true", help="don't mark as seen")
    add("team", cmd_team, "who is doing what")
    p = add("whois", cmd_whois, "who knows about a person/task/folder: footnote whois checkout/")
    p.add_argument("query", nargs="+")
    p = add("assign", cmd_assign, "set a task's owner: footnote assign T-004 alice")
    p.add_argument("id"); p.add_argument("person", nargs="+")
    p = add("add-repo", cmd_add_repo, "include another repository's history (multi-repo teams)")
    p.add_argument("path")
    p = add("add-source", cmd_add_source, "connect a read-only number source: stripe")
    p.add_argument("type", choices=["stripe", "shopify", "woocommerce", "github"]); p.add_argument("--opt", action="append", metavar="KEY=VALUE")
    add("install-hook", cmd_install_hook, "Claude Code: sync after every command")
    p = add("ui", cmd_ui, "open the tracker in your browser")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-browser", action="store_true")
    p.add_argument("--read-only", action="store_true", help="show the tracker without allowing any change (safe for screen sharing)")
    add("mcp", cmd_mcp, "run as an MCP server (used by AI tools)")
    add("show-script", cmd_script, "print the Google Sheets Apps Script")
    return ap


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):      # legacy Windows consoles choke on ✓ and curly quotes
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    a = build().parse_args(argv)
    try:
        tr = Tracker(a.project, a.vault)
        return (getattr(a, "fn", None) or cmd_default)(a, tr)
    except TrackerError as e:
        print(f"⚠ {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
