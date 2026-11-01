import csv, io, json, os, sqlite3, subprocess, sys, tempfile, textwrap, threading, unittest, urllib.request, urllib.error
from pathlib import Path
from footnote import engine, config, setup, connect, mcp_server, server
from footnote.api import Tracker, TrackerError
from footnote.store import Store
from tests.fakes import FakeNotion, FakeSheets, FakeAppsScript


def sh(cwd, *c):
    subprocess.run(c, cwd=cwd, check=True, capture_output=True)


class Base(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        sh(self.d, "git", "init", "-q", "-b", "main")
        sh(self.d, "git", "config", "user.email", "t@t"); sh(self.d, "git", "config", "user.name", "t")
        (self.d / "PLAN.md").write_text("# Plan\n- [ ] Design logo\n- [ ] Build landing page\n- [ ] Launch campaign\n", encoding="utf-8")
        sh(self.d, "git", "add", "-A"); sh(self.d, "git", "commit", "-qm", "init")

    def tr(self):
        return Tracker(self.d)

    def st(self):
        return {f["title"]: f["status"] for f, _ in Store(self.d / "Tracker").load_tasks().values()}


class Mirrors(Base):
    def test_csv_two_way(self):
        setup.add_tracker(self.d, "csv")
        self.tr().sync()
        rows = list(csv.DictReader(open(self.d / "Tracker.csv", encoding="utf-8-sig")))
        self.assertEqual(rows[0]["status"], "Not started")
        rows[0]["status"] = "done"                      # a human edits the spreadsheet
        rows.append({"title": "Hire designer", "status": "In progress"})   # ...and types a new row
        with open(self.d / "Tracker.csv", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) ); w.writeheader()
            for r in rows: w.writerow({k: r.get(k, "") for k in rows[0]})
        self.tr().sync()
        self.assertEqual(self.st()["Design logo"], "done")
        self.assertEqual(self.st()["Hire designer"], "active")
        self.assertEqual(self.tr().sync().changed, 0)   # settled
        back = list(csv.DictReader(open(self.d / "Tracker.csv", encoding="utf-8-sig")))
        self.assertTrue(any(r["title"] == "Hire designer" and r["id"] for r in back))  # id assigned

    def test_backwards_edit_locks_against_automation(self):
        setup.add_tracker(self.d, "csv"); self.tr().sync()
        self.tr().set_status("T-001", "done")
        self.tr().set_status("T-001", "In progress")    # moved back by a human
        sh(self.d, "git", "commit", "-q", "--allow-empty", "-m", "Closes T-001"); self.tr().sync()
        self.assertEqual(self.st()["Design logo"], "active")

    def test_sqlite_edge_table(self):
        (self.d / "PLAN.md").write_text("# Plan\n- [ ] Design logo\n- [ ] Print flyers depends on \"Design logo\"\n", encoding="utf-8")
        setup.add_tracker(self.d, "sqlite"); self.tr().sync()
        con = sqlite3.connect(self.d / "tracker.db")
        self.assertEqual(con.execute("select src,type,dst from relations").fetchall(), [("T-002", "depends_on", "T-001")])
        self.assertEqual(con.execute("select title from ready_tasks").fetchall(), [("Design logo",)])
        con.execute("update tasks set status='Done' where id='T-001'"); con.commit(); con.close()
        self.tr().sync()
        self.assertEqual(self.st()["Design logo"], "done")
        con = sqlite3.connect(self.d / "tracker.db")
        self.assertEqual(len(con.execute("select title from ready_tasks").fetchall()), 1)  # flyers now ready

    def test_notion_two_way(self):
        n = FakeNotion()
        setup.add_tracker(self.d, "notion", token="good-token", parent_page="https://notion.so/Home-" + "a" * 32,
                          base_url=n.url)
        r = self.tr().sync()
        self.assertEqual(r.warnings, [])
        self.assertEqual(len(n.pages), 3)
        self.assertEqual(n.page_by_id("T-001")["properties"]["Status"]["select"]["name"], "Not started")
        n.human_set_status("T-001", "In progress"); n.human_add_row("Write press release")
        self.tr().sync()
        self.assertEqual(self.st()["Design logo"], "active")
        self.assertEqual(self.st()["Write press release"], "todo")
        self.assertEqual(len(n.pages), 4)                        # no duplicate created for the typed row
        before = n.count("POST", "/v1/pages") + n.count("PATCH", "/v1/pages")
        self.tr().sync()
        self.assertEqual(n.count("POST", "/v1/pages") + n.count("PATCH", "/v1/pages"), before)  # nothing to push
        # automation changes flow out
        sh(self.d, "git", "commit", "-q", "--allow-empty", "-m", "Closes T-002"); self.tr().sync()
        self.assertEqual(n.page_by_id("T-002")["properties"]["Status"]["select"]["name"], "Done")

    def test_notion_bad_token_is_a_friendly_warning_not_a_crash(self):
        n = FakeNotion()
        setup.add_tracker(self.d, "notion", token="WRONG", parent_page="a" * 32, base_url=n.url)
        r = self.tr().sync()
        self.assertTrue(any("token is wrong" in w for w in r.warnings))
        self.assertEqual(self.st()["Design logo"], "todo")      # local tracker still works

    def test_google_sheets_api_and_webapp(self):
        s = FakeSheets()
        setup.add_tracker(self.d, "gsheets", token="sheet-token", base_url=s.url, spreadsheet_id="")
        self.tr().sync()
        self.assertEqual(s.created, 1)
        self.assertEqual(s.values[0][:3], ["id", "title", "status"])
        s.human_edit("T-003", "status", "Blocked")
        self.tr().sync()
        self.assertEqual(self.st()["Launch campaign"], "blocked")
        self.assertEqual(s.created, 1)                           # reused, not recreated
        # apps script mode
        d2 = Path(tempfile.mkdtemp()); (d2 / "PLAN.md").write_text("- [ ] One\n- [ ] Two\n", encoding="utf-8")
        a = FakeAppsScript()
        setup.add_tracker(d2, "gsheets", webapp_url=a.url, secret="pw")
        self.assertEqual(Tracker(d2).sync().warnings, [])
        self.assertEqual(len(a.values), 3)
        setup.add_tracker(d2, "gsheets", webapp_url=a.url, secret="nope")
        self.assertTrue(Tracker(d2).sync().warnings)

    def test_mirror_down_does_not_lose_data(self):
        n = FakeNotion()
        setup.add_tracker(self.d, "notion", token="good-token", parent_page="a" * 32, base_url=n.url)
        self.tr().sync()
        n.srv.shutdown(); n.srv.server_close()
        r = self.tr().sync()
        self.assertTrue(r.warnings)
        self.assertEqual(len(self.st()), 3)

    def test_all_five_at_once(self):
        n, s = FakeNotion(), FakeSheets()
        setup.add_tracker(self.d, "obsidian")
        setup.add_tracker(self.d, "csv"); setup.add_tracker(self.d, "sqlite")
        setup.add_tracker(self.d, "notion", token="good-token", parent_page="b" * 32, base_url=n.url)
        setup.add_tracker(self.d, "gsheets", token="sheet-token", base_url=s.url)
        r = self.tr().sync()
        self.assertEqual(r.warnings, [])
        self.assertEqual(len(r.mirrors), 4)
        self.tr().say("finished the logo")
        self.assertEqual(n.page_by_id("T-001")["properties"]["Status"]["select"]["name"], "Done")
        self.assertEqual(s.values[1][2], "Done")
        self.assertEqual(sqlite3.connect(self.d / "tracker.db").execute("select status from tasks where id='T-001'").fetchone()[0], "Done")
        self.assertIn("Done", (self.d / "Tracker.csv").read_text(encoding="utf-8"))


class Plain(Base):
    def test_say(self):
        self.tr().sync()
        res = self.tr().say("I finished the logo and started on the landing page")
        self.assertTrue(all(r["ok"] for r in res), res)
        self.assertEqual(self.st()["Design logo"], "done")
        self.assertEqual(self.st()["Build landing page"], "active")

    def test_say_never_guesses(self):
        self.tr().sync()
        res = self.tr().say("finished the thing")
        self.assertFalse(res[0]["ok"])
        self.assertEqual(set(self.st().values()), {"todo"})
        res = self.tr().say("add task: order business cards, then I'm blocked on launch campaign")
        self.assertTrue(res[0]["ok"] and "Added" in res[0]["message"])
        self.assertEqual(self.st()["Launch campaign"], "blocked")

    def test_gap_title_refs_and_rollup(self):
        (self.d / "PLAN.md").write_text(textwrap.dedent("""\
            # Plan
            - [ ] Website
              - [ ] Design logo
              - [ ] Build pages (after: "Design logo")
            - [ ] Print flyers depends on [[Design logo]]
            """), encoding="utf-8")
        self.tr().sync()
        t = {f["title"]: f for f, _ in Store(self.d / "Tracker").load_tasks().values()}
        logo = t["Design logo"]["id"]
        self.assertIn(f"depends_on:{logo}", t["Build pages"]["relations"])
        self.assertIn(f"depends_on:{logo}", t["Print flyers"]["relations"])
        self.tr().say(f"started {logo}")
        self.assertEqual(self.st()["Website"], "active")             # parent follows child
        self.tr().say("finished design logo and finished build pages")
        self.assertEqual(self.st()["Website"], "done")               # all subtasks done
        self.assertEqual(self.tr().sync().changed, 0)

    def test_inbox_and_hooks_free_agents(self):
        self.tr().sync()
        p = self.d / ".footnote"; p.mkdir(exist_ok=True)
        (p / "inbox.jsonl").write_text('{"text": "finished the logo"}\n{"add": "Book photographer"}\nnot json\n', encoding="utf-8")
        self.tr().sync()
        self.assertEqual(self.st()["Design logo"], "done")
        self.assertIn("Book photographer", self.st())
        self.assertEqual((p / "inbox.jsonl").read_text(encoding="utf-8"), "")

    def test_works_without_git_or_docs(self):
        d = Path(tempfile.mkdtemp())
        t = Tracker(d)
        t.add_task("Plan the offsite")
        t.say("started the offsite")
        self.assertEqual(t.tasks()[0]["status"], "active")


class Agents(Base):
    def test_mcp_roundtrip(self):
        self.tr().sync()
        inp = "\n".join(json.dumps(m) for m in [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "tracker_update", "arguments": {"text": "finished the logo"}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "tracker_set_status", "arguments": {"id": "T-099", "status": "Done"}}},
            {"jsonrpc": "2.0", "id": 5, "method": "nope"}]) + "\n"
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parent.parent))
        out = subprocess.run([sys.executable, "-m", "footnote", "--project", str(self.d), "mcp"],
                             input=inp, capture_output=True, text=True, env=env, encoding="utf-8", errors="replace").stdout.splitlines()
        res = {json.loads(l)["id"]: json.loads(l) for l in out}
        self.assertEqual(len(res), 5)                                # the notification gets no reply
        self.assertEqual(len(res[2]["result"]["tools"]), len(mcp_server.TOOLS))
        self.assertIn("Not started → Done", res[3]["result"]["content"][0]["text"])
        self.assertTrue(res[4]["result"]["isError"])                 # friendly error, no crash
        self.assertIn("no task T-099", res[4]["result"]["content"][0]["text"])
        self.assertEqual(res[5]["error"]["code"], -32601)
        self.assertEqual(self.st()["Design logo"], "done")

    def test_connect_every_tool(self):
        for tool in connect.TOOLS:
            wrote, notes = connect.connect(tool, self.d)
            self.assertTrue(wrote)
        connect.connect("claude", self.d)                           # idempotent
        mcp = json.loads((self.d / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["footnote"]
        self.assertIn("mcp", mcp["args"])
        self.assertEqual((self.d / "CLAUDE.md").read_text(encoding="utf-8").count("Project tracker"), 1)
        self.assertIn("servers", json.loads((self.d / ".vscode" / "mcp.json").read_text(encoding="utf-8")))

    def test_http_api_and_security(self):
        self.tr().sync()
        token = config.server_token(self.d)
        srv = server.ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(self.d, token))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_address[1]}"

        def req(path, body=None, tok=token, host=None):
            r = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                       headers={**({"Authorization": f"Bearer {tok}"} if tok else {}),
                                                **({"Host": host} if host else {})})
            return json.loads(urllib.request.urlopen(r).read())
        with self.assertRaises(urllib.error.HTTPError) as c:
            req("/api/tasks", tok=None)
        self.assertEqual(c.exception.code, 401)
        with self.assertRaises(urllib.error.HTTPError) as c:
            req("/api/tasks", host="evil.example.com")
        self.assertEqual(c.exception.code, 403)
        self.assertEqual(len(req("/api/tasks")["tasks"]), 3)
        req("/api/event", {"text": "finished the logo", "source": "zapier"})
        req("/api/status", {"id": "T-002", "status": "In progress"})
        self.assertEqual(self.st()["Design logo"], "done")
        self.assertEqual(self.st()["Build landing page"], "active")
        html = urllib.request.urlopen(base + "/").read().decode()
        self.assertIn(token, html); self.assertNotIn("__TOKEN__", html)
        srv.shutdown()


if __name__ == "__main__":
    unittest.main()
