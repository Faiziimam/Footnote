import json, re, threading, urllib.parse as up, datetime as dt
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def serve(handler):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


class FakeShopify:
    def __init__(self, n=300):
        today = dt.datetime.now(dt.timezone.utc)
        self.orders = [{"id": 1000 + i, "created_at": (today - dt.timedelta(days=i % 20)).isoformat(), "total_price": "10.00",
                        "currency": "USD", "financial_status": "paid", "cancelled_at": None, "refunds": []} for i in range(n)]
        self.orders[1]["refunds"] = [{"id": 77, "created_at": today.isoformat(), "transactions": [{"kind": "refund", "amount": "4.00"}]}]
        self.orders[2]["cancelled_at"] = today.isoformat()
        self.orders[3]["financial_status"] = "refunded"; self.orders[3]["refunds"] = [{"id": 78, "transactions": [{"kind": "refund", "amount": "10.00"}]}]
        self.orders[4]["currency"] = "EUR"
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_GET(self):
                if self.headers.get("X-Shopify-Access-Token") != "shpat":
                    self.send_response(401); self.end_headers(); return
                u = up.urlparse(self.path); q = {k: v[0] for k, v in up.parse_qs(u.query).items()}
                if u.path.endswith("/shop.json"):
                    res = {"shop": {"name": "x"}}
                else:
                    sid, lim = int(q.get("since_id", 0)), int(q.get("limit", 50))
                    res = {"orders": [o for o in outer.orders if o["id"] > sid][:lim]}
                d = json.dumps(res).encode()
                self.send_response(200); self.send_header("Content-Length", str(len(d))); self.end_headers(); self.wfile.write(d)
        self.srv = serve(H); self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"


class FakeWoo:
    def __init__(self):
        d = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        self.orders = [{"id": i, "status": "completed", "total": "20.00", "currency": "GBP", "date_created": d, "refunds": []} for i in range(1, 121)]
        self.orders[0]["status"] = "cancelled"
        self.orders[1]["refunds"] = [{"id": 5, "total": "-6.00"}]
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_GET(self):
                u = up.urlparse(self.path); q = {k: v[0] for k, v in up.parse_qs(u.query).items()}
                if q.get("consumer_key") != "ck" or q.get("consumer_secret") != "cs":
                    self.send_response(401); self.end_headers(); return
                per, page = int(q.get("per_page", 10)), int(q.get("page", 1))
                d = json.dumps(outer.orders[(page - 1) * per: page * per]).encode()
                self.send_response(200); self.send_header("Content-Length", str(len(d))); self.end_headers(); self.wfile.write(d)
        self.srv = serve(H); self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
