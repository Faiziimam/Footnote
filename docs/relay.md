# Letting Zapier, Make, n8n or GitHub reach your tracker

Those services can only call a **public web address**; your laptop has none. The relay is a tiny server you put anywhere
(a $5 VPS, Render, Fly.io, Railway, a Raspberry Pi). They post to the relay; **your tracker pulls from it** (outbound only),
so nothing on your computer is exposed.

1. On the server:  `python footnote.pyz relay --host 0.0.0.0 --store /data/queue.json`  (or build `Dockerfile.relay`, which does this and runs as a non-root user).
   By default it listens on `127.0.0.1` only; use `0.0.0.0` only behind HTTPS.
   It prints a **PUSH key** (goes into Zapier URLs, can only add events) and a **PULL token** (stays private).
2. Put the relay behind HTTPS (your host usually does this; or Caddy/nginx).
3. In Zapier "Webhooks → POST": URL `https://YOUR-HOST/event?key=PUSH_KEY`, payload e.g. `{"text": "finished the logo"}`,
   `{"add": "Call the printer"}` or `{"id": "T-004", "status": "Done", "note": "approved by client"}`.
4. On your computer:  `footnote add-relay https://YOUR-HOST --pull-token PULL_TOKEN`

Events are removed from the relay only after your tracker confirms them (they repeat rather than get lost). Bad events are
skipped and written to `.footnote/log.txt`. Limits: 16 KB per event, 1000 queued, 120 requests/minute per address.
