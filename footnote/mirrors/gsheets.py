"""Google Sheets. Two ways to connect:
  mode "webapp" (easiest, no OAuth): paste a 12-line Apps Script into your sheet (docs/google-sheets.md)
  mode "api": a Google OAuth access token (env GOOGLE_SHEETS_TOKEN, or `gcloud auth print-access-token`)
"""
import json
import os
import shutil
import subprocess  # nosec B404
import urllib.parse
from .base import Mirror, MirrorError
from .http import call
from .. import config, mdconv

API = "https://sheets.googleapis.com/v4/spreadsheets"


class SheetsMirror(Mirror):
    type = "gsheets"
    supports_publish = True

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.mode = self.cfg.get("mode") or ("webapp" if self.cfg.get("webapp_url") else "api")
        self.base = (self.cfg.get("base_url") or os.environ.get("FOOTNOTE_SHEETS_URL") or API).rstrip("/")
        self.tab = self.cfg.get("sheet_name", "Tracker")

    def ping(self):
        try:
            if self.mode == "webapp":
                self._web("GET")
                return True, "Apps Script web app answered"
            sid = self._sid()
            if sid:
                self._api("GET", f"/{sid}?fields=properties.title")
                return True, "spreadsheet is reachable"
            self._token()
            return True, "access token found (the sheet is created on first sync)"
        except MirrorError as e:
            return False, str(e)

    def where(self):
        if self.mode == "webapp":
            return "Google Sheet via Apps Script web app"
        sid = (self.snapshot().get("meta") or {}).get("spreadsheet_id") or self.cfg.get("spreadsheet_id")
        return f"https://docs.google.com/spreadsheets/d/{sid}" if sid else "Google Sheet (not created yet)"

    # ---- auth (api mode)
    def _token(self):
        t = config.secret(self.cfg, default_env="GOOGLE_SHEETS_TOKEN")
        if not t and shutil.which("gcloud"):
            try:
                t = subprocess.run(["gcloud", "auth", "print-access-token"], capture_output=True,  # nosec B603 B607
                                   text=True, timeout=30, encoding="utf-8", errors="replace").stdout.strip()
            except Exception:
                t = ""
        if not t:
            raise MirrorError("Google Sheets: no access token. Use the Apps Script option (docs/google-sheets.md) "
                              "or set GOOGLE_SHEETS_TOKEN")
        return t

    def _api(self, method, path, body=None):
        return call(method, self.base + path, {"Authorization": f"Bearer {self._token()}"}, body)

    def _sid(self, create=False):
        snap = self.snapshot()
        sid = (snap.get("meta") or {}).get("spreadsheet_id") or self.cfg.get("spreadsheet_id")
        if sid and "/d/" in sid:
            sid = sid.split("/d/")[1].split("/")[0]
        if not sid and create:
            res = self._api("POST", "", {"properties": {"title": self.cfg.get("title", "Tracker")},
                                         "sheets": [{"properties": {"title": self.tab}}]})
            sid = res["spreadsheetId"]
            snap.setdefault("meta", {})["spreadsheet_id"] = sid
            self.save_snapshot(snap)
        return sid

    # ---- webapp mode
    def _web(self, method, body=None, tab=None):
        url = self.cfg["webapp_url"]
        sec = config.secret(self.cfg, key="secret", env_key="secret_env", default_env="TRACKER_SHEET_SECRET")
        if method == "GET":
            q = urllib.parse.urlencode({"secret": sec, **({"tab": tab} if tab else {})})
            res = call("GET", f"{url}{'&' if '?' in url else '?'}{q}")
        else:
            res = call("POST", url, None, {"secret": sec, **body})
        if res.get("error"):
            raise MirrorError(f"Apps Script says: {res['error']} (check the secret)")
        return res

    # ---- interface
    def pull(self):
        if self.mode == "webapp":
            values = self._web("GET").get("values", [])
        else:
            sid = self._sid()
            if not sid:
                return []
            values = self._api("GET", f"/{sid}/values/{urllib.parse.quote(self.tab)}").get("values", [])
        if not values:
            return []
        head = [str(h).strip().lower().replace(" ", "_") for h in values[0]]
        return [{h: (r[i] if i < len(r) else "") for i, h in enumerate(head)} for r in values[1:]]

    def publish(self, docs):
        snap = self.snapshot()
        tabs = snap.setdefault("meta", {}).setdefault("tabs", [])
        for name, md in docs.items():
            rows = mdconv.rows(md)
            if self.mode == "webapp":
                self._web("POST", {"tab": name, "values": rows})
                continue
            sid = self._sid(create=True)
            if name not in tabs:
                try:
                    self._api("POST", f"/{sid}:batchUpdate", {"requests": [{"addSheet": {"properties": {"title": name}}}]})
                except MirrorError:
                    pass                                    # tab already exists
                tabs.append(name)
                self.save_snapshot(snap)
            tab = urllib.parse.quote(name)
            self._api("POST", f"/{sid}/values/{tab}:clear", {})
            self._api("PUT", f"/{sid}/values/{tab}?valueInputOption=RAW", {"values": rows})

    def push(self, columns, all_rows, changed_ids):
        values = [columns] + [[r.get(c, "") for c in columns] for r in all_rows]
        if self.mode == "webapp":
            self._web("POST", {"values": values})
            return
        sid = self._sid(create=True)
        tab = urllib.parse.quote(self.tab)
        self._api("POST", f"/{sid}/values/{tab}:clear", {})
        self._api("PUT", f"/{sid}/values/{tab}?valueInputOption=RAW", {"values": values})
