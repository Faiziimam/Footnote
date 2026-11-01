"""Tiny in-memory stand-ins for Notion, the Google Sheets API and an Apps Script web app."""
import json
import re
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def serve(handler_cls):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


class FakeNotion:
    def __init__(self):
        self.dbs, self.pages, self.log, self.docs = {}, {}, [], {}
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass

            def _do(self, method):
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                outer.log.append((method, self.path))
                if self.headers.get("Authorization") != "Bearer good-token":
                    return self._send(401, {"message": "unauthorized"})
                code, res = outer.route(method, self.path, body)
                self._send(code, res)

            def _send(self, code, res):
                d = json.dumps(res).encode()
                self.send_response(code); self.send_header("Content-Length", str(len(d)))
                self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(d)

            do_GET = lambda s: s._do("GET")
            do_POST = lambda s: s._do("POST")
            do_PATCH = lambda s: s._do("PATCH")
            do_DELETE = lambda s: s._do("DELETE")
        self.srv = serve(H)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}/v1"

    @staticmethod
    def _stored(req):
        out = {}
        for name, v in req.items():
            if "title" in v:
                out[name] = {"type": "title", "title": [{"plain_text": x["text"]["content"]} for x in v["title"]]}
            elif "rich_text" in v:
                out[name] = {"type": "rich_text", "rich_text": [{"plain_text": x["text"]["content"]} for x in v["rich_text"]]}
            elif "select" in v:
                out[name] = {"type": "select", "select": v["select"]}
            elif "date" in v:
                out[name] = {"type": "date", "date": v["date"]}
            elif "number" in v:
                out[name] = {"type": "number", "number": v["number"]}
            elif "checkbox" in v:
                out[name] = {"type": "checkbox", "checkbox": v["checkbox"]}
        return out

    def route(self, method, path, body):
        path = path.removeprefix("/v1")
        if method == "POST" and path == "/databases":
            did = str(uuid.uuid4()); self.dbs[did] = body["properties"]; return 200, {"id": did}
        if method == "GET" and path == "/users/me":
            return 200, {"object": "user", "name": "Tracker bot", "bot": {}}
        m = re.match(r"^/databases/([^/]+)(/query)?$", path)
        if m:
            did = m.group(1)
            if did not in self.dbs:
                return 404, {"message": "not found"}
            if m.group(2):
                return 200, {"results": [p for p in self.pages.values() if p["db"] == did and not p.get("archived")], "has_more": False}
            if method == "PATCH":
                self.dbs[did].update(body["properties"]); return 200, {}
            return 200, {"properties": self.dbs[did]}
        if method == "POST" and path == "/pages" and "page_id" in body["parent"]:
            pid = str(uuid.uuid4())
            self.docs[pid] = {"title": body["properties"]["title"]["title"][0]["text"]["content"], "blocks": list(body.get("children", []))}
            return 200, {"id": pid}
        m = re.match(r"^/blocks/([^/]+)/children(\?.*)?$", path)
        if m:
            doc = self.docs.get(m.group(1))
            if doc is None:
                return 404, {"message": "not found"}
            if method == "GET":
                return 200, {"results": [{"id": b.setdefault("id", str(uuid.uuid4()))} for b in doc["blocks"]], "has_more": False}
            doc["blocks"] += body["children"]
            return 200, {}
        m = re.match(r"^/blocks/([^/]+)$", path)
        if m and method == "DELETE":
            for d in self.docs.values():
                d["blocks"] = [b for b in d["blocks"] if b.get("id") != m.group(1)]
            return 200, {}
        if method == "POST" and path == "/pages":
            pid = str(uuid.uuid4())
            self.pages[pid] = {"id": pid, "db": body["parent"]["database_id"], "properties": self._stored(body["properties"])}
            return 200, self.pages[pid]
        m = re.match(r"^/pages/([^/]+)$", path)
        if m and method == "GET":
            pid = m.group(1)
            if pid in self.docs or pid in self.pages:
                return 200, {"id": pid, "archived": bool(self.pages.get(pid, {}).get("archived"))}
            return 404, {"message": "not found"}
        if m and method == "PATCH":
            if body.get("archived"):
                self.pages[m.group(1)]["archived"] = True
                return 200, {}
            self.pages[m.group(1)]["properties"].update(self._stored(body["properties"])); return 200, {}
        return 404, {"message": "no route"}

    def page_by_id(self, tid):
        for p in self.pages.values():
            if p["properties"]["ID"]["rich_text"][0]["plain_text"] == tid:
                return p

    def human_set_status(self, tid, label):
        self.page_by_id(tid)["properties"]["Status"]["select"] = {"name": label}

    def human_add_row(self, title, status="Not started"):
        db = next(iter(self.dbs))
        pid = str(uuid.uuid4())
        self.pages[pid] = {"id": pid, "db": db, "properties": {
            "Name": {"type": "title", "title": [{"plain_text": title}]},
            "Status": {"type": "select", "select": {"name": status}}}}

    def count(self, method, prefix):
        return sum(1 for m, p in self.log if m == method and p.startswith(prefix))


class FakeSheets:
    def __init__(self):
        self.tabs, self.created = {}, 0
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass

            def _do(self, method):
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                if self.headers.get("Authorization") != "Bearer sheet-token":
                    return self._send(401, {})
                import urllib.parse as up
                p = self.path
                if method == "POST" and p == "/v4/spreadsheets":
                    outer.created += 1; return self._send(200, {"spreadsheetId": "SID123"})
                if method == "POST" and p.endswith(":batchUpdate"):
                    t = body["requests"][0]["addSheet"]["properties"]["title"]
                    if t in outer.tabs:
                        return self._send(400, {"error": "exists"})
                    outer.tabs[t] = []; return self._send(200, {})
                m = re.match(r"^/v4/spreadsheets/[^/]+/values/([^:?]+)(:clear)?", p)
                if m:
                    tab = up.unquote(m.group(1))
                    if method == "POST" and m.group(2):
                        outer.tabs[tab] = []; return self._send(200, {})
                    if method == "PUT":
                        outer.tabs[tab] = body["values"]; return self._send(200, {})
                    if method == "GET":
                        return self._send(200, {"values": outer.tabs.get(tab, [])})
                self._send(404, {})

            def _send(self, code, res):
                d = json.dumps(res).encode()
                self.send_response(code); self.send_header("Content-Length", str(len(d)))
                self.end_headers(); self.wfile.write(d)
            do_GET = lambda s: s._do("GET")
            do_POST = lambda s: s._do("POST")
            do_PUT = lambda s: s._do("PUT")
        self.srv = serve(H)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}/v4/spreadsheets"

    @property
    def values(self):
        return self.tabs.get("Tracker")

    def human_edit(self, tid, col, value):
        head = self.values[0]
        for r in self.values[1:]:
            if r[head.index("id")] == tid:
                r[head.index(col)] = value


class FakeAppsScript:
    SECRET = "pw"

    def __init__(self):
        self.tabs = {}
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass

            def _send(self, res):
                d = json.dumps(res).encode()
                self.send_response(200); self.send_header("Content-Length", str(len(d)))
                self.end_headers(); self.wfile.write(d)

            def do_GET(self):
                import urllib.parse as up
                q = up.parse_qs(up.urlparse(self.path).query)
                if q.get("secret") != ["pw"]:
                    return self._send({"error": "forbidden"})
                self._send({"values": outer.tabs.get((q.get("tab") or ["Tracker"])[0], [])})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
                if body.get("secret") != "pw":
                    return self._send({"error": "forbidden"})
                outer.tabs[body.get("tab", "Tracker")] = body["values"]; self._send({"ok": True})
        self.srv = serve(H)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}/exec"

    @property
    def values(self):
        return self.tabs.get("Tracker", [])
