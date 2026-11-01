import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from .base import MirrorError
from ..security import redact

MAX_RESPONSE = 25_000_000
LOCAL = ("localhost", "127.0.0.1", "::1")
SENSITIVE = ("authorization", "token", "key", "secret")


def _has_credentials(url, headers):
    q = urllib.parse.urlparse(url).query.lower()
    return any(any(w in h.lower() for w in SENSITIVE) for h in (headers or {})) or any(
        w in q for w in ("token=", "key=", "secret=", "consumer_secret="))


def check_url(url, headers=None):
    u = urllib.parse.urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise MirrorError("only http:// and https:// addresses are allowed")
    if u.scheme == "http" and u.hostname not in LOCAL and _has_credentials(url, headers) and not os.environ.get("FOOTNOTE_ALLOW_INSECURE"):
        raise MirrorError(f"refusing to send credentials to {u.hostname} over plain http:// - use https://")


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    """Never carry credentials to a different host, or from https down to http."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is None:
            return None
        old_u, new_u = urllib.parse.urlparse(req.full_url), urllib.parse.urlparse(newurl)
        if new_u.scheme not in ("http", "https"):
            return None
        if old_u.netloc != new_u.netloc or (old_u.scheme == "https" and new_u.scheme != "https"):
            for h in list(new.headers):
                if any(w in h.lower() for w in SENSITIVE):
                    del new.headers[h]
            for h in list(new.unredirected_hdrs):
                if any(w in h.lower() for w in SENSITIVE):
                    del new.unredirected_hdrs[h]
        return new


_OPENER = urllib.request.build_opener(_SafeRedirect)


def call(method, url, headers=None, body=None, retries=4, timeout=30, raw=False):
    check_url(url, headers)
    data = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type": "application/json", **(headers or {})}
    for attempt in range(retries):
        req = urllib.request.Request(url, data=data, headers=h, method=method)
        try:
            with _OPENER.open(req, timeout=timeout) as r:
                blob = r.read(MAX_RESPONSE + 1)
                if len(blob) > MAX_RESPONSE:
                    raise MirrorError(f"{url.split('/')[2]} sent an unexpectedly large reply")
                txt = blob.decode("utf-8", "replace") or "{}"
                if raw:                                  # e.g. Slack answers with the plain text "ok"
                    return {"text": txt}
                return json.loads(txt)
        except urllib.error.HTTPError as e:
            detail = redact(e.read(2000).decode("utf-8", "ignore")[:300])
            if e.code in (429, 502, 503) and attempt < retries - 1:
                time.sleep(float(e.headers.get("Retry-After", 1 + attempt)))
                continue
            hint = {401: "the token is wrong or expired", 403: "access denied (did you share the page/sheet with the integration?)",
                    404: "not found (check the ID/URL and that it is shared with the integration)"}.get(e.code, "")
            raise MirrorError(redact(f"{method} {url.split('?')[0]} -> HTTP {e.code} {hint} {detail}").strip())
        except MirrorError:
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if attempt < retries - 1:
                time.sleep(1 + attempt)
                continue
            raise MirrorError(redact(f"network problem talking to {url.split('/')[2]}: {e}"))
        except ValueError as e:
            raise MirrorError(f"unexpected reply from {url.split('/')[2]}: {e}")
