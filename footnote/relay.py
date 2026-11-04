"""Webhook relay: a tiny, dependency-free server you host anywhere (a VPS, Render, Fly, Railway, a Raspberry Pi).

Why: Zapier / Make / n8n / GitHub can only call a PUBLIC address, and your laptop has none. They POST to the
relay; your tracker PULLS from it (outbound only), so nothing on your computer is exposed to the internet.

Two secrets: PUSH key (goes into Zapier URLs, can only add events) and PULL token (stays on your machine).
Delivery is at-least-once: events are removed only after the tracker acknowledges them.
"""
import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from . import config
from .security import QuietServer
from .mirrors.http import call
from .mirrors.base import MirrorError

MAX_BODY = 16_384
MAX_QUEUE = 1000
REDELIVER_AFTER = 300


class Queue:
    def __init__(self, path=None):
        self.path, self.lock = Path(path) if path else None, threading.Lock()
        self.events, self.seq = [], 0
        if self.path and self.path.exists():
            try:
                d = json.loads(self.path.read_text(encoding="utf-8"))
                self.events, self.seq = d["events"], d["seq"]
            except (OSError, ValueError, KeyError):
                pass

    def _save(self):
        if self.path:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"events": self.events, "seq": self.seq}), encoding="utf-8")
            tmp.replace(self.path)

    def push(self, payload):
        with self.lock:
            if len(self.events) >= MAX_QUEUE:
                return None
            self.seq += 1
            self.events.append({"id": self.seq, "ts": time.time(), "payload": payload, "delivered": 0})
            self._save()
            return self.seq

    def pull(self, limit=50, redeliver_after=REDELIVER_AFTER):
        now = time.time()
        with self.lock:
            out = [e for e in self.events if now - e["delivered"] >= redeliver_after][:limit]   # >= : a coarse clock (Windows) can make two calls look simultaneous
            for e in out:
                e["delivered"] = now
            self._save()
            return [{"id": e["id"], "ts": e["ts"], "payload": e["payload"]} for e in out]

    def ack(self, ids):
        ids = set(ids)
        with self.lock:
            self.events = [e for e in self.events if e["id"] not in ids]
            self._save()


def make_handler(queue, push_key, pull_token, redeliver_after=REDELIVER_AFTER):
    hits = {}

    class H(BaseHTTPRequestHandler):
        timeout = 15
        sys_version = ""

        def log_message(self, *a):
            pass

        def _send(self, code, obj):
            d = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(d)))
            self.end_headers()
            self.wfile.write(d)

        def _auth(self, q, want):
            got = (self.headers.get("Authorization", "")[7:] if self.headers.get("Authorization", "").startswith("Bearer ")
                   else (q.get("key") or q.get("token") or [""])[0])
            return secrets.compare_digest(got, want)

        def _limited(self):
            ip, now = self.client_address[0], time.time()
            recent = [t for t in hits.get(ip, []) if now - t < 60]
            recent.append(now)
            hits[ip] = recent
            return len(recent) > 120

        def _body(self):
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return None
            if n < 0 or n > MAX_BODY:
                return None
            raw = self.rfile.read(n) or b"{}"
            try:
                return json.loads(raw)
            except ValueError:
                from urllib.parse import parse_qsl
                return {k: v for k, v in parse_qsl(raw.decode("utf-8", "replace"))}   # form posts (some Zapier modes)

        def do_GET(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if u.path == "/health":
                return self._send(200, {"ok": True})
            if self._limited():
                return self._send(429, {"error": "slow down"})
            if u.path == "/pull":
                if not self._auth(q, pull_token):
                    return self._send(401, {"error": "bad token"})
                return self._send(200, {"events": queue.pull(int((q.get("limit") or [50])[0]), redeliver_after)})
            self._send(404, {"error": "not found"})

        def do_POST(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if self._limited():
                return self._send(429, {"error": "slow down"})
            if u.path == "/event":
                if not self._auth(q, push_key):
                    return self._send(401, {"error": "bad key"})
                body = self._body()
                if body is None:
                    return self._send(413, {"error": "too large"})
                if not isinstance(body, dict) or not body:
                    return self._send(400, {"error": "send a JSON object, e.g. {\"text\": \"finished the logo\"}"})
                i = queue.push(body)
                return self._send(200 if i else 503, {"queued": i} if i else {"error": "queue full"})
            if u.path == "/ack":
                if not self._auth(q, pull_token):
                    return self._send(401, {"error": "bad token"})
                body = self._body() or {}
                queue.ack(body.get("ids", []))
                return self._send(200, {"ok": True})
            self._send(404, {"error": "not found"})
    return H


def serve(port=8080, host="127.0.0.1", push_key=None, pull_token=None, store=None):
    push_key, pull_token = push_key or secrets.token_urlsafe(16), pull_token or secrets.token_urlsafe(24)
    srv = QuietServer((host, port), make_handler(Queue(store), push_key, pull_token))
    print(f"Relay listening on port {srv.server_address[1]}\n  PUSH key (put in Zapier/Make):  {push_key}\n"
          f"  PULL token (keep private):      {pull_token}\n  Zapier URL:  https://YOUR-HOST/event?key={push_key}\n"
          f"  On your computer:  footnote add-relay https://YOUR-HOST --pull-token {pull_token}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return srv


# ----------------------------------------------------------------- client side (runs inside the tracker)
def fetch(item, limit=50):
    """-> list of {"id", "payload"}"""
    url = item["url"].rstrip("/")
    tok = config.secret(item, key="pull_token", env_key="pull_token_env", default_env="FOOTNOTE_RELAY_TOKEN")
    if not tok:
        raise MirrorError("relay: pull token missing (set it with: footnote add-relay URL --pull-token …)")
    return call("GET", f"{url}/pull?limit={limit}", {"Authorization": f"Bearer {tok}"}, retries=2, timeout=8).get("events", [])


def ack(item, ids):
    if ids:
        tok = config.secret(item, key="pull_token", env_key="pull_token_env", default_env="FOOTNOTE_RELAY_TOKEN")
        call("POST", item["url"].rstrip("/") + "/ack", {"Authorization": f"Bearer {tok}"}, {"ids": ids}, retries=2, timeout=8)
