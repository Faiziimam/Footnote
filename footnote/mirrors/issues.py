"""Two-way sync with issue/board tools. A task appears as "[T-004] Title"; whatever a person types without the
prefix becomes a new task and is renamed to carry its ID. Adapters: GitHub Issues, Trello."""
import os
import re
import time
import urllib.parse
from .base import Mirror, MirrorError
from .http import call
from .. import config
from ..store import LABELS, norm_status

PREFIX = re.compile(r"^\s*\[(T-\d{3,})\]\s*(.*)$", re.S)


def split_title(raw):
    m = PREFIX.match(raw or "")
    return (m.group(1).upper(), m.group(2).strip()) if m else ("", (raw or "").strip())


class PrefixedMirror(Mirror):
    supports_publish = False

    # subclasses implement: items() -> [{"ext", "raw", "status", "epic"}], create(row), update(item, fields), archive(item)
    def pull(self):
        rows = []
        for it in self.items():
            tid, title = split_title(it["raw"])
            row = {"id": tid, "title": title}
            if it.get("status"):
                row["status"] = it["status"]
            if it.get("epic"):
                row["epic"] = it["epic"]
            rows.append(row)
        return rows

    def push(self, columns, all_rows, changed_ids):
        items = self.items()
        by_id, orphans = {}, {}
        for it in items:
            tid, title = split_title(it["raw"])
            if tid:
                by_id[tid] = it
            else:
                orphans.setdefault(title.lower(), []).append(it)
        for rid in getattr(self, "removed", ()):
            if rid in by_id:
                self.archive(by_id[rid])
        for row in all_rows:
            rid = row["id"]
            if "*" not in changed_ids and rid not in changed_ids:
                continue
            it = by_id.get(rid) or (orphans.get(row["title"].strip().lower()) or [None]).pop(0) if rid not in by_id \
                else by_id[rid]
            if it is None:
                self.create(row)
                time.sleep(self.pause)
                continue
            fields = {}
            if it["raw"] != f"[{rid}] {row['title']}":
                fields["title"] = f"[{rid}] {row['title']}"
            if row.get("status") and (it.get("status") or "") != row["status"]:
                fields["status"] = row["status"]
            if row.get("epic") and (it.get("epic") or "") != row["epic"]:
                fields["epic"] = row["epic"]
            if fields:
                self.update(it, fields)
                time.sleep(self.pause)


class GitHubIssues(PrefixedMirror):
    type = "github-issues"

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.base = (self.cfg.get("base_url") or "https://api.github.com").rstrip("/")
        self.repo = self.cfg.get("repo", "")
        self.pause = 0 if self.cfg.get("base_url") else 0.2

    def _req(self, method, path, body=None):
        tok = config.secret(self.cfg, default_env="GITHUB_TOKEN")
        if not tok or not self.repo:
            raise MirrorError("GitHub Issues: needs repo=owner/name and a token (GITHUB_TOKEN with Issues read/write)")
        return call(method, self.base + path, {"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"}, body,
                    retries=3, timeout=20)

    def where(self):
        return f"https://github.com/{self.repo}/issues"

    def ping(self):
        try:
            self._req("GET", f"/repos/{self.repo}")
            return True, f"connected to {self.repo} issues"
        except MirrorError as e:
            return False, str(e)

    @staticmethod
    def _state(issue):
        names = {l["name"].lower() for l in issue.get("labels", [])}
        if issue["state"] == "closed":
            return LABELS["done"]
        if "status: blocked" in names:
            return LABELS["blocked"]
        if "status: in progress" in names:
            return LABELS["active"]
        return LABELS["todo"]

    def items(self):
        out, page = [], 1
        while True:
            batch = self._req("GET", f"/repos/{self.repo}/issues?state=all&per_page=100&page={page}")
            for i in batch:
                if "pull_request" in i:
                    continue
                epic = next((l["name"][6:].strip() for l in i.get("labels", []) if l["name"].lower().startswith("epic:")), "")
                out.append({"ext": i["number"], "raw": i["title"], "status": self._state(i), "epic": epic, "issue": i})
            if len(batch) < 100:
                return out
            page += 1

    def _labels(self, issue, status=None, epic=None):
        keep = [l["name"] for l in issue.get("labels", []) if not l["name"].lower().startswith(("status:", "epic:"))] if issue else []
        cur = [l["name"] for l in issue.get("labels", [])] if issue else []
        st = norm_status(status) if status else None
        if st is None and issue:
            st = {"Not started": "todo", "In progress": "active", "Blocked": "blocked", "Done": "done"}[self._state(issue)]
        if st == "active":
            keep.append("status: in progress")
        elif st == "blocked":
            keep.append("status: blocked")
        ep = epic if epic is not None else next((l[6:].strip() for l in cur if l.lower().startswith("epic:")), "")
        if ep:
            keep.append(f"epic: {ep}"[:50])
        return keep, st

    def create(self, row):
        labels, st = self._labels(None, row.get("status"), row.get("epic"))
        res = self._req("POST", f"/repos/{self.repo}/issues", {"title": f"[{row['id']}] {row['title']}", "labels": labels,
                                                              "body": "Tracked automatically by footnote. Edit the title/labels freely."})
        if st == "done":
            self._req("PATCH", f"/repos/{self.repo}/issues/{res['number']}", {"state": "closed"})

    def update(self, it, fields):
        body = {}
        if "title" in fields:
            body["title"] = fields["title"]
        labels, st = self._labels(it["issue"], fields.get("status"), fields.get("epic"))
        if "status" in fields or "epic" in fields:
            body["labels"] = labels
            body["state"] = "closed" if st == "done" else "open"
        self._req("PATCH", f"/repos/{self.repo}/issues/{it['ext']}", body)

    def archive(self, it):
        self._req("PATCH", f"/repos/{self.repo}/issues/{it['ext']}", {"state": "closed", "state_reason": "not_planned"})


class Trello(PrefixedMirror):
    type = "trello"

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.base = (self.cfg.get("base_url") or "https://api.trello.com/1").rstrip("/")
        self.pause = 0 if self.cfg.get("base_url") else 0.12
        self._lists = None

    def _req(self, method, path, params=None):
        key = config.secret(self.cfg, key="key", env_key="key_env", default_env="TRELLO_KEY")
        tok = config.secret(self.cfg, default_env="TRELLO_TOKEN")
        if not key or not tok or not self.cfg.get("board"):
            raise MirrorError("Trello: needs board=<board id>, plus TRELLO_KEY and TRELLO_TOKEN")
        q = urllib.parse.urlencode({"key": key, "token": tok, **(params or {})})
        return call(method, f"{self.base}{path}?{q}", None, None, retries=3, timeout=20)

    def where(self):
        return f"Trello board {self.cfg.get('board')}"

    def ping(self):
        try:
            self._req("GET", f"/boards/{self.cfg['board']}", {"fields": "name"})
            return True, "connected to the Trello board"
        except (MirrorError, KeyError) as e:
            return False, str(e)

    def lists(self):
        if self._lists is None:
            have = {l["name"].lower(): l["id"] for l in self._req("GET", f"/boards/{self.cfg['board']}/lists", {"filter": "open"})}
            self._lists = {}
            for st, label in LABELS.items():
                lid = have.get(label.lower()) or self._req("POST", "/lists", {"name": label, "idBoard": self.cfg["board"]})["id"]
                self._lists[label] = lid
        return self._lists

    def items(self):
        names = {v: k for k, v in self.lists().items()}
        out = []
        for c in self._req("GET", f"/boards/{self.cfg['board']}/cards", {"filter": "open", "fields": "name,idList,labels"}):
            epic = next((l["name"][6:].strip() for l in c.get("labels", []) if l.get("name", "").lower().startswith("epic:")), "")
            out.append({"ext": c["id"], "raw": c["name"], "status": names.get(c["idList"], ""), "epic": epic})
        return out

    def create(self, row):
        lists = self.lists()
        self._req("POST", "/cards", {"idList": lists.get(row.get("status") or LABELS["todo"], lists[LABELS["todo"]]),
                                     "name": f"[{row['id']}] {row['title']}", "desc": f"Epic: {row.get('epic', '')}"})

    def update(self, it, fields):
        p = {}
        if "title" in fields:
            p["name"] = fields["title"]
        if "status" in fields:
            p["idList"] = self.lists()[fields["status"]]
        self._req("PUT", f"/cards/{it['ext']}", p)

    def archive(self, it):
        self._req("PUT", f"/cards/{it['ext']}", {"closed": "true"})
