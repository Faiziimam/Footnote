import email, json, os, sys, tempfile, threading, unittest, zipfile, urllib.request, datetime as dt
from email import policy
from io import BytesIO
from pathlib import Path
from footnote import cli, config, deck, setup
from footnote.api import Tracker, TrackerError
from tests.test_project import git, commit
from tests.test_security import start_server, raw
from tests.fake_notify import FakeSMTP, FakeSlack


def shop(tmp=None):
    d = Path(tmp or tempfile.mkdtemp()) / "Mug Shop"; d.mkdir(); git(d, "init", "-q", "-b", "main")
    git(d, "config", "user.email", "maya@shop.io"); git(d, "config", "user.name", "Maya")
    tr = Tracker(d); tr.set_project("Mug Shop", "online store", "sell mugs")
    for t, e in (("Catalogue", "Shop"), ("Cart", "Shop"), ("Emails", "Ops")):
        tr.add_task(t, e)
    commit(d, "feat: catalogue (T-001)", ("Maya", "maya@shop.io"), {"package.json": '{"dependencies":{"next":"14"}}', "app/page.tsx": "x"}, days_ago=2)
    tr.say("finished T-001"); tr.metric("revenue", 120, unit="USD"); tr.metric("orders", 4); tr.record("risk", "Shipping undecided")
    return d, tr


class PowerPoint(unittest.TestCase):
    def test_deck_is_a_valid_presentation(self):
        d, tr = shop()
        data = tr.deck_bytes("manager")
        z = zipfile.ZipFile(BytesIO(data))
        self.assertIsNone(z.testzip())
        names = set(z.namelist())
        for part in ("[Content_Types].xml", "ppt/presentation.xml", "ppt/slideMasters/slideMaster1.xml", "ppt/theme/theme1.xml", "ppt/slides/slide1.xml"):
            self.assertIn(part, names)
        import xml.dom.minidom as md
        for n in names:                                                      # every part is well-formed XML
            if n.endswith((".xml", ".rels")):
                md.parseString(z.read(n))
        try:
            from pptx import Presentation
        except ImportError:
            self.skipTest("python-pptx not installed for the extra check")
        p = Presentation(BytesIO(data))
        text = " ".join(sh.text_frame.text for s in p.slides for sh in s.shapes if sh.has_text_frame)
        self.assertGreaterEqual(len(p.slides), 4)
        for needle in ("Mug Shop", "Where we are", "33%", "Shipping undecided", "Business figures"):
            self.assertIn(needle, text)
        self.assertEqual(tr.deck_bytes("manager"), data)                     # same input, same file

    def test_hostile_text_cannot_corrupt_or_inject_into_the_file(self):
        d, tr = shop()
        tr.add_task("Evil \x00\x01\x08 title ]]> <a:t>&amp; \ud800 \U0001F600 end", epic="<p:sp>x</p:sp>")
        tr.record("decision", "Use <b>bold</b> & \"quotes\" \x0b and ]]> markers")
        data = tr.deck_bytes()
        z = zipfile.ZipFile(BytesIO(data))
        import xml.dom.minidom as md
        for n in z.namelist():
            if n.endswith((".xml", ".rels")):
                md.parseString(z.read(n))                                    # still well-formed
        xml = z.read("ppt/slides/slide4.xml").decode() + z.read("ppt/slides/slide2.xml").decode()
        self.assertNotIn("\x00", xml); self.assertNotIn("<p:sp>x</p:sp>", xml)
        self.assertEqual(sum(1 for n in z.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml")), len(
            [n for n in z.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml")]))

    def test_long_reports_split_into_more_slides_instead_of_overflowing(self):
        try:
            import pptx  # noqa
        except ImportError:
            self.skipTest("python-pptx not installed for the extra check")
        d, tr = shop()
        for i in range(60):
            tr.record("decision", f"Decision number {i}: " + "we chose the longer path because of reasons " * 3)
        from pptx import Presentation
        p = Presentation(BytesIO(tr.deck_bytes("everyone")))
        for s in p.slides:
            bullets = [sh.text_frame for sh in s.shapes if sh.has_text_frame and len(sh.text_frame.paragraphs) > 3]
            for tf in bullets:
                self.assertLessEqual(len(tf.paragraphs), 12)
        self.assertGreater(len(p.slides), 6)

    def test_cli_and_web_download(self):
        d, tr = shop()
        self.assertEqual(cli.main(["--project", str(d), "deck", str(d / "review"), "--for", "everyone"]), 0)
        self.assertTrue((d / "review.pptx").exists())
        srv, token, base = start_server(d)
        self.assertEqual(raw(base, "/api/deck")[0], 401)                      # needs the token like everything else
        code, h, body = raw(base, "/api/deck?for=manager", token=token)
        self.assertEqual(code, 200); self.assertIn("presentationml", h["Content-Type"]); self.assertTrue(zipfile.is_zipfile(BytesIO(body)))
        srv.shutdown()
        srv, token, base = start_server(d, read_only=True)
        self.assertEqual(raw(base, "/api/deck", token=token)[0], 200)         # presenting is fine in read-only mode
        srv.shutdown()


class ScheduledReportEmail(unittest.TestCase):
    def setUp(self):
        self.d, self.tr = shop()
        self.smtp = FakeSMTP()
        self.slack = FakeSlack()
        setup.add_notify(self.d, email_to="boss@x.io, ceo@x.io", smtp_host="127.0.0.1", smtp_port=self.smtp.port, email_from="tracker@x.io",
                         digest="monthly", tls=False, content="report", report_for="manager", attach=["deck", "html"])
        cfg = config.load(self.d); cfg["notify"]["slack_webhook"] = self.slack.http; config.save(self.d, cfg)

    def sent(self, i=-1):
        return email.message_from_string(self.smtp.mails[i]["data"], policy=policy.default)

    def test_monthly_means_monthly_and_the_email_carries_the_report(self):
        Tracker(self.d).sync()                                                 # baseline: nothing sent yet
        self.assertEqual(self.smtp.mails, [])
        self._age_digest(20)
        Tracker(self.d).sync(); self.assertEqual(self.smtp.mails, [])        # 20 days is not a month
        self._age_digest(31)
        Tracker(self.d).sync()
        self.assertEqual(len(self.smtp.mails), 1)
        m = self.sent()
        self.assertEqual(m["Subject"], "Mug Shop: project report"); self.assertIn("boss@x.io", m["To"]); self.assertIn("ceo@x.io", m["To"])
        plain = m.get_body(("plain",)).get_content(); html = m.get_body(("html",)).get_content()
        self.assertIn("At a glance", plain); self.assertIn("<h2>", html); self.assertIn("Shipping undecided", html)
        files = {a.get_filename(): a.get_content_type() for a in m.iter_attachments()}
        self.assertEqual(sorted(files), ["Mug_Shop-report.html", "Mug_Shop-review.pptx"])
        self.assertIn("presentationml", files["Mug_Shop-review.pptx"])
        pptx = [a for a in m.iter_attachments() if a.get_filename().endswith(".pptx")][0].get_content()
        self.assertTrue(zipfile.is_zipfile(BytesIO(pptx)))                      # the attachment is a real, openable deck
        self.assertTrue(self.slack.posts and len(self.slack.posts[-1]) < 3800)  # Slack gets a readable, trimmed version
        Tracker(self.d).sync(); self.assertEqual(len(self.smtp.mails), 1)       # and not again until next month

    def _age_digest(self, days):
        p = self.d / ".footnote" / "notified.json"
        st = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"alerts": {}}
        st["digest"] = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).isoformat()
        p.write_text(json.dumps(st), encoding="utf-8")

    def test_send_now_from_the_command_line(self):
        self.assertEqual(cli.main(["--project", str(self.d), "report", "--for", "developer", "--email", "--attach", "deck"]), 0)
        m = self.sent()
        self.assertEqual([a.get_filename() for a in m.iter_attachments()], ["Mug_Shop-review.pptx"])
        self.assertIn("Technical overview", m.get_body(("plain",)).get_content())
        self.assertEqual(self.slack.posts, [])                                 # --email means email only

    def test_setup_is_validated_in_plain_language(self):
        for bad in (dict(digest="hourly"), dict(content="everything"), dict(attach=["zip"]), dict(report_for="alien")):
            with self.assertRaises(TrackerError):
                setup.add_notify(self.d, email_to="a@b.c", smtp_host="h", **bad)
        d2, tr2 = shop()
        with self.assertRaises(TrackerError) as c:
            tr2.mail_report()
        self.assertIn("add-notify", str(c.exception))
        setup.add_notify(d2, email_to="a@b.c", smtp_host="127.0.0.1", smtp_port=1, tls=False)
        with self.assertRaises(TrackerError):
            Tracker(d2).mail_report()                                            # server down: a clear error, no crash
