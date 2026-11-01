"""The one public API. The CLI, web UI, MCP server, webhook and inbox file all call this."""
import json
import re
from pathlib import Path
import datetime as dt
import subprocess  # nosec B404
import time
from .security import LIMITS, UNTRUSTED, clean_text
from . import deck as deck_mod, export, llm, dates, finance, formulas, github, notify, relay as relay_mod, log, history, lock, engine, nl, relations, config, insights, journal, metrics, profiles, report as report_mod, team, architecture, signals
from .store import parse_ts, Store, LABELS, norm_status, parse_frontmatter, now, iso

INBOX = "inbox.jsonl"


class TrackerError(Exception):
    """Message is written for humans; shown as-is."""


def _cap(value, what, key):
    v = clean_text(value)
    if len(v) > LIMITS[key]:
        raise TrackerError(f"{what} is too long (the limit is {LIMITS[key]} characters).")
    return v


class Tracker:
    def __init__(self, project=".", vault=None):
        self.project = Path(project).resolve()
        config.migrate_legacy(self.project)
        self._cfg0 = config.load(self.project)
        self.vault = Path(vault).resolve() if vault else self.project / self._cfg0["vault"]
        self.lock_timeout = 60.0

    @property
    def cfg(self):
        """Always fresh: a long-running process (the MCP server) must notice settings changed meanwhile."""
        return config.load(self.project)

    @cfg.setter
    def cfg(self, value):
        pass

    def _lock(self):
        """Hold this for any read-modify-write. Re-entrant, works across processes."""
        import contextlib

        @contextlib.contextmanager
        def guard():
            try:
                with lock.locked(config.lock_path(self.project), self.lock_timeout):
                    yield
            except lock.Busy:
                raise TrackerError("Another update is in progress (maybe your AI tool or another window). "
                                   "Try again in a moment.") from None
        return guard()

    # ---- reads
    def _store(self):
        s = Store(self.vault)
        s.ensure()
        return s

    def tasks(self, include_archived=False):
        if not (self.vault / "_schema.json").exists():
            self.sync()
        s = self._store()
        t = {k: v for k, v in s.load_tasks().items() if include_archived or not v[0].get("archived")}
        waits = relations.waiting_on(t)
        kids = relations.children(t)
        out = []
        for tid, (fm, _) in sorted(t.items()):
            d = {k: v for k, v in fm.items() if k not in ("key", "unlinked")}
            d["status_label"] = LABELS[fm["status"]]
            d["waiting_on"] = waits.get(tid, [])
            d["children"] = kids.get(tid, [])
            out.append(d)
        return out

    def summary(self):
        ts = self.tasks()
        c = {s: sum(1 for t in ts if t["status"] == s) for s in LABELS}
        pct = round(100 * c["done"] / len(ts)) if ts else 0
        return {"total": len(ts), "counts": c, "percent_done": pct,
                "mirrors": [{"name": m.get("name") or m["type"], "type": m["type"]}
                            for m in self.cfg.get("mirrors", [])]}

    # ---- sync
    def sync(self, use_agent=None, force_publish=False):
        with self._lock():
            self._snap("automatic sync")
            self._ingest_inbox()
            r = engine.sync_report(self.project, self.vault, use_agent, self.cfg, force_publish)
            for w in r.warnings:
                log.write(self.project, "warn", w)
            if r.changed:
                log.write(self.project, "info", f"sync: {r.changed} change(s)")
            try:
                notify.run(self, r)
            except Exception as e:                       # alerts must never break the tracker
                log.write(self.project, "warn", f"alerts: {e}")
            return r

    # ---- writes (every write ends with a sync so mirrors/dashboard stay current)
    def _snap(self, label):
        history.snapshot(self.project, self.vault, label)

    def _mutate(self, fn, label="change"):
        with self._lock():
            if not (self.vault / "_schema.json").exists():
                engine.sync_report(self.project, self.vault, None, self.cfg)
            self._snap(label)
            s = self._store()
            tasks = s.load_tasks()
            result = fn(s, tasks)
            for fm, body in tasks.values():
                s.write_task(fm, body)
            s.flush_log()
            return result

    def _need(self, tasks, tid):
        tid = (tid or "").upper()
        if tid not in tasks:
            raise TrackerError(f"There is no task {tid or '(none given)'}. Ask for the task list to see valid IDs.")
        return tid

    def _note(self, tasks, tid, note, who):
        if note:
            fm, body = tasks[tid]
            tasks[tid] = (fm, body.rstrip("\n") + f"\n- {now().strftime('%Y-%m-%d %H:%M')} ({who}) {note}\n")

    def set_status(self, tid, status, note="", who="you", sync=True):
        st = norm_status(status)
        if not st:
            raise TrackerError(f"“{status}” isn't a status. Use: Not started, In progress, Blocked or Done.")

        def go(s, tasks):
            t = self._need(tasks, tid)
            engine.set_status(tasks[t][0], st, f"set by {who}", s)
            self._note(tasks, t, note, who)
            return t
        t = self._mutate(go, f"set {tid} to {st}")
        if sync:
            self.sync()
        return t

    def add_task(self, title, epic="Inbox", parent=None, depends_on=(), status="todo", who="you", sync=True):
        title = _cap(title, "The title", "title").strip()
        epic = _cap(epic, "The area name", "name")
        if not title:
            raise TrackerError("A task needs a title.")
        self._fresh()

        def go(s, tasks):
            tid = engine.new_task(s, tasks, title, epic or "Inbox", f"added by {who}")
            fm = tasks[tid][0]
            if parent:
                relations.add(fm, "parent", self._need(tasks, parent), s, "given at creation")
            for d in depends_on or ():
                relations.add(fm, "depends_on", self._need(tasks, d), s, "given at creation")
            if norm_status(status) not in (None, "todo"):
                engine.set_status(fm, norm_status(status), f"created by {who}", s)
            return tid
        tid = self._mutate(go, f"add task: {title[:40]}")
        if sync:
            self.sync()
        return tid

    # ---- fields and calculations
    PROTECTED = {"id": "can't change", "key": "can't change", "created": "is set automatically", "source": "is set automatically",
                 "status": "use `footnote set T-001 done`", "locked": "use `footnote unlock T-001`",
                 "relations": "use `footnote link`", "unlinked": "use `footnote link`", "archived": "use `footnote archive`",
                 "cycle_days": "is calculated", "started": "is set automatically", "done": "is set automatically"}

    def set_field(self, tid, field, value, who="you"):
        value = _cap(value, "That value", "value")
        field = re.sub(r"[^a-z0-9_]+", "_", (field or "").strip().lower()).strip("_")

        def go(s, tasks):
            t = self._need(tasks, tid)
            schema = s.schema()
            if field in self.PROTECTED:
                raise TrackerError(f"“{field}” {self.PROTECTED[field]}.")
            if field in (schema.get("formulas") or {}):
                raise TrackerError(f"“{field}” is a calculated field. Change its formula with: footnote field add {field} --formula \"…\"")
            if field not in schema["fields"]:
                raise TrackerError(f"There is no field “{field}”. Add one with: footnote field add {field}   "
                                   f"(existing: {', '.join(k for k in schema['fields'] if k not in self.PROTECTED)})")
            typ = schema["fields"][field]
            text = str(value).strip()
            if field == "priority":
                from .scan import PRI
                if text.lower() not in PRI and text != "":
                    raise TrackerError("Priority can be: urgent, high, medium, low.")
                val = PRI.get(text.lower(), "")
            elif field == "estimate":
                val = dates.parse_estimate(text) if text else None
                if text and val is None:
                    raise TrackerError("Estimate looks like 3d, 2w, 4h or just a number of days.")
            elif typ == "date":
                val = dates.parse(text) if text else ""
                if text and not val:
                    raise TrackerError("I couldn't read that date. Try: tomorrow, next friday, in 3 days, dec 12, 2026-12-01.")
            elif typ == "number":
                try:
                    val = float(text.replace(",", "")) if text else None
                    val = int(val) if val is not None and val == int(val) else val
                except ValueError:
                    raise TrackerError(f"“{field}” is a number field; “{text}” isn't a number.")
            elif typ == "bool":
                val = text.lower() in ("yes", "true", "1", "y", "x")
            elif typ == "list":
                val = [x.strip() for x in text.split(",") if x.strip()]
            else:
                val = text
            tasks[t][0][field] = val
            s.log(f"{t} {field} → {val!r} (set by {who})")
            return t
        t = self._mutate(go, f"set {field} on {tid}")
        self.sync()
        return t

    def add_field(self, name, ftype="string", formula=None):
        name = re.sub(r"[^a-z0-9_]+", "_", (name or "").strip().lower()).strip("_")
        if not re.fullmatch(r"[a-z][a-z0-9_]*", name or ""):
            raise TrackerError("A field name uses letters, numbers and underscores, e.g. budget or days_open.")
        if name in self.PROTECTED or name in ("title", "epic", "owner", "priority", "due", "estimate"):
            raise TrackerError(f"“{name}” already exists as a built-in field.")
        if ftype not in ("string", "number", "date", "bool", "list"):
            raise TrackerError("Field type can be: string, number, date, bool, list.")
        sample = None
        with self._lock():
            s = self._store()
            if (self.vault / "_schema.json").exists() is False:
                engine.sync_report(self.project, self.vault, None, self.cfg)
            self._snap(f"add field {name}")
            schema = s.schema()
            if formula:
                try:
                    formulas.check(formula)
                except formulas.FormulaError as e:
                    raise TrackerError(str(e)) from e
                live = [(fm, b) for fm, b in s.load_tasks().values() if not fm.get("archived")]
                if live:
                    try:
                        sample = formulas.evaluate(formula, {**formulas.task_env(live[0][0]),
                                                             **{k: schema_val for k, schema_val in
                                                                {n: "" for n in (schema.get("formulas") or {})}.items()}})
                    except formulas.FormulaError as e:
                        if "unknown field" in str(e):
                            raise TrackerError(f"{e}. Fields you can use: {', '.join(sorted(live[0][0]))}") from e
                        sample = f"(example task: {e})"
                schema.setdefault("formulas", {})[name] = {"formula": formula}
                ftype = ftype if ftype != "string" or not isinstance(sample, (int, float)) else "number"
            schema["fields"][name] = ftype
            s.save_schema(schema)
            s.log(f"schema: new {'calculated ' if formula else ''}field `{name}` ({ftype})" + (f" = {formula}" if formula else ""))
            s.flush_log()
        self.sync()
        return sample

    def remove_field(self, name):
        name = (name or "").strip().lower()
        with self._lock():
            s = self._store()
            schema = s.schema()
            if name not in schema["fields"] or name in self.PROTECTED or name in ("title", "epic", "owner", "priority", "due", "estimate"):
                raise TrackerError(f"“{name}” isn't a custom field you can remove.")
            self._snap(f"remove field {name}")
            schema["fields"].pop(name)
            (schema.get("formulas") or {}).pop(name, None)
            s.save_schema(schema)
            for fm, body in s.load_tasks().values():
                if name in fm:
                    fm.pop(name)
                    s.write_task(fm, body)
            s.log(f"schema: removed field `{name}`")
            s.flush_log()
        self.sync()

    def fields(self):
        sc = self._store().schema()
        return [{"name": k, "type": v, "formula": (sc.get("formulas") or {}).get(k, {}).get("formula", "")}
                for k, v in sc["fields"].items() if k not in self.PROTECTED and k not in ("key", "unlinked")]

    def archive(self, tid, reason=""):
        """Hide a task everywhere without losing its history. The docs scan will not bring it back."""
        reason = _cap(reason, "The reason", "note")
        def go(s, tasks):
            t = self._need(tasks, tid)
            fm = tasks[t][0]
            fm["archived"] = True
            s.set_ignored(s.ignored() | {fm["key"]})
            self._note(tasks, t, f"archived{': ' + reason if reason else ''}", "you")
            s.log(f"{t} **{fm['title']}** archived" + (f" ({reason})" if reason else ""))
            return t
        t = self._mutate(go, f"archive {tid}")
        self.sync()
        return t

    def unarchive(self, tid):
        def go(s, tasks):
            t = self._need(tasks, tid)
            fm = tasks[t][0]
            fm["archived"] = False
            s.set_ignored(s.ignored() - {fm["key"]})
            s.log(f"{t} **{fm['title']}** restored from archive")
            return t
        t = self._mutate(go, f"unarchive {tid}")
        self.sync()
        return t

    def rename(self, tid, title):
        title = _cap(title, "The title", "title").strip()
        if not title:
            raise TrackerError("Give the new title.")

        def go(s, tasks):
            t = self._need(tasks, tid)
            s.log(f"{t} renamed: “{tasks[t][0]['title']}” → “{title}”")
            tasks[t][0]["title"] = title
            return t
        t = self._mutate(go, f"rename {tid}")
        self.sync()
        return t

    def unlock(self, tid):
        def go(s, tasks):
            t = self._need(tasks, tid)
            tasks[t][0]["locked"] = False
            s.log(f"{t} unlocked: automation may update it again")
            return t
        t = self._mutate(go, f"unlock {tid}")
        self.sync()
        return t

    # ---- undo
    def history(self):
        return history.listing(self.project)

    def undo(self, steps=1, to=None):
        """Step back (and make it stick). -> (lines describing what changed, locked task ids)."""
        with self._lock():
            sid, lines, locked = history.restore(self.project, self.vault, to, steps)
            if sid:
                s = self._store()
                s.log(f"UNDO: restored an earlier state ({len(lines)} difference(s))" + (
                    f"; locked {', '.join(sorted(locked))} so automation does not redo them" if locked else ""))
                s.flush_log()
        if sid:
            self.sync()
        return lines, locked

    def link(self, tid, rtype, target, remove=False):
        rtype = re.sub(r"[ -]+", "_", rtype.strip().lower())
        if not relations.REL.match(f"{rtype}:T-001"):
            raise TrackerError("Relationship names use letters only, e.g. depends_on, parent, related, caused_by.")

        def go(s, tasks):
            a, b = self._need(tasks, tid), self._need(tasks, target)
            fm = tasks[a][0]
            rel = f"{rtype}:{b}"
            if remove:
                fm["relations"] = [r for r in fm["relations"] if r != rel]
                if rel not in fm["unlinked"]:
                    fm["unlinked"].append(rel)
                s.log(f"{a} -relation `{rel}` (manual)")
            else:
                fm["unlinked"] = [r for r in fm["unlinked"] if r != rel]
                relations.add(fm, rtype, b, s, "manual")
        self._mutate(go, f"link {tid} {rtype} {target}")
        self.sync()

    def say(self, text, who="you", sync=True, create_missing=False):
        """Plain English in, plain English out. Never guesses when unsure."""
        text = _cap(text, "That message", "say")
        results = []
        if create_missing or nl.ADD.search(text or ""):
            self._fresh()

        def go(s, tasks):
            live = {k: v for k, v in tasks.items() if not v[0].get("archived")}
            for a in nl.parse(text, live, create_missing):
                if a["op"] == "unclear":
                    results.append({"ok": False, "message": a["message"], "clause": a.get("clause")})
                elif a["op"] == "field":
                    fm = tasks[a["id"]][0] if a["id"] in tasks else None
                    if fm is None:
                        results.append({"ok": False, "message": f"There is no task {a['id']}."})
                        continue
                    fm[a["field"]] = a["value"]
                    s.log(f"{a['id']} {a['field']} → {a['value']} ({who} said: “{a['clause']}”)")
                    results.append({"ok": True, "id": a["id"], "message": f"{a['id']} “{fm['title']}” is now due {a['value']}."})
                elif a["op"] == "add_status":
                    tid = engine.new_task(s, tasks, a["title"], "Inbox", f"added by {who}")
                    engine.set_status(tasks[tid][0], a["status"], f"{who} said: “{a['clause']}”", s)
                    results.append({"ok": True, "id": tid, "message":
                                    f"Added {tid} “{a['title']}” and marked it {LABELS[a['status']]}."})
                elif a["op"] == "add":
                    tid = engine.new_task(s, tasks, a["title"], "Inbox", f"added by {who}")
                    results.append({"ok": True, "id": tid, "message": f"Added {tid}: {a['title']}"})
                else:
                    fm = tasks[a["id"]][0] if a["id"] in tasks else None
                    if fm is None:
                        results.append({"ok": False, "message": f"There is no task {a['id']}."})
                        continue
                    old = fm["status"]
                    changed = engine.set_status(fm, a["status"], f"{who} said: “{a['clause']}”", s)
                    self._note(tasks, a["id"], a["clause"], who)
                    results.append({"ok": True, "id": a["id"], "message":
                                    f"{a['id']} “{fm['title']}”: {LABELS[old]} → {LABELS[a['status']]}"
                                    if changed else f"{a['id']} “{fm['title']}” is already {LABELS[old]}."})
        self._mutate(go, "update: " + (text or "")[:50])
        if llm.enabled(self.cfg, "fuzzy") and any(not r["ok"] and r.get("clause") for r in results):
            results = self._ai_second_look(results, who)
        if sync:
            self.sync()
        return results

    def _ai_second_look(self, results, who):
        """Optional: let the AI try the updates the keyword matcher could not place. It can only pick existing tasks."""
        out = []
        for r in results:
            if r["ok"] or not r.get("clause"):
                out.append(r)
                continue
            holder = {}

            def go(s, tasks, clause=r["clause"]):
                hit = llm.resolve_update(self.cfg, self.project, clause, tasks)
                if hit:
                    fm = tasks[hit["id"]][0]
                    old = fm["status"]
                    engine.set_status(fm, hit["status"], f"{who} said (understood by AI): “{clause}”", s)
                    self._note(tasks, hit["id"], clause, who)
                    holder["r"] = {"ok": True, "id": hit["id"], "message":
                                   f"{hit['id']} “{fm['title']}”: {LABELS[old]} → {LABELS[hit['status']]} (matched by AI — say the ID if wrong, or `footnote undo`)"}
            self._mutate(go, "AI-matched update")
            out.append(holder.get("r") or r)
        self.sync()
        return out

    def suggest_fields(self, apply=False):
        s = self._store()
        live = [fm for fm, _ in s.load_tasks().values() if not fm.get("archived")]
        if not llm.enabled(self.cfg):
            raise TrackerError("AI help isn't switched on. Enable it with: footnote add-llm")
        found = llm.suggest_fields(self.cfg, self.project, self.project_info()["kind"], s.schema(), live)
        if apply:
            for f in found:
                self.add_field(f["name"], f["type"], f["formula"])
        return found

    def _fresh(self):
        """Teammates share one tracker (Notion/Sheets): look before creating so IDs never collide."""
        if self.cfg.get("mirrors"):
            self.sync()

    # ---- project memory: definition, journal, numbers
    def project_info(self):
        return insights.project_info(self.vault, self.project, architecture.load(self.vault))

    def set_project(self, name=None, kind=None, goal=None):
        with self._lock():
            self._store()
            insights.save_project(self.vault, name, kind, goal)
        info = self.project_info()
        self.sync()
        return f"Saved: {info['name']} ({info['kind']}). " + profiles.template_text(info["kind"])

    def record(self, kind, text, task=None, who="agent", sync=True):
        text = _cap(text, "That note", "text")
        with self._lock():
            self._store()
            self._snap("record " + kind)
            e = journal.add(self.vault, kind, text, task and task.upper(), who)
        if sync:
            self.sync()
        return e["id"] if e else None

    def metric(self, name, value, date=None, unit="", who="you"):
        name = _cap(name, "The metric name", "name")
        with self._lock():
            self._store()
            self._snap("record number")
            try:
                added = metrics.add(self.vault, name, value, date, unit, who)
            except ValueError as e:
                raise TrackerError(f"That doesn't look like a number: {value!r}") from e
        self.sync()
        return added

    def import_metrics(self, path, mode="auto"):
        self._store()
        p = Path(path).expanduser()
        if not p.exists():
            raise TrackerError(f"I can't find the file {path}")
        with self._lock():
            self._snap("import numbers")
            try:
                res = metrics.import_csv(self.vault, p, mode, default_unit=metrics.settings(self.cfg)[0])
            except ValueError as e:
                raise TrackerError(str(e)) from e
        self.sync()
        return res

    def categorize(self, keyword, category):
        with self._lock():
            cfg = config.load(self.project)
            cfg.setdefault("finance", {}).setdefault("rules", {})[keyword.strip().lower()] = category.strip()
            config.save(self.project, cfg)
            self.cfg = cfg
        self.sync()

    def add_invoice(self, client, amount, due, currency="", note=""):
        client, note = _cap(client, "The client name", "client"), _cap(note, "The note", "note")
        when = dates.parse(due)
        if not when:
            raise TrackerError("I couldn't read the due date. Try: 2026-12-01, in 30 days, end of month.")
        with self._lock():
            self._store()
            self._snap("add invoice")
            try:
                iid = finance.add_invoice(self.vault, client, amount, when, currency or metrics.settings(self.cfg)[0], note)
            except ValueError as e:
                raise TrackerError(f"That doesn't look like an amount: {amount!r}") from e
        self.sync()
        return iid

    def invoice_paid(self, iid, date=None):
        with self._lock():
            self._snap("invoice paid")
            try:
                inv = finance.mark_paid(self.vault, iid, date)
            except ValueError as e:
                raise TrackerError(str(e)) from e
        self.sync()
        return inv

    def invoices(self):
        return finance.invoices(self.vault)

    def metrics_list(self, name=None, limit=50):
        es = metrics.read(self.vault)
        if name:
            es = [e for e in es if e["name"] == metrics.norm_name(name)]
        return es[-limit:]

    def metric_delete(self, mid):
        with self._lock():
            try:
                metrics.delete(self.vault, mid)
            except ValueError as e:
                raise TrackerError(str(e)) from e
        self.sync()

    def metric_fix(self, mid, value):
        with self._lock():
            try:
                new = metrics.fix(self.vault, mid, value)
            except ValueError as e:
                raise TrackerError(str(e)) from e
        self.sync()
        return new

    def set_currency(self, base, rates=None):
        with self._lock():
            cfg = config.load(self.project)
            cfg["currency"] = {"base": base.upper(), "rates": {k.upper(): float(v) for k, v in (rates or {}).items()}}
            config.save(self.project, cfg)
            self.cfg = cfg
        self.sync()

    # ---- team
    def _history(self):
        return signals.git_history(self.project, self.cfg.get("repos", []))

    def _analysis(self, days=7):
        tasks = self._store().load_tasks()
        return team.analyze(self._history(), tasks, self.cfg, window_days=days), tasks

    def assign(self, tid, person):
        analysis, _ = self._analysis()
        hits = team.match_person(analysis, person)
        name = hits[0]["name"] if len(hits) == 1 else person.strip()

        def go(s, tasks):
            t = self._need(tasks, tid)
            tasks[t][0]["owner"] = name
            s.log(f"{t} owner → {name} (assigned)")
            return t
        t = self._mutate(go, f"assign {tid} to {name}")
        self.sync()
        return t, name

    def whois(self, query):
        analysis, tasks = self._analysis()
        return team.whois(analysis, tasks, query)

    def _git_email(self):
        try:
            return subprocess.run(["git", "-C", str(self.project), "config", "user.email"], capture_output=True,  # nosec B603 B607
                                  text=True, timeout=5, encoding="utf-8", errors="replace").stdout.strip().lower() or "unknown"
        except Exception:
            return "unknown"

    @staticmethod
    def parse_since(s, now):
        s = (s or "").strip().lower()
        m = re.fullmatch(r"(\d+)\s*(h|d|w|m)", s)
        if m:
            n, u = int(m.group(1)), m.group(2)
            return now - dt.timedelta(hours=n) if u == "h" else now - dt.timedelta(days=n * {"d": 1, "w": 7, "m": 30}[u])
        if s in ("yesterday",):
            return now - dt.timedelta(days=1)
        if s in ("today",):
            return now.replace(hour=0, minute=0, second=0, microsecond=0)
        if s in ("last week", "week"):
            return now - dt.timedelta(days=7)
        try:
            d = parse_ts(s)
            return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)
        except ValueError:
            raise TrackerError("I didn't understand that time. Try: 3d, 2w, yesterday, or a date like 2026-10-28.")

    def catchup(self, since=None, peek=False):
        """What changed since you last looked (remembered per person), or since a given time."""
        now = dt.datetime.now(dt.timezone.utc)
        seen_p = config.dir_for(self.project) / "last_seen.json"
        try:
            seen = json.loads(seen_p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            seen = {}
        me = self._git_email()
        if since:
            cut = self.parse_since(since, now)
        elif me in seen:
            cut = parse_ts(seen[me])
        else:
            cut = now - dt.timedelta(days=7)
        days = max(1, (now - cut).days + (1 if (now - cut).seconds else 0))
        analysis, tasks = self._analysis(days)
        text = team.catchup(analysis, tasks, journal.read(self.vault), cut, now)
        if not peek:
            seen[me] = iso(now)
            seen_p.parent.mkdir(exist_ok=True)
            seen_p.write_text(json.dumps(seen), encoding="utf-8")
        return text

    def deck_bytes(self, audience="all"):
        md = self.report(audience)
        tasks = {k: v for k, v in self._store().load_tasks().items() if not v[0].get("archived")}
        mets = metrics.summarize(metrics.read(self.vault), None, *metrics.settings(self.cfg))
        return deck_mod.build(self.project_info(), tasks, mets, md, audience)

    def deck(self, path, audience="all"):
        p = Path(path).expanduser()
        if p.suffix.lower() != ".pptx":
            p = p.with_suffix(".pptx")
        p.write_bytes(self.deck_bytes(audience))
        return str(p)

    def digest_payload(self, since, n=None):
        """What a scheduled email contains: a short catch-up, or the full report (optionally with slides / HTML attached)."""
        n = n if n is not None else (self.cfg.get("notify") or {})
        name = self.project_info()["name"]
        if n.get("content", "catchup") == "report":
            aud = n.get("report_for", "manager")
            md = self.report(aud)
            files = []
            if "deck" in (n.get("attach") or []):
                files.append((f"{re.sub(r'[^A-Za-z0-9._-]+', '_', name)}-review.pptx",
                              "application/vnd.openxmlformats-officedocument.presentationml.presentation", self.deck_bytes(aud)))
            if "html" in (n.get("attach") or []):
                files.append((f"{re.sub(r'[^A-Za-z0-9._-]+', '_', name)}-report.html", "text/html", export.convert(md, f"{name} report").encode("utf-8")))
            return f"{name}: project report", md, export.convert(md, f"{name} report"), files
        return f"{name}: catch-up", notify.digest_text(self, since), None, []

    def mail_report(self, audience="manager", attach=()):
        """Send the report by email right now (to the address(es) set with add-notify)."""
        n = self.cfg.get("notify") or {}
        if not (n.get("email") or {}).get("to"):
            raise TrackerError("No email address is set up. Add one with: footnote add-notify --email-to you@example.com --smtp-host smtp.gmail.com")
        n = {**n, "slack_webhook": None, "content": "report", "report_for": audience, "attach": list(attach)}
        subject, body, html, files = self.digest_payload(None, n)
        errs = notify.send(n, subject, body, html, files)
        if errs:
            raise TrackerError("; ".join(errs))
        return n["email"]["to"]

    def report_html(self, path, audience="all"):
        from . import export
        md = self.report(audience)
        info = self.project_info()
        Path(path).expanduser().write_text(export.convert(md, f"{info['name']} — project report"), encoding="utf-8")
        return str(Path(path).expanduser())

    def digest(self, dry_run=False):
        """Send (or preview) the catch-up now. -> (text, errors)"""
        n = self.cfg.get("notify") or {}
        st = notify._load(self.project) or {}
        since = st.get("digest") or iso(dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=7))
        text = notify.digest_text(self, since)
        if dry_run or not n:
            return text, [] if n else ["Alerts/digests aren't set up yet: footnote add-notify --slack <webhook URL>"]
        errs = notify.send(n, f"{self.project_info()['name']}: catch-up", text)
        if not errs:
            st = st or {"alerts": {}}
            st["digest"] = iso(dt.datetime.now(dt.timezone.utc))
            from .store import atomic_write
            atomic_write(notify._state_path(self.project), json.dumps(st))
        return text, errs

    def report(self, audience="all"):
        if not (self.vault / "_schema.json").exists():
            self.sync()
        tasks = self._store().load_tasks()
        hist = self._history()
        analysis = team.analyze(hist, tasks, self.cfg, github=github.load(self.vault))
        arch = architecture.load(self.vault) or architecture.scan(self.project, self.vault)
        return report_mod.build(insights.project_info(self.vault, self.project, arch), tasks, self._store().schema(), arch,
                                journal.read(self.vault), metrics.summarize(metrics.read(self.vault), None, *metrics.settings(self.cfg)), analysis, hist, audience,
                                github.load(self.vault), insights.snapshot_prior(self.vault))

    # ---- inbox: any tool can append a JSON line to .footnote/inbox.jsonl
    def _ingest_relay(self):
        item = self.cfg.get("relay")
        if not item:
            return 0
        stamp = config.dir_for(self.project) / "relay_last"
        try:
            if time.time() - float(stamp.read_text(encoding="utf-8")) < 15:      # hooks fire often; don't hammer the relay
                return 0
        except (OSError, ValueError):
            pass
        try:
            events = relay_mod.fetch(item)
        except Exception as e:
            log.write(self.project, "warn", f"relay: {e}")
            return 0
        stamp.parent.mkdir(exist_ok=True)
        stamp.write_text(str(time.time()), encoding="utf-8")
        done = []
        for e in events:
            try:
                self.handle_event({**e["payload"], "source": e["payload"].get("source", "webhook")}, sync=False)
            except Exception as ex:                    # a bad event must never block the queue
                log.write(self.project, "warn", f"relay event {e.get('id')} ignored: {ex}")
            done.append(e["id"])
        try:
            relay_mod.ack(item, done)
        except Exception as e:
            log.write(self.project, "warn", f"relay ack failed (events may repeat once): {e}")
        return len(done)

    def _ingest_inbox(self):
        self._ingest_relay()
        p = config.dir_for(self.project) / INBOX
        if not p.exists() or not p.read_text(encoding="utf-8").strip():
            return 0
        p.parent.mkdir(exist_ok=True)
        lines = p.read_text(encoding="utf-8").splitlines()
        p.write_text("", encoding="utf-8")
        n = 0
        for line in lines:
            try:
                ev = json.loads(line)
                self.handle_event(ev, sync=False)
                n += 1
            except (ValueError, TrackerError):
                pass
        with open(p.parent / "inbox.done.jsonl", "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        return n

    def handle_event(self, ev, sync=True):
        """Generic event: {"text": ...} | {"id":..,"status":..,"note":..} | {"add": "title"}."""
        who = ev.get("source", "agent")
        if ev.get("text"):
            return self.say(ev["text"], who, sync=sync, create_missing=who != "you")
        if ev.get("add"):
            return {"id": self.add_task(ev["add"], ev.get("epic", "Inbox"), ev.get("parent"),
                                        ev.get("depends_on", ()), who=who, sync=sync)}
        if ev.get("id") and ev.get("status"):
            return {"id": self.set_status(ev["id"], ev["status"], ev.get("note", ""), who, sync=sync)}
        raise TrackerError("Event needs one of: text | add | id+status")
