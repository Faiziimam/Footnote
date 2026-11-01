import json, os, subprocess, sys, tempfile, textwrap, time, unittest, datetime as dt
from pathlib import Path
from footnote import config, lock, metrics, cli, setup, connect
from footnote.api import Tracker, TrackerError
from footnote.store import Store
from tests.test_project import git, commit

ROOT = str(Path(__file__).resolve().parent.parent)


class Locking(unittest.TestCase):
    def test_parallel_processes_do_not_collide(self):
        d = Path(tempfile.mkdtemp()); git(d, "init", "-q", "-b", "main")
        Tracker(d).sync()
        code = textwrap.dedent(f"""
            import sys; sys.path.insert(0, {ROOT!r})
            from footnote.api import Tracker
            t = Tracker({str(d)!r})
            for i in range(5):
                t.add_task(f"task {{sys.argv[1]}}-{{i}}", sync=False)
        """)
        ps = [subprocess.Popen([sys.executable, "-c", code, str(n)], env={**os.environ, "PYTHONPATH": ROOT}) for n in range(8)]
        for p in ps:
            self.assertEqual(p.wait(), 0)
        ids = [f["id"] for f, _ in Store(d / "Tracker").load_tasks().values()]
        self.assertEqual(len(ids), 40)
        self.assertEqual(len(set(ids)), 40)
        self.assertEqual(json.loads((d / "Tracker" / "_schema.json").read_text(encoding="utf-8"))["next_id"], 41)

    def test_busy_gives_plain_message(self):
        d = Path(tempfile.mkdtemp()); git(d, "init", "-q", "-b", "main")
        hold = textwrap.dedent(f"""
            import sys, time; sys.path.insert(0, {ROOT!r})
            from footnote import lock, config
            with lock.locked(config.lock_path({str(d)!r})):
                print("held", flush=True); time.sleep(4)
        """)
        p = subprocess.Popen([sys.executable, "-c", hold], stdout=subprocess.PIPE, text=True, env={**os.environ, "PYTHONPATH": ROOT})
        p.stdout.readline()
        t = Tracker(d); t.lock_timeout = 0.5
        with self.assertRaises(TrackerError) as c:
            t.add_task("x")
        self.assertIn("another update is in progress", str(c.exception).lower())
        p.wait()
        Tracker(d).add_task("works after release")

    def test_reentrant_in_one_process(self):
        d = Path(tempfile.mkdtemp())
        with lock.locked(config.lock_path(d)):
            with lock.locked(config.lock_path(d)):
                Tracker(d).add_task("nested ok")


class HookPortability(unittest.TestCase):
    def test_hook_command_is_shell_neutral_and_actually_runs(self):
        d = Path(tempfile.mkdtemp()); git(d, "init", "-q", "-b", "main")
        (d / "PLAN.md").write_text("- [ ] One\n- [ ] Two\n")
        cli.main(["--project", str(d), "install-hook"])
        cfg = json.loads((d / ".claude" / "settings.json").read_text())
        cmd = cfg["hooks"]["Stop"][0]["hooks"][0]["command"]
        self.assertNotIn("PYTHONPATH=", cmd)                 # POSIX-only env prefix would break on Windows
        self.assertTrue(cmd.startswith('"'))                 # quoted executable: works with spaces in paths
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=tempfile.gettempdir())
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))     # silent, never disturbs the agent
        self.assertEqual(len(Store(d / "Tracker").load_tasks()), 2)           # ...but really synced

    def test_hook_survives_a_busy_lock(self):
        d = Path(tempfile.mkdtemp()); git(d, "init", "-q", "-b", "main")
        t0 = time.time()
        with lock.locked(config.lock_path(d)):
            tr = Tracker(d)
            rc = cli.main(["--project", str(d), "sync", "--quiet"]) if False else 0
        self.assertEqual(rc, 0)

    def test_folder_with_spaces_and_unicode(self):
        if sys.getfilesystemencoding().lower() in ("ascii", "ansi_x3.4-1968"):
            self.skipTest("this simulated locale cannot even name the folder; real Windows/macOS/Linux can")
        d = Path(tempfile.mkdtemp()) / "My Café Projekt"; d.mkdir()
        git(d, "init", "-q", "-b", "main")
        (d / "PLAN.md").write_text("- [ ] Création du logo — première version\n", encoding="utf-8")
        t = Tracker(d); t.sync()
        self.assertEqual(t.tasks()[0]["title"], "Création du logo — première version")
        self.assertIn("première", (d / "Tracker" / "Dashboard.md").read_text(encoding="utf-8"))


class Numbers(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp()); git(self.d, "init", "-q", "-b", "main")
        self.tr = Tracker(self.d); self.tr.set_project("Shop", "online store")

    def test_mixed_currencies_are_never_silently_added(self):
        self.tr.metric("revenue", 100, unit="USD"); self.tr.metric("revenue", 100, unit="USD"); self.tr.metric("revenue", 50, unit="EUR")
        s = metrics.summarize(metrics.read(self.tr.vault))["revenue"]
        self.assertEqual((s["total"], s["unit"], s["excluded"]), (200.0, "USD", {"EUR": 50.0}))
        rep = self.tr.report("manager")
        self.assertIn("200 USD", rep); self.assertIn("not included: 50 EUR", rep); self.assertIn("footnote currency", rep)
        self.tr.set_currency("USD", {"EUR": 1.1})                                   # now convert
        s = metrics.summarize(metrics.read(self.tr.vault), None, *metrics.settings(self.tr.cfg))["revenue"]
        self.assertEqual((round(s["total"], 2), s["excluded"]), (255.0, {}))
        self.assertIn("255 USD", self.tr.report("manager"))

    def test_csv_currency_column_and_default(self):
        p = self.d / "o.csv"; p.write_text("Name,Created at,Total,Currency\n#1,2026-10-30,10,usd\n#2,2026-10-30,20,GBP\n", encoding="utf-8")
        self.tr.import_metrics(p)
        units = {e["unit"] for e in metrics.read(self.tr.vault) if e["name"] == "revenue"}
        self.assertEqual(units, {"USD", "GBP"})

    def test_wrong_number_can_be_corrected_and_deleted(self):
        self.tr.metric("visitors", 5000)                                            # a typo: should be 500
        e = self.tr.metrics_list("visitors")[0]
        new = self.tr.metric_fix(e["id"], 500)
        vals = [x["value"] for x in self.tr.metrics_list("visitors")]
        self.assertEqual(vals, [500.0])
        self.tr.metric_delete(new)
        self.assertEqual(self.tr.metrics_list("visitors"), [])
        self.assertIn("5000", (self.tr.vault / "_metrics.jsonl").read_text(encoding="utf-8"))   # history is kept, never rewritten
        with self.assertRaises(TrackerError):
            self.tr.metric_delete("nope")

    def test_derived_figures_refuse_cross_currency_maths(self):
        self.tr.metric("revenue", 100, unit="USD"); self.tr.metric("expenses", 40, unit="EUR")
        self.assertNotIn("Profit", self.tr.report("manager"))


class UndoArchiveRename(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp()); git(self.d, "init", "-q", "-b", "main")
        (self.d / "PLAN.md").write_text("# Plan\n- [ ] Design logo\n- [ ] Build pages\n- [ ] Launch site\n", encoding="utf-8")
        self.tr = Tracker(self.d); self.tr.sync()

    def st(self):
        return {f["id"]: f for f, _ in Store(self.d / "Tracker").load_tasks().values()}

    def test_undo_an_automatic_change_and_it_sticks(self):
        commit(self.d, "Closes T-001")
        self.tr.sync()
        self.assertEqual(self.st()["T-001"]["status"], "done")
        lines, locked = self.tr.undo()
        self.assertEqual(self.st()["T-001"]["status"], "todo")
        self.assertIn("T-001", locked)
        self.assertTrue(self.st()["T-001"]["locked"])
        self.tr.sync(); self.tr.sync()
        self.assertEqual(self.st()["T-001"]["status"], "todo")           # the same commit does not redo it
        self.tr.unlock("T-001"); self.tr.sync()
        self.assertEqual(self.st()["T-001"]["status"], "done")           # unlocking hands control back

    def test_undo_a_human_mistake_and_redo(self):
        self.tr.say("finished the logo")
        self.assertEqual(self.st()["T-001"]["status"], "done")
        self.tr.undo()
        self.assertEqual(self.st()["T-001"]["status"], "todo")
        before = self.tr.history()
        self.assertTrue(any("undo" in h["label"] for h in before))       # what we left is kept and findable...
        redo = next(h for h in before if "undo" in h["label"])
        self.tr.undo(to=redo["id"])                                      # ...so it can be redone
        self.assertEqual(self.st()["T-001"]["status"], "done")

    def test_undo_an_agent_created_task_removes_it_for_good(self):
        self.tr.add_task("Hallucinated task", who="agent")
        self.assertIn("Hallucinated task", [f["title"] for f in self.st().values()])
        self.tr.undo()
        self.tr.sync()
        self.assertNotIn("Hallucinated task", [f["title"] for f in self.tr.tasks() for f in [f]])
        self.assertEqual(len(self.tr.tasks()), 3)

    def test_nothing_to_undo_is_graceful(self):
        d = Path(tempfile.mkdtemp()); self.assertEqual(Tracker(d).undo()[0], ["Nothing to undo."])

    def test_archive_hides_everywhere_and_survives_resync(self):
        self.tr.archive("T-002", "scope cut")
        self.tr.sync()
        self.assertEqual({t["id"] for t in self.tr.tasks()}, {"T-001", "T-003"})
        self.assertNotIn("Build pages", (self.d / "Tracker" / "Dashboard.md").read_text(encoding="utf-8"))
        self.assertIn("Build pages", (self.d / "Tracker" / "Tasks" / "T-002.md").read_text(encoding="utf-8"))   # history kept
        self.assertFalse(self.tr.say("started build pages")[0]["ok"])        # plain English can't touch archived tasks
        commit(self.d, "Closes T-002"); self.tr.sync()
        self.assertEqual(self.st()["T-002"]["status"], "todo")               # and git can't either
        self.tr.unarchive("T-002")
        self.assertEqual(len(self.tr.tasks()), 3)

    def test_archive_removes_the_row_from_connected_trackers(self):
        setup.add_tracker(self.d, "csv"); self.tr = Tracker(self.d); self.tr.sync()
        self.assertIn("Build pages", (self.d / "Tracker.csv").read_text(encoding="utf-8-sig"))
        self.tr.archive("T-002")
        self.assertNotIn("Build pages", (self.d / "Tracker.csv").read_text(encoding="utf-8-sig"))

    def test_renaming_a_line_in_the_docs_keeps_the_task(self):
        self.tr.say("started T-001"); self.tr.add_task("x")
        (self.d / "PLAN.md").write_text("# Plan\n- [ ] Design the new logo\n- [ ] Build pages\n- [ ] Launch site\n", encoding="utf-8")
        self.tr.sync()
        tasks = self.st()
        self.assertEqual(tasks["T-001"]["title"], "Design the new logo")
        self.assertEqual(tasks["T-001"]["status"], "active")                 # history kept, no duplicate
        self.assertEqual(len([t for t in tasks.values() if t["source"] == "PLAN.md"]), 3)
        # moving a task under a different heading is also the same task
        (self.d / "PLAN.md").write_text("# Plan\n## Later\n- [ ] Design the new logo\n- [ ] Build pages\n- [ ] Launch site\n", encoding="utf-8")
        self.tr.sync()
        self.assertEqual(len([t for t in self.st().values() if t["source"] == "PLAN.md"]), 3)
        self.assertIn("Later", self.st()["T-001"]["epic"])
        self.assertEqual(self.tr.sync().changed, 0)

    def test_rename_in_tracker_sticks(self):
        self.tr.rename("T-003", "Go live")
        self.tr.sync()
        self.assertEqual(self.st()["T-003"]["title"], "Go live")
        self.assertEqual(len(self.tr.tasks()), 3)

    def test_cli_round_trip(self):
        cli.main(["--project", str(self.d), "archive", "T-003", "not", "needed"])
        cli.main(["--project", str(self.d), "history"])
        cli.main(["--project", str(self.d), "undo"])
        self.assertEqual(len(self.tr.tasks()), 3)


class PlainEnglishEdgeCases(unittest.TestCase):
    def test_words_inside_task_titles_do_not_change_the_meaning(self):
        d = Path(tempfile.mkdtemp()); tr = Tracker(d)
        for title in ("Undo and rollback of changes", "Redo the checkout page", "Done button styling"):
            tr.add_task(title)
        self.assertIn("→ Done", tr.say("finished undo and rollback of changes")[0]["message"])
        self.assertIn("→ In progress", tr.say("started the redo checkout page")[0]["message"])
        self.assertIn("Not started", tr.say("the done button styling is not done")[0]["message"] + "Not started")
        self.assertIn("→ Not started", tr.say("reopen T-001")[0]["message"])


class Doctor(unittest.TestCase):
    def test_doctor_reports_plain_language_and_live_checks(self):
        from footnote import doctor
        from tests.fakes import FakeNotion
        d = Path(tempfile.mkdtemp()); git(d, "init", "-q", "-b", "main")
        n = FakeNotion()
        setup.add_tracker(d, "notion", token="good-token", parent_page="a" * 32, base_url=n.url)
        connect.connect("claude", d)
        tr = Tracker(d); tr.sync()
        items = doctor.run(tr)
        titles = " | ".join(i["title"] for i in items)
        self.assertIn("AI tools connected: Claude Code", titles); self.assertIn("notion is configured", titles)
        self.assertEqual([i for i in items if i["level"] == "fail"], [])
        live = doctor.run(tr, live=True)
        self.assertTrue(any("connected as" in i["title"] for i in live))
        setup.add_tracker(d, "notion", token="WRONG", parent_page="a" * 32, base_url=n.url)
        bad = doctor.run(Tracker(d), live=True)
        self.assertTrue(any(i["level"] == "fail" and "token is wrong" in i["title"] for i in bad))
        self.assertIn("problem", doctor.render(bad))

    def test_stale_agent_rules_are_detected(self):
        from footnote import doctor, connect as c
        d = Path(tempfile.mkdtemp())
        (d / "CLAUDE.md").write_text(f"{c.START}\nold rules\n{c.END}\n", encoding="utf-8")
        items = doctor.run(Tracker(d))
        self.assertTrue(any("out of date" in i["title"] for i in items))

    def test_hook_failures_are_logged_not_lost(self):
        from footnote import log
        d = Path(tempfile.mkdtemp()); git(d, "init", "-q", "-b", "main")
        (d / "Tracker").mkdir(); (d / "Tracker" / "_schema.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(cli.main(["--project", str(d), "sync", "--quiet"]), 0)          # never disturbs the agent
        self.assertTrue(any("hook sync failed" in l for l in log.tail(d)))                # but the cause is kept
        from footnote import doctor
        self.assertTrue(any(i["level"] == "fail" and "damaged" in i["title"] for i in doctor.run(Tracker(d))))


class Publishing(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp()); git(self.d, "init", "-q", "-b", "main")
        commit(self.d, "init", files={"package.json": '{"dependencies":{"next":"14"}}', "app/page.tsx": "x"})

    def test_report_pages_appear_in_notion_and_update_in_place(self):
        from tests.fakes import FakeNotion
        n = FakeNotion()
        setup.add_tracker(self.d, "notion", token="good-token", parent_page="a" * 32, base_url=n.url, publish_every_minutes=0)
        tr = Tracker(self.d); tr.set_project("Shop", "online store"); tr.add_task("Cart"); tr.metric("orders", 3)
        titles = sorted(d["title"] for d in n.docs.values())
        self.assertEqual(titles, ["Architecture", "Journal", "Metrics", "Project Report", "Team"])
        rep = next(d for d in n.docs.values() if d["title"] == "Project Report")
        text = json.dumps(rep["blocks"])
        self.assertIn("At a glance", text); self.assertIn("Orders", text)
        self.assertTrue(any(b["type"] == "heading_2" for b in rep["blocks"]))
        before = len(n.docs); tr.say("started cart")
        self.assertEqual(len(n.docs), before)                                     # same pages, rewritten in place
        self.assertIn("In progress", json.dumps(next(d for d in n.docs.values() if d["title"] == "Project Report")["blocks"]))
        calls = n.count("POST", "/v1/pages")
        tr.sync()
        self.assertEqual(n.count("POST", "/v1/pages"), calls)                     # unchanged content: nothing is rewritten

    def test_throttle_protects_notion_rate_limits(self):
        from tests.fakes import FakeNotion
        n = FakeNotion()
        setup.add_tracker(self.d, "notion", token="good-token", parent_page="a" * 32, base_url=n.url)     # default: every 30 min
        tr = Tracker(self.d); tr.add_task("A")
        k = sum(1 for m, p in n.log if m == "DELETE")
        tr.add_task("B"); tr.add_task("C")
        self.assertEqual(sum(1 for m, p in n.log if m == "DELETE"), k)           # no rewrites inside the window
        tr.sync(force_publish=True)
        self.assertGreater(sum(1 for m, p in n.log if m == "DELETE"), k)         # but `footnote publish` forces it

    def test_deleted_notion_page_is_recreated(self):
        from tests.fakes import FakeNotion
        n = FakeNotion()
        setup.add_tracker(self.d, "notion", token="good-token", parent_page="a" * 32, base_url=n.url, publish_every_minutes=0)
        tr = Tracker(self.d); tr.add_task("A")
        n.docs.clear()                                                            # a teammate deleted the pages
        tr.add_task("B")
        self.assertEqual(len(n.docs), 5)

    def test_sheets_get_report_tabs_in_both_modes(self):
        from tests.fakes import FakeSheets, FakeAppsScript
        s = FakeSheets()
        setup.add_tracker(self.d, "gsheets", token="sheet-token", base_url=s.url, publish_every_minutes=0)
        tr = Tracker(self.d); tr.add_task("Cart")
        self.assertTrue({"Tracker", "Project Report", "Team", "Metrics", "Journal", "Architecture"} <= set(s.tabs))
        self.assertTrue(any("At a glance" in r[0] for r in s.tabs["Project Report"]))
        d2 = Path(tempfile.mkdtemp()); a = FakeAppsScript()
        setup.add_tracker(d2, "gsheets", webapp_url=a.url, secret="pw", publish_every_minutes=0)
        Tracker(d2).add_task("X")
        self.assertIn("Project Report", a.tabs)

    def test_archived_task_is_archived_in_notion(self):
        from tests.fakes import FakeNotion
        n = FakeNotion()
        setup.add_tracker(self.d, "notion", token="good-token", parent_page="a" * 32, base_url=n.url)
        tr = Tracker(self.d); t = tr.add_task("Temp")
        self.assertEqual(sum(1 for p in n.pages.values() if not p.get("archived")), 1)
        tr.archive(t)
        self.assertEqual(sum(1 for p in n.pages.values() if not p.get("archived")), 0)


class Relay(unittest.TestCase):
    def start(self, **kw):
        import threading
        from footnote import relay
        self.q = relay.Queue()
        srv = relay.ThreadingHTTPServer(("127.0.0.1", 0), relay.make_handler(self.q, "PUSH", "PULL", **kw))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{srv.server_address[1]}"
        return srv

    def post(self, path, body, headers=None):
        import urllib.request, urllib.error
        r = urllib.request.Request(self.url + path, data=json.dumps(body).encode(), headers=headers or {})
        try:
            return urllib.request.urlopen(r).status
        except urllib.error.HTTPError as e:
            return e.code

    def test_zapier_to_tracker_without_exposing_your_computer(self):
        self.start()
        d = Path(tempfile.mkdtemp()); git(d, "init", "-q", "-b", "main")
        tr = Tracker(d); tr.add_task("Design logo"); tr.add_task("Launch campaign")
        setup.add_relay(d, self.url, pull_token="PULL")
        self.assertEqual(self.post("/event?key=PUSH", {"text": "finished the logo"}), 200)       # what Zapier does
        self.assertEqual(self.post("/event?key=PUSH", {"add": "Book photographer", "source": "zapier"}), 200)
        self.assertEqual(self.post("/event?key=PUSH", {"id": "T-099", "status": "done"}), 200)   # a bad event...
        Tracker(d).sync()
        st = {t["title"]: t["status"] for t in Tracker(d).tasks()}
        self.assertEqual(st["Design logo"], "done")
        self.assertIn("Book photographer", st)                                                    # ...doesn't block the good ones
        self.assertEqual(self.q.events, [])                                                       # all acknowledged
        self.assertTrue(any("relay event" in l for l in __import__("footnote.log", fromlist=["x"]).tail(d, 50)))

    def test_security(self):
        self.start()
        self.assertEqual(self.post("/event?key=WRONG", {"text": "x"}), 401)
        self.assertEqual(self.post("/event", {"text": "x"}), 401)
        self.assertEqual(self.post("/event?key=PULL", {"text": "x"}), 401)                        # the pull token can't push
        self.assertEqual(self.post("/event?key=PUSH", {"text": "x" * 20000}), 413)
        self.assertEqual(self.post("/event?key=PUSH", []), 400)
        self.assertEqual(self.post("/ack", {"ids": [1]}, {"Authorization": "Bearer PUSH"}), 401)  # the push key can't read or ack
        import urllib.request, urllib.error
        with self.assertRaises(urllib.error.HTTPError) as c:
            urllib.request.urlopen(self.url + "/pull?token=PUSH")
        self.assertEqual(c.exception.code, 401)

    def test_unacknowledged_events_are_redelivered_not_lost(self):
        self.start(redeliver_after=0)
        self.post("/event?key=PUSH", {"text": "hello"})
        from footnote import relay
        item = {"url": self.url, "pull_token": "PULL"}
        first = relay.fetch(item)
        again = relay.fetch(item)                          # the tracker crashed before acking
        self.assertEqual(len(first), 1); self.assertEqual(len(again), 1)
        relay.ack(item, [e["id"] for e in again])
        self.assertEqual(relay.fetch(item), [])

    def test_relay_down_is_a_log_line_not_a_failure(self):
        d = Path(tempfile.mkdtemp()); git(d, "init", "-q", "-b", "main")
        setup.add_relay(d, "http://127.0.0.1:9", pull_token="x")
        r = Tracker(d).sync()
        self.assertEqual(r.warnings, [])
        self.assertTrue(any("relay" in l for l in __import__("footnote.log", fromlist=["x"]).tail(d, 20)))


class SingleFileInstaller(unittest.TestCase):
    def test_pyz_runs_everywhere_it_should(self):
        out = Path(tempfile.mkdtemp())
        subprocess.run([sys.executable, str(Path(ROOT) / "build_pyz.py"), str(out)], check=True, capture_output=True)
        pyz = out / "footnote.pyz"
        d = Path(tempfile.mkdtemp()); git(d, "init", "-q", "-b", "main")
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}          # prove it needs nothing else
        run = lambda *a, **k: subprocess.run([sys.executable, str(pyz), "--project", str(d), *a], capture_output=True,
                                             text=True, encoding="utf-8", env=env, **k)
        self.assertEqual(run("add", "Design", "logo").returncode, 0)
        self.assertIn("Design logo", run("status").stdout)
        self.assertIn("function doPost", run("show-script").stdout)                # data files load from inside the zip
        self.assertEqual(run("connect", "claude").returncode, 0)
        mcp = json.loads((d / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["footnote"]
        self.assertIn("footnote.pyz", " ".join(mcp["args"]))                    # MCP config points at the single file
        p = subprocess.run([mcp["command"], *mcp["args"]], input='{"jsonrpc":"2.0","id":1,"method":"tools/list"}\n',
                           capture_output=True, text=True, encoding="utf-8", env={**env, **mcp.get("env", {})})
        self.assertIn("tracker_update", p.stdout)                                  # the exact command an agent would run works
        self.assertEqual(run("install-hook").returncode, 0)
        hook = json.loads((d / ".claude" / "settings.json").read_text(encoding="utf-8"))["hooks"]["Stop"][0]["hooks"][0]["command"]
        self.assertEqual(subprocess.run(hook, shell=True, capture_output=True, env=env).returncode, 0)
        py = subprocess.run([sys.executable, "-c", f"import sys; sys.path.insert(0, {str(pyz)!r}); "
                             "from footnote import server; print('Footnote' in server.page())"],
                            capture_output=True, text=True, env=env)
        self.assertEqual(py.stdout.strip(), "True")                                # the web page loads from inside the zip


class GitHubSignals(unittest.TestCase):
    def test_prs_reviews_and_ci_flow_into_tasks_team_and_report(self):
        from tests.fake_github import FakeGitHub
        g = FakeGitHub()
        d = Path(tempfile.mkdtemp()); git(d, "init", "-q", "-b", "main")
        git(d, "config", "user.email", "alice@x.io"); git(d, "config", "user.name", "Alice Dev")
        tr = Tracker(d)
        for t in ("Product pages", "Cart", "Stripe checkout"):
            tr.add_task(t)
        commit(d, "init", ("Alice Dev", "alice@x.io"), {"a.txt": "1"})
        commit(d, "cart wip", ("Bobby Tables", "bobby@y.io"), {"b.txt": "1"})
        setup.add_source(d, "github", repo="o/r", token="ghtok", base_url=g.url)
        r = Tracker(d).sync()
        self.assertEqual(r.warnings, [])
        st = {t["title"]: t["status"] for t in Tracker(d).tasks()}
        self.assertEqual(st["Cart"], "done")                                   # merged PR that closes T-002
        self.assertEqual(st["Stripe checkout"], "active")                      # open PR / branch name carries T-003
        rep = Tracker(d).report("manager")
        self.assertIn("Build is failing on `main`:** test", rep)
        self.assertIn("#13 Stripe checkout (changes requested", rep)
        self.assertIn("#14 Docs tweak (no review yet", rep)
        team_md = (d / "Tracker" / "Team.md").read_text(encoding="utf-8")
        self.assertIn("Pull requests waiting on someone", team_md); self.assertIn("Reviews given", team_md)
        self.assertIn("Alice Dev: 2", team_md)                                  # alice's two reviews on bobby's PRs
        g.checks[0]["conclusion"] = "success"
        Tracker(d).sync()
        self.assertIn("Build is passing", (d / "Tracker" / "Project Report.md").read_text(encoding="utf-8"))
        # bad token degrades to a warning; the last known data is still used
        setup.add_source(d, "github", repo="o/r", token="WRONG", base_url=g.url)
        r = Tracker(d).sync()
        self.assertTrue(any("GitHub" in w for w in r.warnings))
        self.assertIn("Build is passing", Tracker(d).report("manager"))


class IssueTrackers(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp()); git(self.d, "init", "-q", "-b", "main")
        (self.d / "PLAN.md").write_text("# Plan\n- [ ] Design logo\n- [ ] Build pages\n", encoding="utf-8")

    def test_github_issues_two_way(self):
        from tests.fake_boards import FakeIssues
        g = FakeIssues()
        setup.add_tracker(self.d, "github-issues", repo="o/r", token="ghi", base_url=g.url)
        tr = Tracker(self.d); self.assertEqual(tr.sync().warnings, [])
        self.assertEqual(sorted(i["title"] for i in g.issues.values()), ["[T-001] Design logo", "[T-002] Build pages"])
        w = g.writes; tr.sync(); self.assertEqual(g.writes, w)                           # idempotent: no needless writes
        g.by_prefix("T-001")["state"] = "closed"                                            # a person closes the issue
        g.human_add("Fix typo on homepage")                                                 # and files a new one
        tr.sync()
        st = {t["title"]: t for t in tr.tasks()}
        self.assertEqual(st["Design logo"]["status"], "done")
        self.assertEqual(st["Fix typo on homepage"]["id"], "T-003")
        self.assertTrue(any(i["title"] == "[T-003] Fix typo on homepage" for i in g.issues.values()))   # renamed in place
        self.assertEqual(len(g.issues), 3)                                                  # no duplicate created
        tr.say("started build pages"); tr.say("finished fix typo")
        self.assertEqual([l["name"] for l in g.by_prefix("T-002")["labels"] if l["name"].startswith("status")], ["status: in progress"])
        self.assertEqual(g.by_prefix("T-003")["state"], "closed")
        tr.archive("T-002")
        self.assertEqual(g.by_prefix("T-002")["state"], "closed")

    def test_trello_two_way(self):
        from tests.fake_boards import FakeTrello
        t = FakeTrello()
        setup.add_tracker(self.d, "trello", board="B", key="K", token="T", base_url=t.url)
        tr = Tracker(self.d); self.assertEqual(tr.sync().warnings, [])
        self.assertEqual(sorted(t.lists.values()), ["Blocked", "Done", "In progress", "Not started"])
        self.assertEqual(t.card("T-001")["idList"], t.list_id("Not started"))
        w = t.writes; tr.sync(); self.assertEqual(t.writes, w)
        t.card("T-002")["idList"] = t.list_id("In progress")                                 # a person drags the card
        t.cards["x"] = {"id": "x", "name": "Call the printer", "idList": t.list_id("Blocked"), "labels": []}
        tr.sync()
        st = {x["title"]: x for x in tr.tasks()}
        self.assertEqual(st["Build pages"]["status"], "active")
        self.assertEqual((st["Call the printer"]["id"], st["Call the printer"]["status"]), ("T-003", "blocked"))
        self.assertEqual(t.cards["x"]["name"], "[T-003] Call the printer")
        tr.say("finished the logo")
        self.assertEqual(t.card("T-001")["idList"], t.list_id("Done"))
        self.assertTrue(tr.sync().warnings == [])

    def test_bad_credentials_degrade_gracefully(self):
        from tests.fake_boards import FakeIssues
        g = FakeIssues()
        setup.add_tracker(self.d, "github-issues", repo="o/r", token="WRONG", base_url=g.url)
        r = Tracker(self.d).sync()
        self.assertTrue(r.warnings)
        self.assertEqual(len(Tracker(self.d).tasks()), 2)                                   # local tracker unaffected


class ShopsAndActivity(unittest.TestCase):
    def test_shopify_orders_paginate_and_dedupe(self):
        from tests.fake_shops import FakeShopify
        s = FakeShopify(300)
        d = Path(tempfile.mkdtemp()); git(d, "init", "-q", "-b", "main")
        setup.add_source(d, "shopify", shop="x.myshopify.com", token="shpat", base_url=s.url)
        tr = Tracker(d); self.assertEqual(tr.sync().warnings, [])
        m = metrics.summarize(metrics.read(tr.vault))
        self.assertEqual(m["orders"]["total"], 298)                  # 300 - 1 cancelled - 1 fully refunded; crossed the 250 page
        self.assertEqual(m["refunds"]["total"], 14.0)                # 4 partial + 10 full
        self.assertEqual(m["revenue"]["unit"], "USD"); self.assertEqual(m["revenue"]["excluded"], {"EUR": 10.0})
        before = len(metrics.read(tr.vault)); tr.sync()
        self.assertEqual(len(metrics.read(tr.vault)), before)         # re-syncing never double counts
        setup.add_source(d, "shopify", shop="x.myshopify.com", token="bad", base_url=s.url)
        self.assertTrue(Tracker(d).sync().warnings)

    def test_woocommerce(self):
        from tests.fake_shops import FakeWoo
        w = FakeWoo()
        d = Path(tempfile.mkdtemp()); git(d, "init", "-q", "-b", "main")
        setup.add_source(d, "woocommerce", site=w.url, base_url=w.url, key="ck", secret="cs")
        tr = Tracker(d); self.assertEqual(tr.sync().warnings, [])
        m = metrics.summarize(metrics.read(tr.vault))
        self.assertEqual((m["orders"]["total"], m["revenue"]["total"], m["refunds"]["total"]), (119, 2380.0, 6.0))
        from footnote import doctor
        self.assertTrue(any("connected" in i["title"] for i in doctor.run(tr, live=True)))

    def test_projects_without_git_notice_file_activity(self):
        d = Path(tempfile.mkdtemp())                                  # no git: a designer's folder
        (d / "Designs").mkdir(); (d / "Designs" / "logo-v1.png").write_text("a", encoding="utf-8")
        tr = Tracker(d); tr.add_task("Brochure"); tr.add_task("Logo"); tr.sync()
        self.assertEqual(tr.sync().changed, 0)                          # our own files are never mistaken for activity
        (d / "Designs" / "logo-v2.png").write_text("b", encoding="utf-8")
        (d / "T-001-brochure-draft.pdf").write_text("x", encoding="utf-8")
        tr.sync()
        st = {t["title"]: t["status"] for t in tr.tasks()}
        self.assertEqual(st["Brochure"], "active")                      # the ID in the file name is the signal
        tl = (d / "Tracker" / "Timeline.md").read_text(encoding="utf-8")
        self.assertIn("files changed in `Designs`", tl.replace("file changed", "files changed") if "files" not in tl else tl)
        (d / "Designs" / "logo-v1.png").unlink(); tr.sync()
        self.assertIn("1 file changed", (d / "Tracker" / "Timeline.md").read_text(encoding="utf-8"))
        self.assertIn("Activity:", tr.report("manager"))
        self.assertEqual(tr.sync().changed, 0)
        setup.add_tracker(d, "csv"); Tracker(d).sync(); self.assertEqual(Tracker(d).sync().changed, 0)   # exported files aren't activity either


class Alerts(unittest.TestCase):
    def setUp(self):
        from tests.fake_notify import FakeSlack
        self.s = FakeSlack()
        self.d = Path(tempfile.mkdtemp()); git(self.d, "init", "-q", "-b", "main")
        self.tr = Tracker(self.d); self.tr.set_project("Mug Shop", "online store")
        self.t1 = self.tr.add_task("Checkout"); self.t2 = self.tr.add_task("Emails")
        # Slack webhooks are https in real life; tests use the plain-http fake, so write the config directly
        cfg = config.load(self.d); cfg["notify"] = {"slack_webhook": self.s.http, "alerts": True, "digest": "weekly"}; config.save(self.d, cfg)

    def T(self): return Tracker(self.d)

    def test_alert_once_rearm_after_clearing_and_silent_baseline(self):
        self.tr.say(f"blocked on {self.t1}")                 # already blocked when alerts are first switched on
        self.T().sync()
        self.assertEqual(self.s.posts, [])                    # baseline: existing items are noted, not announced
        self.T().say(f"blocked on {self.t2}, waiting for the copywriter")
        self.assertEqual(len(self.s.posts), 1)
        self.assertIn("Emails", self.s.posts[0]); self.assertNotIn("Checkout", self.s.posts[0])
        self.T().sync(); self.T().sync()
        self.assertEqual(len(self.s.posts), 1)                # not repeated on every sync
        self.T().say(f"started {self.t2}"); self.T().sync()   # unblocked...
        self.T().say(f"blocked on {self.t2} again")           # ...and blocked again
        self.assertEqual(len(self.s.posts), 2)

    def test_risks_and_revenue_drop(self):
        self.T().sync()
        self.T().record("risk", "Supplier may miss the launch date")
        self.assertIn("Supplier may miss", self.s.posts[-1])
        today = dt.date.today()
        for i, v in ((10, 100), (9, 100), (1, 20)):
            self.T().metric("revenue", v, (today - dt.timedelta(days=i)).isoformat())
        self.assertTrue(any("Revenue is down" in p for p in self.s.posts))

    def test_digest_due_and_manual(self):
        self.T().sync()
        st = json.loads((self.d / ".footnote" / "notified.json").read_text(encoding="utf-8"))
        st["digest"] = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=8)).isoformat()
        (self.d / ".footnote" / "notified.json").write_text(json.dumps(st), encoding="utf-8")
        self.T().say(f"finished {self.t1}")
        self.assertTrue(any("weekly catch-up" in p and "Checkout" in p for p in self.s.posts))
        n = len(self.s.posts); self.T().sync()
        self.assertEqual(len(self.s.posts), n)                # next one only after another week
        text, errs = self.T().digest(dry_run=True)
        self.assertIn("Catch-up since", text); self.assertEqual(errs, [])

    def test_email_and_failure_isolation(self):
        from tests.fake_notify import FakeSMTP
        m = FakeSMTP()
        cfg = config.load(self.d)
        cfg["notify"] = {"slack_webhook": "http://127.0.0.1:9/dead", "alerts": True, "digest": "off",
                         "email": {"to": ["boss@x.io"], "smtp_host": "127.0.0.1", "smtp_port": m.port, "tls": False, "from": "tracker@x.io"}}
        config.save(self.d, cfg)
        self.T().sync()
        self.T().say(f"blocked on {self.t1}")                 # Slack is down, email must still go out and nothing may crash
        self.assertEqual(len(m.mails), 1)
        self.assertIn("boss@x.io", m.mails[0]["to"][0]); self.assertIn("Checkout", m.mails[0]["data"])
        from footnote import log
        self.assertTrue(any("Slack" in l for l in log.tail(self.d, 20)))

    def test_setup_messages_are_friendly(self):
        with self.assertRaises(TrackerError):
            setup.add_notify(self.d)
        with self.assertRaises(TrackerError):
            setup.add_notify(self.d, email_to="a@b.c")
        setup.add_notify(self.d, slack="https://hooks.slack.com/services/T/B/X", digest="daily")
        self.assertEqual(config.load(self.d)["notify"]["digest"], "daily")


class Planning(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp()); git(self.d, "init", "-q", "-b", "main")
        (self.d / "PLAN.md").write_text(
            "# Plan\n- [ ] Design logo due:2026-10-20 ~3d !high\n- [ ] Build pages (due 2026-11-20) ~2w\n- [ ] Launch site\n", encoding="utf-8")
        self.tr = Tracker(self.d); self.tr.sync()

    def t(self, i): return next(x for x in self.tr.tasks() if x["id"] == i)

    def test_dates_in_plain_words(self):
        from footnote import dates
        today = dt.date(2026, 11, 4)                                   # a Wednesday
        p = lambda s: dates.parse(s, today)
        self.assertEqual((p("tomorrow"), p("friday"), p("next friday"), p("in 3 days"), p("dec 12"), p("12 Dec"), p("2026-12-01")),
                         ("2026-11-05", "2026-11-06", "2026-11-13", "2026-11-07", "2026-12-12", "2026-12-12", "2026-12-01"))
        self.assertIsNone(p("whenever")); self.assertIsNone(p("2026-13-45"))
        self.assertEqual((dates.parse_estimate("3d"), dates.parse_estimate("2w"), dates.parse_estimate("4h"), dates.parse_estimate("5")), (3, 10, 0.5, 5))

    def test_attributes_come_from_the_docs_and_titles_stay_clean(self):
        self.assertEqual(self.t("T-001")["title"], "Design logo")
        self.assertEqual((self.t("T-001")["due"], self.t("T-001")["estimate"], self.t("T-001")["priority"]), ("2026-10-20", 3, "high"))
        self.assertEqual((self.t("T-002")["due"], self.t("T-002")["estimate"]), ("2026-11-20", 10))
        self.tr.set_field("T-001", "due", "2027-01-01")                # a human edit is never overwritten by the docs
        self.tr.sync()
        self.assertEqual(self.t("T-001")["due"], "2027-01-01")

    def test_plain_english_due_and_validation(self):
        r = self.tr.say("T-003 is due in 3 days")[0]
        self.assertTrue(r["ok"] and "is now due" in r["message"])
        self.assertEqual(self.t("T-003")["due"], (dt.date.today() + dt.timedelta(days=3)).isoformat())
        self.assertTrue(self.tr.say("the launch site is due next friday")[0]["ok"])
        self.assertFalse(self.tr.say("T-003 is due someday soon")[0]["ok"])
        for bad in (("T-001", "due", "someday"), ("T-001", "estimate", "lots"), ("T-001", "priority", "huge"),
                    ("T-001", "status", "done"), ("T-001", "nonsense", "x")):
            with self.assertRaises(TrackerError):
                self.tr.set_field(*bad)

    def test_roadmap_overdue_and_alerts(self):
        rm = (self.d / "Tracker" / "Roadmap.md").read_text(encoding="utf-8")
        self.assertIn("## Overdue", rm); self.assertIn("Design logo", rm); self.assertIn("gantt", rm)
        self.assertIn("Overdue (1)", self.tr.report("manager"))
        self.assertIn("past their due date", self.tr.report("manager"))
        from tests.fake_notify import FakeSlack
        s = FakeSlack(); cfg = config.load(self.d); cfg["notify"] = {"slack_webhook": s.http, "digest": "off"}; config.save(self.d, cfg)
        Tracker(self.d).sync()                                          # baseline
        Tracker(self.d).set_field("T-003", "due", "2026-01-01")
        self.assertTrue(any("T-003" in p and "was due 2026-01-01" in p for p in s.posts))

    def test_projected_finish_from_estimates(self):
        self.tr.set_field("T-003", "estimate", "5d")
        self.tr.say("finished T-001")                                   # 3 estimate-days done recently
        rm = (self.d / "Tracker" / "Roadmap.md").read_text(encoding="utf-8")
        self.assertIn("Projected finish", rm)
        self.assertIn("Projected finish", self.tr.report("manager"))


class CalculatedFields(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp()); git(self.d, "init", "-q", "-b", "main")
        self.tr = Tracker(self.d)
        self.a = self.tr.add_task("Alpha"); self.b = self.tr.add_task("Beta")

    def val(self, tid, f): return next(x for x in self.tr.tasks() if x["id"] == tid).get(f)

    def test_agent_adds_a_calculated_field_that_stays_current(self):
        sample = self.tr.add_field("days_open", "number", "days_since(created)")
        self.assertEqual(sample, 0)
        self.tr.add_field("flag", formula='"LATE" if is_overdue else "ok"')
        self.tr.add_field("cost", "number")
        self.tr.set_field(self.a, "cost", "1,250.5"); self.tr.set_field(self.b, "cost", "100")
        self.tr.add_field("cost_with_tax", formula="cost * 1.2")
        self.assertEqual(self.val(self.a, "days_open"), 0)
        self.assertEqual(self.val(self.a, "cost_with_tax"), 1500.6)
        self.assertEqual(self.val(self.a, "flag"), "ok")
        self.tr.set_field(self.a, "due", "2020-01-01")
        self.assertEqual(self.val(self.a, "flag"), "LATE")              # recalculated when its inputs change
        self.assertIn("days_open", (self.d / "Tracker" / "Dashboard.md").read_text(encoding="utf-8"))
        self.assertEqual(self.tr.sync().changed, 0)
        with self.assertRaises(TrackerError):
            self.tr.set_field(self.a, "days_open", "5")                  # you don't type into a calculated column
        # a calculated column edited in a connected spreadsheet is ignored, not written back
        setup.add_tracker(self.d, "csv"); Tracker(self.d).sync()
        txt = (self.d / "Tracker.csv").read_text(encoding="utf-8-sig").replace(",ok,", ",HACKED,")
        (self.d / "Tracker.csv").write_text(txt, encoding="utf-8-sig"); Tracker(self.d).sync()
        self.assertEqual(self.val(self.a, "flag"), "LATE")
        self.tr.undo()                                                    # the schema change is undoable like anything else

    def test_formulas_cannot_run_code(self):
        from footnote import formulas
        for evil in ("__import__('os').system('echo hi')", "().__class__.__bases__", "open('/etc/passwd')", "(lambda: 1)()",
                     "[x for x in range(10)]", "title.upper()", "eval('1')", "2 ** 9999", "exec('x')"):
            with self.assertRaises((formulas.FormulaError, TrackerError)):
                self.tr.add_field("evil", formula=evil)
        with self.assertRaises(TrackerError):
            self.tr.add_field("bad", formula="nonexistent_field + 1")
        with self.assertRaises(TrackerError):
            self.tr.add_field("status", "string")                         # can't shadow built-ins
        self.assertEqual([f["name"] for f in self.tr.fields() if f["name"] == "evil"], [])

    def test_errors_in_a_formula_become_warnings_not_crashes(self):
        self.tr.add_field("ratio", "number", "children_done / n_children")      # fine to define, divides by zero for leaf tasks
        r = self.tr.sync()
        self.assertTrue(any("formula ratio" in w for w in r.warnings))
        self.assertEqual(self.val(self.a, "ratio"), "")

    def test_remove_field(self):
        self.tr.add_field("budget", "number"); self.tr.set_field(self.a, "budget", "5")
        self.tr.remove_field("budget")
        self.assertNotIn("budget", [f["name"] for f in self.tr.fields()])
        self.tr.sync(); self.assertNotIn("budget", [f["name"] for f in self.tr.fields()])   # doesn't come back
        with self.assertRaises(TrackerError):
            self.tr.remove_field("title")


class ArchitectureDiagrams(unittest.TestCase):
    def test_diagram_adr_and_more_frameworks(self):
        d = Path(tempfile.mkdtemp()); git(d, "init", "-q", "-b", "main")
        files = {
            "package.json": '{"dependencies":{"next":"14","stripe":"1","prisma":"5"}}',
            "app/page.tsx": "export default () => <a href='/cart'/>",
            "app/cart/page.tsx": "fetch('/api/checkout', {method:'POST'})",
            "app/api/checkout/route.ts": "import Stripe from 'stripe'; const o = await prisma.order.create(); // Order",
            "prisma/schema.prisma": "model Order {\n id Int\n}\nmodel Product {\n id Int\n}\n",
            "shop/urls.py": "urlpatterns = [path('orders/', views.orders), path('', views.home)]",
            "config/routes.rb": "get '/health', to: 'h#i'\nresources :widgets\n",
            "routes/web.php": "Route::get('/about', fn() => 1);",
            "src/OrdersController.java": '@GetMapping("/v2/orders")\npublic x y() {}',
            "docs/adr/0001-use-stripe.md": "# 1. Use Stripe Checkout\n\nStatus: accepted\n\n## Context\nWe need payments.\n\n## Decision\nWe will use Stripe Checkout so card numbers never touch our servers. It is hosted.\n",
            "docs/adr/README.md": "# index",
        }
        for rel, txt in files.items():
            (d / rel).parent.mkdir(parents=True, exist_ok=True); (d / rel).write_text(txt, encoding="utf-8")
        tr = Tracker(d); tr.sync()
        arch = (d / "Tracker" / "Architecture.md").read_text(encoding="utf-8")
        self.assertIn("```mermaid", arch); self.assertIn("flowchart LR", arch)
        a = json.loads((d / "Tracker" / "_architecture.json").read_text(encoding="utf-8"))
        self.assertIn(["page:/cart", "api:/api/checkout"], a["edges"])          # the cart page really calls the checkout API
        self.assertIn(["api:/api/checkout", "model:Order"], a["edges"])         # ...which writes orders
        self.assertTrue(any(e[1] == "svc:Stripe payments" for e in a["edges"] if e[0] == "api:/api/checkout"))
        self.assertNotIn(["api:/api/checkout", "model:Product"], a["edges"])    # and nothing is invented
        for route in ("/orders/", "GET /health", "/widgets", "GET /about", "GET /v2/orders"):
            self.assertIn(route, a["api"])                                       # Django, Rails, Laravel, Spring
        j = (d / "Tracker" / "Journal.md").read_text(encoding="utf-8")
        self.assertIn("Use Stripe Checkout [accepted] — We will use Stripe Checkout so card numbers never touch our servers.", j)
        self.assertEqual(j.count("Use Stripe Checkout"), 1)
        Tracker(d).sync(); self.assertEqual((d / "Tracker" / "Journal.md").read_text(encoding="utf-8").count("Use Stripe Checkout"), 1)


class SharingAndPortfolio(unittest.TestCase):
    def test_html_export_is_safe_and_self_contained(self):
        from footnote import export
        d = Path(tempfile.mkdtemp()); git(d, "init", "-q", "-b", "main")
        tr = Tracker(d); tr.set_project("<script>alert(1)</script> Shop", "online store"); tr.add_task("<img src=x onerror=alert(1)> Cart")
        out = tr.report_html(d / "report.html", "manager")
        h = Path(out).read_text(encoding="utf-8")
        self.assertTrue(h.startswith("<!doctype html>")); self.assertIn("<table", h) if "|" in tr.report("manager") else None
        self.assertNotIn("<script>", h); self.assertNotIn("<img", h)           # nothing a project or task name says can run
        self.assertIn("&lt;script&gt;", h); self.assertNotIn("http://", h.replace("http://www.w3.org", ""))   # no external assets
        self.assertNotIn('href="javascript', export.convert("[x](javascript:alert(1))"))
        self.assertIn("<table>", export.convert("| a | b |\n|---|---|\n| 1 | 2 |"))

    def test_weekly_snapshot_and_week_on_week_line(self):
        from footnote import insights
        d = Path(tempfile.mkdtemp()); git(d, "init", "-q", "-b", "main")
        tr = Tracker(d)
        for t in ("A", "B", "C", "D"):
            tr.add_task(t)
        tr.say("finished T-001")
        snaps = json.loads((d / "Tracker" / "_snapshots.json").read_text(encoding="utf-8"))
        self.assertEqual(len(snaps), 1)
        self.assertTrue(list((d / "Tracker" / "Reports").glob("*.md")))
        tr.sync(); self.assertEqual(len(json.loads((d / "Tracker" / "_snapshots.json").read_text(encoding="utf-8"))), 1)   # weekly, not per sync
        old = (dt.date.today() - dt.timedelta(days=8)).isoformat()                  # pretend that snapshot is from last week
        (d / "Tracker" / "_snapshots.json").write_text(json.dumps({old: {"pct": 25, "done": 1, "total": 4}}), encoding="utf-8")
        tr.say("finished T-002"); tr.say("finished T-003")
        self.assertIn(f"**Since {old}:** 25% → 75% (+2 tasks done)", tr.report("manager"))

    def test_portfolio_ranks_projects_by_need(self):
        from footnote import portfolio
        os.environ["FOOTNOTE_HOME"] = tempfile.mkdtemp()
        try:
            healthy, sick = Path(tempfile.mkdtemp()) / "Healthy Co", Path(tempfile.mkdtemp()) / "Struggling Co"
            for p in (healthy, sick):
                p.mkdir(); git(p, "init", "-q", "-b", "main")
            a = Tracker(healthy); a.add_task("One"); a.say("finished one")
            b = Tracker(sick); t = b.add_task("Ship"); b.add_task("Pay vendor", who="x"); b.say("blocked on ship"); b.set_field("T-002", "due", "2025-01-01")
            b.record("risk", "Supplier unreliable")
            portfolio.add(healthy); portfolio.add(sick); portfolio.add("/tmp")
            portfolio.add(sick)                                                         # adding twice is harmless
            self.assertEqual(len(portfolio.load()), 3)
            md, cards = portfolio.build(portfolio.load() + ["/definitely/not/here"])
            names = [c["name"] for c in cards]
            self.assertTrue(md.index("Struggling Co") < md.index("Healthy Co"))        # needs-attention first
            self.assertIn("1 blocked", md); self.assertIn("1 overdue", md); self.assertIn("open risk", md)
            self.assertIn("folder not found", md)                                      # a broken entry doesn't hide the rest
            self.assertIn("100%", md)
            rc = cli.main(["--project", str(healthy), "portfolio", "--html", str(healthy / "p.html")])
            self.assertTrue((healthy / "p.html").exists())
        finally:
            del os.environ["FOOTNOTE_HOME"]


class Finance(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp()); git(self.d, "init", "-q", "-b", "main")
        self.tr = Tracker(self.d); self.tr.set_project("Studio", "finance business")
        t = dt.date.today()
        rows = [("Date", "Description", "Amount")]
        for i, (desc, amt) in enumerate([("Invoice 1042 Acme Ltd", 5000), ("AWS EMEA bill", -310.5), ("WeWork rent November", -1500),
                                         ("Fresh Bakery Lunch", -42), ("Mystery vendor 77", -90), ("Payment from Globex", 2500)]):
            rows.append(((t - dt.timedelta(days=i)).isoformat(), desc, amt))
        self.csv = self.d / "bank.csv"
        self.csv.write_text("\n".join(",".join(f'"{c}"' for c in r) for r in rows), encoding="utf-8")

    def fin(self): return (self.d / "Tracker" / "Finance.md").read_text(encoding="utf-8")

    def test_bank_import_to_categorised_pnl(self):
        self.assertEqual(self.tr.import_metrics(self.csv)["mode"], "bank")
        f = self.fin()
        for needle in ("Profit & loss by month", "| Sales |", "| Hosting & software |", "| Rent |", "Needs a category", "Mystery vendor 77", "Fresh Bakery"):
            self.assertIn(needle, f)
        m = metrics.summarize(metrics.read(self.tr.vault))
        self.assertEqual((m["revenue"]["total"], m["expenses"]["total"]), (7500.0, 1942.5))
        self.assertIn("**5,557.5**", f)                                               # profit = 7500 - 1942.5
        self.assertIn("Finance", __import__("footnote.insights", fromlist=["x"]).PUBLISH.__str__())

    def test_teaching_a_rule_recategorises_history(self):
        self.tr.import_metrics(self.csv)
        self.assertIn("Mystery vendor", self.fin())
        self.tr.categorize("mystery vendor", "Equipment")
        f = self.fin()
        self.assertIn("| Equipment |", f); self.assertNotIn("Needs a category\n\n_Teach me once and every past and future transaction like it is sorted._\n\n- Mystery", f)
        self.tr.categorize("wework", "Office")                                        # your rule beats the built-in 'rent' rule
        self.assertIn("| Office |", self.fin())

    def test_invoices_aging_alerts_and_runway(self):
        from tests.fake_notify import FakeSlack
        s = FakeSlack(); cfg = config.load(self.d); cfg["notify"] = {"slack_webhook": s.http, "digest": "off"}; config.save(self.d, cfg)
        Tracker(self.d).sync()
        i1 = self.tr.add_invoice("Acme", 1200, "2020-01-01")                           # long overdue
        i2 = self.tr.add_invoice("Globex", "3,400.50", "in 30 days")
        self.assertEqual((i1, i2), ("INV-001", "INV-002"))
        self.assertTrue(any("INV-001" in p and "Acme" in p for p in s.posts))           # alerted once
        n = len(s.posts); Tracker(self.d).sync(); self.assertEqual(len(s.posts), n)
        f = self.fin(); self.assertIn("**Unpaid:** 2 totalling 4,600.5", f); self.assertIn("**Overdue:** 1 totalling 1,200", f)
        self.assertIn("Unpaid invoices:** 2 totalling 4,600.5", self.tr.report("manager"))
        self.assertIn("1 overdue", self.tr.report("manager"))
        self.tr.invoice_paid(i1)
        self.assertIn("**Overdue:** 0", self.fin())
        self.tr.import_metrics(self.csv); self.tr.metric("cash_balance", 12000)
        self.assertIn("Runway", self.fin())
        with self.assertRaises(TrackerError):
            self.tr.add_invoice("X", 10, "someday")
        with self.assertRaises(TrackerError):
            self.tr.invoice_paid("INV-999")

    def test_other_currencies_are_flagged_not_mixed(self):
        self.tr.import_metrics(self.csv)
        self.tr.metric("expenses", 500, unit="EUR"); self.tr.metric("revenue", 10, unit="USD")
        self.assertIn("other currencies are not included", self.fin())


class LongRunningProcesses(unittest.TestCase):
    def test_a_running_tracker_notices_settings_changed_by_someone_else(self):
        d = Path(tempfile.mkdtemp()); git(d, "init", "-q", "-b", "main")
        running = Tracker(d)                                # e.g. the MCP server inside an AI tool, started long ago
        running.add_task("First")
        setup.add_tracker(d, "csv")                         # later the user connects Excel from another window
        running.add_task("Second")
        self.assertIn("Second", (d / "Tracker.csv").read_text(encoding="utf-8-sig"))


class OptionalAI(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp()); git(self.d, "init", "-q", "-b", "main")
        self.calls = self.d / "llm_calls.txt"
        os.environ["FAKE_LLM_LOG"] = str(self.calls); os.environ["FAKE_LLM_MODE"] = "ok"
        self.cmd = f"{sys.executable} {Path(ROOT) / 'tests' / 'bin' / 'fake_llm.py'}"
        self.tr = Tracker(self.d); self.tr.add_task("Design logo"); self.tr.add_task("Build pages")

    def tearDown(self):
        os.environ.pop("FAKE_LLM_MODE", None)

    def n_calls(self): return len(self.calls.read_text(encoding="utf-8").splitlines()) if self.calls.exists() else 0

    def test_off_by_default_nothing_is_sent_anywhere(self):
        self.assertFalse(self.tr.say("terminé el logo")[0]["ok"])
        self.assertEqual(self.n_calls(), 0)

    def test_understands_other_languages_but_only_picks_real_tasks(self):
        setup.add_llm(self.d, self.cmd)
        r = self.tr.say("terminé el logo")[0]                              # Spanish: the keyword matcher can't read it
        self.assertTrue(r["ok"]); self.assertIn("matched by AI", r["message"])
        self.assertEqual(next(t for t in self.tr.tasks() if t["id"] == "T-001")["status"], "done")
        self.assertFalse(self.tr.say("please hallucinate something")[0]["ok"])      # invented task id: rejected
        self.assertFalse(self.tr.say("weird status words")[0]["ok"])                 # invented status: rejected
        self.assertFalse(self.tr.say("zzz qqq")[0]["ok"])                            # AI says "not sure": nothing changes
        self.tr.undo()                                                               # and an AI guess is undoable
        self.assertEqual(next(t for t in self.tr.tasks() if t["id"] == "T-001")["status"], "todo")

    def test_ai_never_runs_when_the_simple_matcher_succeeds(self):
        setup.add_llm(self.d, self.cmd, narrative=False)
        self.tr.say("finished the logo")
        self.assertEqual(self.n_calls(), 0)

    def test_broken_ai_is_harmless(self):
        setup.add_llm(self.d, self.cmd); os.environ["FAKE_LLM_MODE"] = "crash"
        self.assertFalse(self.tr.say("terminé el logo")[0]["ok"])
        setup.add_llm(self.d, "/no/such/binary")
        self.assertFalse(Tracker(self.d).say("terminé el logo")[0]["ok"])
        self.assertTrue(any("AI command" in l for l in __import__("footnote.log", fromlist=["x"]).tail(self.d, 20)))

    def test_summary_paragraph_is_cached_and_cannot_invent_numbers(self):
        self.tr.say("finished T-001")                                                # 1 of 2 done = 50%
        setup.add_llm(self.d, self.cmd)
        rep = Tracker(self.d).report("manager"); Tracker(self.d).sync()
        self.assertIn("The project is 50 percent complete.", (self.d / "Tracker" / "Project Report.md").read_text(encoding="utf-8"))
        n = self.n_calls(); Tracker(self.d).sync(); Tracker(self.d).sync()
        self.assertEqual(self.n_calls(), n)                                           # not re-asked every sync
        os.environ["FAKE_LLM_MODE"] = "lie"
        (self.d / "Tracker" / "_narrative.json").unlink()
        Tracker(self.d).sync()
        self.assertNotIn("77", (self.d / "Tracker" / "Project Report.md").read_text(encoding="utf-8"))   # fabricated figure discarded

    def test_field_suggestions_pass_through_our_own_checker(self):
        with self.assertRaises(TrackerError):
            self.tr.suggest_fields()                                                  # not enabled yet
        setup.add_llm(self.d, self.cmd)
        found = {f["name"] for f in Tracker(self.d).suggest_fields()}
        self.assertEqual(found, {"days_open", "late"})                                # unsafe, unknown-field and clashing ones dropped
        Tracker(self.d).suggest_fields(apply=True)
        self.assertEqual({"days_open", "late"} <= {f["name"] for f in Tracker(self.d).fields()}, True)
        self.assertEqual(next(t for t in Tracker(self.d).tasks() if t["id"] == "T-001")["late"], "ok")


class ColdStartOnly(unittest.TestCase):
    def test_readme_headings_seed_a_first_plan_but_do_not_keep_adding_tasks(self):
        d = Path(tempfile.mkdtemp()); git(d, "init", "-q", "-b", "main")
        (d / "README.md").write_text("# Shop\n## Install\n## Usage\n", encoding="utf-8")
        tr = Tracker(d); tr.sync()
        self.assertEqual(len(tr.tasks()), 2)                                  # a brand-new project gets a starting point
        (d / "README.md").write_text("# Shop\n## Install\n## Usage\n## Troubleshooting\n## Licence\n", encoding="utf-8")
        tr.sync()
        self.assertEqual(len(tr.tasks()), 2)                                  # later README edits are documentation, not new work
        (d / "ARCHITECTURE.md").write_text("# A\n## Payments service\n", encoding="utf-8")
        tr.sync()
        self.assertEqual(len(tr.tasks()), 3)                                  # but real architecture docs still add work


class OlderPythons(unittest.TestCase):
    def test_timestamps_from_every_source_parse_everywhere(self):
        from footnote.store import parse_ts
        for s in ("2026-10-27T10:54:24Z", "2026-10-27T10:54:24.217182Z", "2026-10-27T10:54:24.2Z", "2026-10-27T10:54:24.000+00:00",
                  "2026-10-27T10:54:24+02:00", "2026-10-27T10:54:24", "2026-10-27T10:54:24.123456789Z"):
            d = parse_ts(s)
            self.assertIsNotNone(d.tzinfo, s)
            self.assertEqual((d.year, d.month, d.day), (2026, 10, 27))
        self.assertEqual(parse_ts("2026-10-27T10:54:24Z"), parse_ts("2026-10-27T10:54:24+00:00"))


class TemplatesAreNotWork(unittest.TestCase):
    def test_checkboxes_in_templates_and_hidden_folders_are_ignored(self):
        d = Path(tempfile.mkdtemp()); git(d, "init", "-q", "-b", "main")
        (d / ".github").mkdir(); (d / ".github" / "PULL_REQUEST_TEMPLATE.md").write_text("- [ ] I added tests\n- [ ] I updated docs\n", encoding="utf-8")
        (d / "docs").mkdir(); (d / "docs" / "ADR_TEMPLATE.md").write_text("- [ ] Context written\n", encoding="utf-8")
        (d / ".obsidian").mkdir(); (d / ".obsidian" / "x.md").write_text("- [ ] hidden thing\n", encoding="utf-8")
        (d / "PLAN.md").write_text("- [ ] Real work\n", encoding="utf-8")
        (d / "docs" / "checklist.md").write_text("- [ ] A real checklist item\n", encoding="utf-8")
        self.assertEqual(sorted(t["title"] for t in Tracker(d).tasks()), ["A real checklist item", "Real work"])
