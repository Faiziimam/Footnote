"""Local web page + HTTP API (and webhook). Binds to this computer only; every API call needs the token."""
import json
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from . import config, log, setup
from .security import QuietServer
from .api import Tracker, TrackerError

LOCK = threading.Lock()
def page():
    import pkgutil
    return pkgutil.get_data("footnote", "ui.html").decode("utf-8")


MAX_BODY = 1_000_000
FAIL_LIMIT = 10          # wrong tokens per minute per address before we stop answering


def csp(nonce):
    return ("default-src 'none'; script-src 'nonce-%s'; style-src 'nonce-%s'; connect-src 'self'; img-src 'self' data:; "
            "base-uri 'none'; form-action 'none'; frame-ancestors 'none'" % (nonce, nonce))


def make_handler(project, token, read_only=False):
    fails = {}
    tok = token.encode()

    class H(BaseHTTPRequestHandler):
        server_version = "footnote"
        sys_version = ""
        timeout = 15                              # a stalled client cannot hold a connection open forever

        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json", nonce=None):
            data = body if isinstance(body, bytes) else (body if isinstance(body, str) else json.dumps(body)).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype + "; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cross-Origin-Opener-Policy", "same-origin")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
            if nonce:
                self.send_header("Content-Security-Policy", csp(nonce))
            self.end_headers()
            self.wfile.write(data)

        def _host_ok(self):   # blocks DNS-rebinding: only our own loopback names are accepted
            h = urlparse("//" + self.headers.get("Host", "")).hostname
            return h in ("127.0.0.1", "localhost", "::1")

        def _origin_ok(self):   # blocks other websites from driving this server through the visitor's browser
            origin = self.headers.get("Origin")
            if origin and origin != f"http://{self.headers.get('Host', '')}":
                return False
            return self.headers.get("Sec-Fetch-Site", "same-origin") in ("same-origin", "none")

        def _locked_out(self):
            ip, now = self.client_address[0], time.time()
            fails[ip] = [t for t in fails.get(ip, []) if now - t < 60]
            return len(fails[ip]) >= FAIL_LIMIT

        def _authed(self, q):
            given = self.headers.get("X-Tracker-Token") or (q.get("token") or [""])[0]
            auth = self.headers.get("Authorization", "")
            if auth.startswith("Bearer "):
                given = auth[7:]
            ok = secrets.compare_digest(given.encode("utf-8", "replace"), tok)       # constant-time
            if not ok:
                fails.setdefault(self.client_address[0], []).append(time.time())
            return ok

        def _route(self, method):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if not self._host_ok():
                return self._send(403, {"error": "forbidden host"})
            if u.path in ("/", "/index.html") and method == "GET":
                nonce = secrets.token_urlsafe(16)
                html = page().replace("__TOKEN__", token).replace("__NONCE__", nonce).replace("__READONLY__", "true" if read_only else "false")
                return self._send(200, html, "text/html", nonce)
            if not u.path.startswith("/api/"):
                return self._send(404, {"error": "not found"})
            if not self._origin_ok():
                return self._send(403, {"error": "cross-site request refused"})
            if self._locked_out():
                return self._send(429, {"error": "too many wrong tokens; wait a minute"})
            if not self._authed(q):
                return self._send(401, {"error": "missing or wrong token"})
            body = {}
            if method == "POST":
                if read_only:
                    return self._send(403, {"error": "this is a read-only view"})
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    return self._send(400, {"error": "bad Content-Length"})
                if n < 0 or n > MAX_BODY:
                    return self._send(413, {"error": "request too large"})
                try:
                    body = json.loads(self.rfile.read(n) or b"{}")
                except ValueError:
                    return self._send(400, {"error": "body must be JSON"})
                if not isinstance(body, dict):
                    return self._send(400, {"error": "body must be a JSON object"})
            try:
                if u.path == "/api/deck" and method == "GET":
                    with LOCK:
                        data = Tracker(project).deck_bytes((q.get("for") or ["all"])[0] if isinstance(q.get("for"), list) else q.get("for", "all"))
                    return self._send(200, data, "application/vnd.openxmlformats-officedocument.presentationml.presentation")
                with LOCK:
                    tr = Tracker(project)
                    res = dispatch(tr, method, u.path, body, {k: v[0] for k, v in q.items()})
                return self._send(200, res)
            except TrackerError as e:
                return self._send(400, {"error": str(e)})
            except Exception as e:
                log.write(project, "error", f"web request failed: {type(e).__name__}: {e}")
                return self._send(500, {"error": "Something went wrong. Details are in .footnote/log.txt"})

        def do_GET(self):
            self._route("GET")

        def do_POST(self):
            self._route("POST")
    return H


def dispatch(tr, method, path, b, q=None):
    q = q or {}
    if method == "GET" and path == "/api/tasks":
        return {"tasks": tr.tasks(), "summary": tr.summary()}
    if method == "GET" and path == "/api/mirrors":
        return {"mirrors": tr.cfg.get("mirrors", []), "types": setup.TYPES, "fields": setup.FIELDS}
    if method == "GET" and path == "/api/report":
        return {"markdown": tr.report(q.get("for", "all"))}
    if method == "GET" and path == "/api/catchup":
        return {"markdown": tr.catchup(q.get("since"), peek=True)}
    if method == "GET" and path == "/api/whois":
        return {"text": tr.whois(q.get("q", ""))}
    if method == "POST" and path == "/api/record":
        return {"id": tr.record(b.get("kind", "note"), b.get("text", ""), b.get("task"), b.get("source", "web"))}
    if method == "POST" and path == "/api/metric":
        return {"added": tr.metric(b.get("name"), b.get("value"), b.get("date"), b.get("unit", ""), b.get("source", "web"))}
    if method == "POST" and path == "/api/say":
        return {"results": tr.say(b.get("text", ""), b.get("source", "web"))}
    if method == "POST" and path == "/api/event":
        return {"result": tr.handle_event(b)}
    if method == "POST" and path == "/api/status":
        return {"id": tr.set_status(b.get("id"), b.get("status"), b.get("note", ""), b.get("source", "web"))}
    if method == "POST" and path == "/api/tasks":
        return {"id": tr.add_task(b.get("title"), b.get("epic", "Inbox"), b.get("parent"),
                                  b.get("depends_on") or (), b.get("status", "todo"), b.get("source", "web"))}
    if method == "POST" and path == "/api/link":
        tr.link(b.get("id"), b.get("type"), b.get("target"), bool(b.get("remove")))
        return {"ok": True}
    if method == "POST" and path == "/api/connect":
        t = b.pop("type", "")
        for k in ("base_url", "command", "spreadsheet_base"):           # test/advanced options are not reachable from the web page
            b.pop(k, None)
        for k in ("path", "vault"):                                      # files must stay inside the project folder
            if b.get(k):
                target = (tr.project / str(b[k])).resolve()
                if tr.project.resolve() not in target.parents and target != tr.project.resolve():
                    raise TrackerError("For safety, files created from this page must stay inside the project folder.")
                b[k] = str(target)
        setup.add_tracker(tr.project, t, **b)
        r = Tracker(tr.project).sync()
        return {"ok": True, "warnings": r.warnings, "mirrors": r.mirrors}
    if method == "POST" and path == "/api/sync":
        r = tr.sync()
        return {"changed": r.changed, "warnings": r.warnings, "mirrors": r.mirrors}
    raise TrackerError("Unknown request.")


def serve(project, port=8765, open_browser=True, read_only=False):
    token = config.server_token(project)
    srv = QuietServer(("127.0.0.1", port), make_handler(project, token, read_only))
    url = f"http://localhost:{srv.server_address[1]}/"
    print(f"Tracker is open at {url}\n"
          f"Webhook for other tools: POST {url}api/event  with header  Authorization: Bearer {token}\n"
          "Press Ctrl+C to stop.")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return srv
