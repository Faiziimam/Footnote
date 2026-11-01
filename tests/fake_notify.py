import json, socketserver, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeSlack:
    def __init__(self):
        self.posts = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_POST(self):
                outer.posts.append(json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))["text"])
                self.send_response(200); self.send_header("Content-Length", "2"); self.end_headers(); self.wfile.write(b"ok")
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"https://127.0.0.1:{self.srv.server_address[1]}"
        self.http = f"http://127.0.0.1:{self.srv.server_address[1]}"


class FakeSMTP:
    def __init__(self):
        self.mails = []
        outer = self

        class H(socketserver.StreamRequestHandler):
            def handle(self):
                w = lambda s: (self.wfile.write((s + "\r\n").encode()), self.wfile.flush())
                w("220 fake")
                data, in_data, frm, to = [], False, "", []
                while True:
                    line = self.rfile.readline().decode("utf-8", "replace")
                    if not line:
                        return
                    if in_data:
                        if line.strip() == ".":
                            outer.mails.append({"from": frm, "to": to, "data": "\n".join(data)}); in_data = False; w("250 queued")
                        else:
                            data.append(line.rstrip("\r\n"))
                        continue
                    c = line[:4].upper()
                    if c in ("EHLO", "HELO"): w("250 hello")
                    elif c == "MAIL": frm = line.split(":", 1)[1].strip(); w("250 ok")
                    elif c == "RCPT": to.append(line.split(":", 1)[1].strip()); w("250 ok")
                    elif c == "DATA": in_data = True; w("354 go")
                    elif c == "QUIT": w("221 bye"); return
                    else: w("250 ok")
        self.srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), H)
        self.srv.daemon_threads = True
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.port = self.srv.server_address[1]
