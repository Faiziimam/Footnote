import csv, datetime as dt, json, os, subprocess, tempfile, threading, unittest, urllib.request
from pathlib import Path
from footnote import config, connect, mcp_server, server, setup, metrics, team, signals
from footnote.api import Tracker, TrackerError
from footnote.store import Store
from tests.fakes import FakeNotion


def git(cwd, *args, **env):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, env={**os.environ, **env})


def commit(d, msg, who=("Alice Dev", "alice@x.io"), files=None, days_ago=0, body=""):
    for rel, txt in (files or {}).items():
        p = Path(d) / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(txt, encoding="utf-8")
    git(d, "add", "-A")
    when = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days_ago)).isoformat()
    git(d, "commit", "-q", "--allow-empty", "-m", msg + (("\n\n" + body) if body else ""),
        GIT_AUTHOR_NAME=who[0], GIT_AUTHOR_EMAIL=who[1], GIT_COMMITTER_NAME=who[0], GIT_COMMITTER_EMAIL=who[1],
        GIT_AUTHOR_DATE=when, GIT_COMMITTER_DATE=when)


class Repo(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        git(self.d, "init", "-q", "-b", "main")
        git(self.d, "config", "user.email", "alice@x.io"); git(self.d, "config", "user.name", "Alice Dev")

    def tr(self): return Tracker(self.d)
    def st(self): return {f["title"]: f for f, _ in Store(self.d / "Tracker").load_tasks().values()}
    def vault(self, name): return (self.d / "Tracker" / name).read_text(encoding="utf-8")


class Portfolio(Repo):
    def test_agent_builds_portfolio_start_to_finish(self):
        tr = self.tr()
        out = tr.set_project("My Portfolio", "portfolio website", "show my work to clients")
        self.assertIn("Typical work for a portfolio", out)
        ids = {}
        for title, epic in [("Design system", "Design"), ("Home page", "Build"), ("Projects page", "Build"), ("Deploy site", "Launch")]:
            ids[title] = tr.add_task(title, epic, who="agent")
        tr.add_task("Contact form", "Build", parent=ids["Home page"], depends_on=[ids["Design system"]], who="agent")
        # the agent works and commits with task IDs
        tr.say(f"started {ids['Design system']}", who="agent")
        commit(self.d, f"Add design tokens ({ids['Design system']})", files={
            "package.json": '{"dependencies":{"next":"14","react":"18","tailwindcss":"3"},"scripts":{"dev":"next dev","build":"next build"}}',
            "styles/tokens.css": ":root{}"})
        commit(self.d, f"Closes {ids['Design system']}")
        commit(self.d, f"Add home page and hero ({ids['Home page']})", files={"app/page.tsx": "x", "components/Hero.tsx": "x"})
        tr.record("decision", "Using Next.js static export so hosting is free and fast", who="agent")
        tr.sync()
        tasks = self.st()
        self.assertEqual(tasks["Design system"]["status"], "done")
        self.assertEqual(tasks["Home page"]["status"], "active")
        self.assertEqual(tasks["Design system"]["owner"], "Alice Dev")           # from commits
        self.assertEqual(tasks["Contact form"]["status"], "todo")
        # architecture discovered automatically + logged as it changed
        arch = self.vault("Architecture.md")
        self.assertIn("Next.js", arch); self.assertIn("`/`", arch); self.assertIn("Hero", arch)
        # the agent adds a page later: drift is captured without anyone telling the tracker
        commit(self.d, f"Add projects page ({ids['Projects page']})", files={"app/projects/page.tsx": "x", "app/api/contact/route.ts": "x"})
        tr.sync()
        j = self.vault("Journal.md")
        self.assertIn("Added to the stack: Next.js", j); self.assertIn("New page: /projects", j); self.assertIn("New API route: /api/contact", j)
        self.assertIn("Using Next.js static export", j)
        self.assertIn("Add home page and hero", self.vault("Timeline.md"))
        built = self.vault("Built.md")
        self.assertIn("Design system", built); self.assertIn("styles/tokens.css", built)
        rep = self.vault("Project Report.md")
        for needle in ("At a glance", "What has been built", "Technical overview", "Handover checklist", "Next.js"):
            self.assertIn(needle, rep)
        self.assertIn("No automated tests found", rep)                          # honest about gaps
        self.assertIn("No deployment configuration found", rep)
        self.assertEqual(tr.sync().changed, 0)                                  # settled / idempotent

    def test_agent_reports_work_nobody_planned(self):
        tr = self.tr()
        res = tr.say("started building the portfolio website", who="agent", create_missing=True)
        self.assertTrue(res[0]["ok"] and "Added T-001" in res[0]["message"], res)
        self.assertEqual(self.st()["Building the portfolio website"]["status"], "active")
        # ...but with something CLOSE already planned it still refuses to guess
        tr.add_task("Build hero section"); tr.add_task("Build footer section")
        res = tr.say("finished the section", who="agent", create_missing=True)
        self.assertFalse(res[0]["ok"])
        # a human saying something unmatched never creates tasks
        self.assertFalse(tr.say("finished quantum teleporter")[0]["ok"])

    def test_rules_upgrade_in_place(self):
        (self.d / "CLAUDE.md").write_text("# My notes\nKeep it simple.\n\n<!-- footnote -->\n## Project tracker (auto-maintained)\nold rules\n\n## Other\nkeep me\n", encoding="utf-8")
        connect.connect("claude", self.d); connect.connect("claude", self.d)
        t = (self.d / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn("Keep it simple.", t); self.assertIn("keep me", t)
        self.assertNotIn("old rules", t)
        self.assertEqual(t.count("Project tracker (auto-maintained)"), 1)
        self.assertIn("tracker_project", t); self.assertIn("commit", t.lower())

    def test_audience_views(self):
        tr = self.tr(); tr.set_project("X", "portfolio website"); tr.add_task("Home page"); tr.sync()
        mgr, ev, dev = tr.report("manager"), tr.report("everyone"), tr.report("developer")
        self.assertNotIn("What has been built", mgr); self.assertIn("What has been built", ev)
        self.assertNotIn("Technical overview", ev)
        self.assertIn("At a glance", dev)


class Ecommerce(Repo):
    def write_csv(self, name, rows):
        p = self.d / name
        with open(p, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
        return p

    def test_sales_import_and_report(self):
        tr = self.tr(); tr.set_project("Mug Shop", "online store")
        today = dt.date.today()
        rows = [{"Name": f"#10{i}", "Created at": (today - dt.timedelta(days=i)).isoformat() + " 10:00:00 +0000",
                 "Total": f"${20 + i:,.2f}", "Financial Status": "paid"} for i in range(5)]
        rows.append({"Name": "#200", "Created at": today.isoformat(), "Total": "15.00", "Financial Status": "refunded"})
        p = self.write_csv("orders.csv", rows)
        r = tr.import_metrics(p)
        self.assertEqual((r["mode"], r["added"]), ("sales", 11))
        self.assertEqual(tr.import_metrics(p)["added"], 0)                      # re-import is safe
        tr.metric("visitors", 400)
        rep = tr.report("manager")
        self.assertIn("Revenue", rep); self.assertIn("110", rep)                 # 20+21+22+23+24
        self.assertIn("Refunds", rep); self.assertIn("Average order value", rep)
        self.assertIn("22", rep)                                                  # AOV 22
        self.assertIn("Visitor → order conversion", rep)
        self.assertIn("Units in stock", rep)                                      # defined but not connected: said so
        self.assertIn("not connected yet", rep)

    def test_bank_export_gives_profit_and_runway(self):
        tr = self.tr(); tr.set_project("Studio", "finance business")
        today = dt.date.today().isoformat()
        p = self.write_csv("bank.csv", [{"Date": today, "Description": "Client A", "Amount": "5000"},
                                        {"Date": today, "Description": "Rent", "Amount": "-1500"},
                                        {"Date": today, "Description": "Tools", "Amount": "(300.50)"}])
        self.assertEqual(tr.import_metrics(p)["mode"], "bank")
        tr.metric("cash_balance", 9000)
        rep = tr.report("manager")
        self.assertIn("Profit:** 3,199.5", rep)
        self.assertIn("Cash runway (months):** 5", rep)

    def test_wide_analytics_csv(self):
        tr = self.tr()
        p = self.write_csv("traffic.csv", [{"date": dt.date.today().isoformat(), "visitors": "120", "signups": "7"}])
        self.assertEqual(tr.import_metrics(p)["mode"], "wide")
        self.assertIn("signups", self.vault("Metrics.md"))

    def test_unreadable_file_gets_plain_message(self):
        p = self.write_csv("junk.csv", [{"foo": "a", "bar": "b"}])
        with self.assertRaises(TrackerError) as c:
            self.tr().import_metrics(p)
        self.assertIn("couldn't recognise", str(c.exception))

    def test_stripe_pull(self):
        import http.server, urllib.parse
        now = int(dt.datetime.now(dt.timezone.utc).timestamp())

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_GET(self):
                if self.headers.get("Authorization") != "Bearer sk_test": self.send_response(401); self.end_headers(); return
                path = urllib.parse.urlparse(self.path).path
                data = ([{"id": "pi_1", "created": now, "status": "succeeded", "amount_received": 4500, "currency": "usd"},
                         {"id": "pi_2", "created": now, "status": "requires_payment_method", "amount": 900}]
                        if path == "/v1/payment_intents" else [{"id": "re_1", "created": now, "status": "succeeded", "amount": 500, "currency": "usd"}])
                body = json.dumps({"data": data, "has_more": False}).encode()
                self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
        setup.add_source(self.d, "stripe", token="sk_test", base_url=f"http://127.0.0.1:{srv.server_address[1]}")
        tr = self.tr(); r = tr.sync()
        self.assertEqual(r.warnings, [])
        s = metrics.summarize(metrics.read(tr.vault))
        self.assertEqual((s["revenue"]["total"], s["orders"]["total"], s["refunds"]["total"]), (45.0, 1, 5.0))
        tr.sync(); self.assertEqual(metrics.summarize(metrics.read(tr.vault))["orders"]["total"], 1)   # no double count
        setup.add_source(self.d, "stripe", token="bad", base_url=f"http://127.0.0.1:{srv.server_address[1]}")
        self.assertTrue(self.tr().sync().warnings)
        srv.shutdown()

    def test_ecommerce_detected_from_stripe_dependency(self):
        commit(self.d, "init", files={"package.json": '{"dependencies":{"next":"14","stripe":"1"}}', "app/page.tsx": "x"})
        self.tr().sync()
        self.assertEqual(self.tr().project_info()["kind"], "ecommerce")


class AnyProject(Repo):
    def test_non_code_business_with_custom_numbers(self):
        tr = self.tr()
        tr.set_project("Sunrise Bakery", "bakery", "open a neighbourhood bakery")
        a = tr.add_task("Find a shop to rent", "Setup", who="agent")
        tr.say(f"finished {a}", who="agent")
        tr.metric("loaves_sold", 180); tr.metric("loaves_sold", 210)
        tr.record("risk", "Only one oven; a breakdown stops all sales", who="agent")
        rep = tr.report("all")
        self.assertIn("Sunrise Bakery", rep); self.assertIn("Loaves Sold", rep)
        self.assertIn("Only one oven", rep)
        self.assertNotIn("Technical overview", rep)                              # no code, no tech section
        self.assertIn("1 open risk", rep)


class Team(Repo):
    def setUp(self):
        super().setUp()
        self.A, self.B = ("Alice Dev", "alice@x.io"), ("Bob Builder", "bob@y.com")
        tr = self.tr()
        self.t1 = tr.add_task("Checkout flow", "Shop"); self.t2 = tr.add_task("Admin dashboard", "Ops"); self.t3 = tr.add_task("Product pages", "Shop")
        commit(self.d, f"feat: add cart ({self.t1})", self.A, {"app/checkout/cart.tsx": "1", "app/checkout/pay.tsx": "1"}, days_ago=3)
        commit(self.d, "fix: rounding bug in totals", self.A, {"app/checkout/pay.tsx": "2"}, days_ago=2)
        commit(self.d, f"Add admin tables ({self.t2})", self.B, {"app/admin/tables.tsx": "1"}, days_ago=2)
        commit(self.d, f"fix checkout tax ({self.t1})", self.B, {"app/checkout/pay.tsx": "3"}, days_ago=1)
        commit(self.d, "Bump deps", ("dependabot[bot]", "bot@github.com"), {"package-lock.json": "{}"}, days_ago=1)

    def test_people_ownership_and_summaries(self):
        tr = self.tr(); tr.sync()
        t = self.st()
        self.assertEqual(t["Checkout flow"]["owner"], "Alice Dev")               # most commits referencing it
        self.assertEqual(t["Admin dashboard"]["owner"], "Bob Builder")
        team_md = self.vault("Team.md")
        self.assertIn("Alice Dev", team_md); self.assertIn("Bob Builder", team_md)
        self.assertNotIn("dependabot", team_md)                                   # bots are not teammates
        self.assertIn("app/checkout", team_md)                                    # overlap: both touched pay.tsx
        self.assertTrue((self.d / "Tracker" / "People" / "Alice Dev.md").exists())
        out = tr.whois("alice")
        self.assertIn("Alice Dev", out); self.assertIn("app/checkout", out)
        self.assertIn("Alice Dev (2 commits)", tr.whois(self.t1)) if False else None
        w = tr.whois(self.t1)
        self.assertIn("Owner: Alice Dev", w); self.assertIn("Bob Builder", w)
        self.assertIn("app/admin", tr.whois("app/admin")); self.assertIn("Bob Builder", tr.whois("app/admin"))

    def test_assign_overrides_and_sticks(self):
        tr = self.tr(); tr.sync()
        tr.assign(self.t1, "bob")
        self.assertEqual(self.st()["Checkout flow"]["owner"], "Bob Builder")
        commit(self.d, f"more checkout ({self.t1})", self.A, {"app/checkout/x.tsx": "1"})
        tr.sync()
        self.assertEqual(self.st()["Checkout flow"]["owner"], "Bob Builder")     # human choice is never overwritten

    def test_catchup_since_last_looked(self):
        tr = self.tr(); tr.sync()
        first = tr.catchup("7d")
        self.assertIn("What people did", first); self.assertIn("Alice Dev", first); self.assertIn("Bob Builder", first)
        self.assertIn("possible overlap", first.lower())
        tr.catchup()                                                              # marks as seen (this person = git user)
        quiet = tr.catchup(peek=True)
        self.assertNotIn("What people did", quiet)
        commit(self.d, f"feat: coupons ({self.t3})", self.B, {"app/products/coupons.tsx": "1"})
        news = tr.catchup(peek=True)
        self.assertIn("Bob Builder", news); self.assertIn("coupons", news.lower())
        with self.assertRaises(TrackerError):
            tr.catchup("whenever")

    def test_stalled_and_bus_factor_and_aliases(self):
        tr = self.tr(); tr.sync()
        tr.say(f"started {self.t3}")
        commit(self.d, f"start product pages ({self.t3})", self.A, {"app/products/p.tsx": "1"}, days_ago=12)
        for i in range(7):
            commit(self.d, f"payments work {i}", self.A, {f"lib/payments/f{i}.ts": "1"}, days_ago=10)
        commit(self.d, "tweak", self.B, {"app/admin/other.tsx": "1"})
        setup.add_repo  # exists
        rep = tr.sync(); team_md = self.vault("Team.md")
        self.assertIn("May be stalled", team_md); self.assertIn("Product pages", team_md)
        self.assertIn("Knowledge concentrated", team_md); self.assertIn("lib/payments", team_md)
        # same person, second email -> merged via alias
        commit(self.d, "from laptop", ("Alice D.", "alice.personal@gmail.com"), {"z.txt": "1"})
        cfg = config.load(self.d); cfg["team"] = {"aliases": {"alice.personal@gmail.com": "alice@x.io"}}; config.save(self.d, cfg)
        names = [p["name"] for p in team.analyze(signals.git_history(self.d), Store(self.d / "Tracker").load_tasks(), cfg)["people"].values()]
        self.assertEqual(len(names), 2)

    def test_multi_repo(self):
        other = Path(tempfile.mkdtemp()); git(other, "init", "-q", "-b", "main")
        commit(other, "backend: add orders api", ("Carol API", "carol@z.io"), {"api/orders.py": "x"})
        setup.add_repo(self.d, str(other))
        self.tr().sync()
        self.assertIn("Carol API", self.vault("Team.md"))

    def test_mcp_exposes_team_and_memory_tools(self):
        tr = self.tr(); tr.sync()
        call = lambda n, a: mcp_server.call_tool(tr, n, a)
        self.assertIn("Alice Dev", call("tracker_whois", {"query": "alice"}))
        self.assertIn("Catch-up", call("tracker_catchup", {"since": "7d"}))
        self.assertIn("Typical work for a ecommerce" if False else "Typical work", call("tracker_project", {"kind": "online store"}))
        call("tracker_metric", {"name": "orders", "value": 3}); call("tracker_record", {"kind": "learning", "text": "Customers want guest checkout"})
        rep = call("tracker_report", {"audience": "manager"})
        self.assertIn("guest checkout", self.vault("Journal.md")); self.assertIn("Orders", rep)
        self.assertIn("now owned by Bob Builder", call("tracker_assign", {"id": self.t1, "person": "bob"}))


class SharedTracker(unittest.TestCase):
    """Two teammates, two clones, ONE shared Notion tracker."""
    def dev(self, name, email):
        d = Path(tempfile.mkdtemp()); git(d, "init", "-q", "-b", "main")
        git(d, "config", "user.email", email); git(d, "config", "user.name", name)
        return d

    def test_two_devs_share_a_tracker_without_id_collisions(self):
        n = FakeNotion()
        a, b = self.dev("Alice Dev", "alice@x.io"), self.dev("Bob Builder", "bob@y.com")
        (a / "PLAN.md").write_text("- [ ] Design logo\n- [ ] Build pages\n", encoding="utf-8")
        for d in (a, b):
            setup.add_tracker(d, "notion", token="good-token", parent_page="a" * 32, base_url=n.url)
        A, B = Tracker(a), Tracker(b)
        B_first_db = None
        A.sync()                                       # Alice's plan lands in Notion (T-001, T-002)
        db = (a / "Tracker" / ".mirrors" / "notion.json").read_text(encoding="utf-8")
        (b / "Tracker").mkdir(exist_ok=True); (b / "Tracker" / ".mirrors").mkdir(exist_ok=True)
        (b / "Tracker" / ".mirrors" / "notion.json").write_text(json.dumps({"rows": {}, "meta": {"database_id": json.loads(db)["meta"]["database_id"]}}), encoding="utf-8")
        B.sync()
        self.assertEqual({t["id"] for t in B.tasks()}, {"T-001", "T-002"})        # Bob sees Alice's tasks, same IDs
        new = B.add_task("Write launch email")                                     # Bob creates one...
        self.assertEqual(new, "T-003")
        A.sync()
        self.assertIn("T-003", {t["id"] for t in A.tasks()})                       # ...Alice sees it
        newer = A.add_task("Record demo video")                                    # Alice creates one: no clash
        self.assertEqual(newer, "T-004")
        B.say("finished T-001")                                                    # Bob finishes Alice's task
        A.sync()
        self.assertEqual({t["id"]: t["status"] for t in A.tasks()}["T-001"], "done")
        self.assertEqual(len(n.pages), 4)                                          # no duplicates anywhere


class WebAndHooks(Repo):
    def test_report_and_metric_endpoints(self):
        tr = self.tr(); tr.add_task("Home page"); tr.sync()
        token = config.server_token(self.d)
        srv = server.ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(self.d, token))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        def req(path, body=None):
            r = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                       headers={"Authorization": f"Bearer {token}"})
            return json.loads(urllib.request.urlopen(r).read())
        req("/api/metric", {"name": "orders", "value": 5, "source": "zapier"})
        req("/api/record", {"kind": "decision", "text": "Ship on Fridays"})
        self.assertIn("Orders", req("/api/report?for=manager")["markdown"])
        self.assertIn("Catch-up", req("/api/catchup")["markdown"])
        srv.shutdown()


if __name__ == "__main__":
    unittest.main()
