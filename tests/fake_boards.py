import json, re, threading, urllib.parse as up, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def _serve(handler):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


class FakeIssues:
    def __init__(self):
        self.issues, self.n, self.writes = {}, 0, 0
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def _do(self, method):
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                if self.headers.get("Authorization") != "Bearer ghi":
                    self.send_response(401); self.end_headers(); return
                path = self.path.split("?")[0]
                res, code = [], 200
                if method == "GET" and path == "/repos/o/r/issues":
                    page = int(re.search(r"[?&]page=(\d+)", self.path).group(1))
                    res = list(outer.issues.values())[(page - 1) * 100: page * 100]
                elif method == "GET" and path == "/repos/o/r":
                    res = {"full_name": "o/r"}
                elif method == "POST" and path == "/repos/o/r/issues":
                    outer.writes += 1; outer.n += 1
                    res = {"number": outer.n, "title": body["title"], "state": "open", "labels": [{"name": l} for l in body.get("labels", [])]}
                    outer.issues[outer.n] = res
                elif method == "PATCH" and (m := re.match(r"^/repos/o/r/issues/(\d+)$", path)):
                    outer.writes += 1
                    i = outer.issues[int(m.group(1))]
                    if "title" in body: i["title"] = body["title"]
                    if "state" in body: i["state"] = body["state"]
                    if "labels" in body: i["labels"] = [{"name": l} for l in body["labels"]]
                    res = i
                else:
                    code = 404
                d = json.dumps(res).encode()
                self.send_response(code); self.send_header("Content-Length", str(len(d))); self.end_headers(); self.wfile.write(d)
            do_GET = lambda s: s._do("GET"); do_POST = lambda s: s._do("POST"); do_PATCH = lambda s: s._do("PATCH")
        self.srv = _serve(H)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def human_add(self, title):
        self.n += 1
        self.issues[self.n] = {"number": self.n, "title": title, "state": "open", "labels": []}

    def by_prefix(self, tid):
        return next(i for i in self.issues.values() if i["title"].startswith(f"[{tid}]"))


class FakeTrello:
    def __init__(self):
        self.lists, self.cards, self.writes = {}, {}, 0
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def _do(self, method):
                u = up.urlparse(self.path); q = {k: v[0] for k, v in up.parse_qs(u.query).items()}
                if q.get("key") != "K" or q.get("token") != "T":
                    self.send_response(401); self.end_headers(); return
                res, code = {}, 200
                if method == "GET" and u.path == "/1/boards/B/lists":
                    res = [{"id": i, "name": n} for i, n in outer.lists.items()]
                elif method == "GET" and u.path == "/1/boards/B/cards":
                    res = [c for c in outer.cards.values() if not c.get("closed")]
                elif method == "GET" and u.path == "/1/boards/B":
                    res = {"name": "Board"}
                elif method == "POST" and u.path == "/1/lists":
                    i = uuid.uuid4().hex; outer.lists[i] = q["name"]; res = {"id": i}
                elif method == "POST" and u.path == "/1/cards":
                    outer.writes += 1; i = uuid.uuid4().hex
                    outer.cards[i] = {"id": i, "name": q["name"], "idList": q["idList"], "labels": []}; res = outer.cards[i]
                elif method == "PUT" and (m := re.match(r"^/1/cards/(\w+)$", u.path)):
                    outer.writes += 1; c = outer.cards[m.group(1)]
                    if "name" in q: c["name"] = q["name"]
                    if "idList" in q: c["idList"] = q["idList"]
                    if q.get("closed") == "true": c["closed"] = True
                    res = c
                else:
                    code = 404
                d = json.dumps(res).encode()
                self.send_response(code); self.send_header("Content-Length", str(len(d))); self.end_headers(); self.wfile.write(d)
            do_GET = lambda s: s._do("GET"); do_POST = lambda s: s._do("POST"); do_PUT = lambda s: s._do("PUT")
        self.srv = _serve(H)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}/1"

    def list_id(self, label):
        return next(i for i, n in self.lists.items() if n == label)

    def card(self, tid):
        return next(c for c in self.cards.values() if c["name"].startswith(f"[{tid}]"))
