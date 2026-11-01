import json, re, threading, datetime as dt
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeGitHub:
    def __init__(self):
        now = dt.datetime.now(dt.timezone.utc)
        iso = lambda days: (now - dt.timedelta(days=days)).isoformat().replace("+00:00", "Z")
        self.prs = [
            {"number": 12, "title": "Add cart (T-002)", "body": "Closes T-002", "state": "closed", "merged_at": iso(1), "draft": False,
             "user": {"login": "bobby"}, "created_at": iso(4), "updated_at": iso(1), "head": {"ref": "feat/cart"}, "html_url": "u12", "requested_reviewers": []},
            {"number": 13, "title": "Stripe checkout", "body": "Work on T-003", "state": "open", "merged_at": None, "draft": False,
             "user": {"login": "bobby"}, "created_at": iso(5), "updated_at": iso(2), "head": {"ref": "feat/T-003-stripe"}, "html_url": "u13",
             "requested_reviewers": [{"login": "alice"}]},
            {"number": 14, "title": "Docs tweak", "body": "", "state": "open", "merged_at": None, "draft": False,
             "user": {"login": "alice"}, "created_at": iso(3), "updated_at": iso(3), "head": {"ref": "docs"}, "html_url": "u14", "requested_reviewers": []},
            {"number": 1, "title": "Ancient", "body": "", "state": "closed", "merged_at": None, "draft": False, "user": {"login": "x"},
             "created_at": iso(400), "updated_at": iso(399), "head": {"ref": "old"}, "html_url": "u1", "requested_reviewers": []}]
        self.reviews = {12: [{"user": {"login": "alice"}, "state": "APPROVED", "submitted_at": iso(2)}],
                        13: [{"user": {"login": "alice"}, "state": "CHANGES_REQUESTED", "submitted_at": iso(1)}], 14: []}
        self.checks = [{"name": "test", "status": "completed", "conclusion": "failure"}, {"name": "lint", "status": "completed", "conclusion": "success"}]
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_GET(self):
                if self.headers.get("Authorization") != "Bearer ghtok":
                    self.send_response(401); self.end_headers(); return
                p = self.path.split("?")[0]
                if p == "/repos/o/r/pulls": res = outer.prs
                elif m := re.match(r"^/repos/o/r/pulls/(\d+)/reviews$", p): res = outer.reviews.get(int(m.group(1)), [])
                elif p == "/repos/o/r": res = {"default_branch": "main"}
                elif p == "/repos/o/r/commits/main/check-runs": res = {"check_runs": outer.checks}
                else: self.send_response(404); self.end_headers(); return
                d = json.dumps(res).encode()
                self.send_response(200); self.send_header("Content-Length", str(len(d))); self.end_headers(); self.wfile.write(d)
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
