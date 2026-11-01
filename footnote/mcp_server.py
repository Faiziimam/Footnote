"""MCP server (stdio, JSON-RPC). Works with any MCP-capable agent: Claude, Cursor, Codex, Gemini CLI,
Copilot, Windsurf, ... Exposes a handful of plain tools; no dependencies."""
import json
import sys
from .api import Tracker, TrackerError
from .guide import SERVER_INSTRUCTIONS
from .security import UNTRUSTED

STATUS = {"type": "string", "enum": ["Not started", "In progress", "Blocked", "Done"]}
TOOLS = [
    {"name": "tracker_list", "description": "List all tasks with status, epic, relationships (waiting_on, children).",
     "inputSchema": {"type": "object", "properties": {"status": {**STATUS, "description": "optional filter"}}}},
    {"name": "tracker_update", "description": "Tell the tracker what happened, in plain English. "
     "e.g. 'finished the login page and started checkout'. Unclear matches are reported, never guessed.",
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
    {"name": "tracker_set_status", "description": "Set one task's status by ID.",
     "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}, "status": STATUS,
                                                      "note": {"type": "string"}}, "required": ["id", "status"]}},
    {"name": "tracker_add_task", "description": "Add a new task. Optionally link it to a parent or dependencies.",
     "inputSchema": {"type": "object", "properties": {"title": {"type": "string"}, "epic": {"type": "string"},
                     "parent": {"type": "string"}, "depends_on": {"type": "array", "items": {"type": "string"}},
                     "status": STATUS}, "required": ["title"]}},
    {"name": "tracker_link", "description": "Add or remove a relationship between tasks (type like depends_on, "
     "parent, related, caused_by).", "inputSchema": {"type": "object", "properties": {
         "id": {"type": "string"}, "type": {"type": "string"}, "target": {"type": "string"},
         "remove": {"type": "boolean"}}, "required": ["id", "type", "target"]}},
    {"name": "tracker_project", "description": "Call ONCE at the start of a multi-step request. Names the project, its kind "
     "(portfolio, ecommerce, saas, mobile app, marketing campaign, content, finance business, client project, event, research, "
     "or anything else) and goal. Returns typical work for that kind so you can plan tasks.",
     "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}, "kind": {"type": "string"},
                     "goal": {"type": "string"}}, "required": ["kind"]}},
    {"name": "tracker_record", "description": "Write to the project's memory: a decision (with the WHY), risk, learning, "
     "milestone or note. One plain sentence.", "inputSchema": {"type": "object", "properties": {
         "kind": {"type": "string", "enum": ["decision", "risk", "learning", "milestone", "note", "issue"]},
         "text": {"type": "string"}, "task": {"type": "string"}}, "required": ["kind", "text"]}},
    {"name": "tracker_metric", "description": "Record a real business number (revenue, orders, visitors, spend, hours, "
     "cash_balance, anything). Never invent numbers. Any name works.", "inputSchema": {"type": "object", "properties": {
         "name": {"type": "string"}, "value": {"type": "number"}, "date": {"type": "string"}, "unit": {"type": "string"}},
         "required": ["name", "value"]}},
    {"name": "tracker_metric_fix", "description": "Correct or remove a recorded number by its ID (see tracker_metrics). "
     "Use when a figure was wrong. Provide value to correct it, or delete=true to remove it.",
     "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}, "value": {"type": "number"},
                     "delete": {"type": "boolean"}}, "required": ["id"]}},
    {"name": "tracker_metrics", "description": "List recorded numbers with their IDs (optionally for one metric name).",
     "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}}}},
    {"name": "tracker_set_field", "description": "Set a field on a task: due (plain words ok: 'next friday'), estimate ('3d'), "
     "priority (urgent/high/medium/low), owner, or any custom field.", "inputSchema": {"type": "object", "properties": {
         "id": {"type": "string"}, "field": {"type": "string"}, "value": {"type": "string"}}, "required": ["id", "field", "value"]}},
    {"name": "tracker_add_field", "description": "Add a custom field to every task, optionally CALCULATED from a safe formula. "
     "Functions: days_since(date) days_until(date) days_between(a,b) round min max iif(cond,a,b). Variables: any field, "
     "age_days, is_overdue, n_children, children_done, n_blockers, est_left. Example: formula 'days_since(started)'.",
     "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}, "type": {"type": "string"},
                     "formula": {"type": "string"}}, "required": ["name"]}},
    {"name": "tracker_invoice", "description": "Track an invoice you sent: action 'add' (client, amount, due ['in 30 days' ok]) or 'paid' (id).",
     "inputSchema": {"type": "object", "properties": {"action": {"type": "string", "enum": ["add", "paid"]}, "client": {"type": "string"},
                     "amount": {"type": "number"}, "due": {"type": "string"}, "id": {"type": "string"}}, "required": ["action"]}},
    {"name": "tracker_archive", "description": "Remove a task that is no longer relevant (nothing is lost; it can be restored). "
     "Never delete tasks any other way.", "inputSchema": {"type": "object", "properties": {"id": {"type": "string"},
                     "reason": {"type": "string"}}, "required": ["id"]}},
    {"name": "tracker_undo", "description": "Undo the last change to the tracker if it was a mistake (yours or automatic). "
     "Reverted tasks are locked so automation does not redo them.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "tracker_report", "description": "Get the project report (progress, what was built, figures, risks, team, "
     "handover checklist). audience: all | manager | everyone | developer.",
     "inputSchema": {"type": "object", "properties": {"audience": {"type": "string"}}}},
    {"name": "tracker_catchup", "description": "What changed (tasks, people, decisions, collisions). Use at the start of a "
     "session or before touching shared areas. since: 3d, 2w, yesterday or a date; default = since this person last looked.",
     "inputSchema": {"type": "object", "properties": {"since": {"type": "string"}}}},
    {"name": "tracker_whois", "description": "Who knows or owns something? Pass a person's name, a task ID (T-004) or a "
     "folder/area (checkout/). Use before changing shared code to avoid colliding with a teammate.",
     "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "tracker_assign", "description": "Set the owner of a task.", "inputSchema": {"type": "object", "properties": {
         "id": {"type": "string"}, "person": {"type": "string"}}, "required": ["id", "person"]}},
    {"name": "tracker_sync", "description": "Re-read docs/git and refresh all connected trackers.",
     "inputSchema": {"type": "object", "properties": {}}},
]


def fmt_tasks(ts):
    if not ts:
        return "No tasks yet."
    lines = []
    for t in ts:
        extra = (f" — waiting on {', '.join(t['waiting_on'])}" if t["waiting_on"] else "")
        lines.append(f"{t['id']} [{t['status_label']}] {t['epic']} :: {t['title']}{extra}")
    return "\n".join(lines)


def call_tool(tr, name, a):
    if name == "tracker_list":
        ts = tr.tasks()
        if a.get("status"):
            ts = [t for t in ts if t["status_label"] == a["status"]]
        return UNTRUSTED + fmt_tasks(ts)
    if name == "tracker_update":
        res = tr.say(a["text"], who="agent", create_missing=True)
        return "\n".join(r["message"] for r in res) or "Nothing to update."
    if name == "tracker_set_status":
        tid = tr.set_status(a["id"], a["status"], a.get("note", ""), who="agent")
        return f"{tid} is now {a['status']}."
    if name == "tracker_add_task":
        tid = tr.add_task(a["title"], a.get("epic", "Inbox"), a.get("parent"), a.get("depends_on") or (),
                          a.get("status", "todo"), who="agent")
        return f"Added {tid}: {a['title']}"
    if name == "tracker_link":
        tr.link(a["id"], a["type"], a["target"], bool(a.get("remove")))
        return f"{'Removed' if a.get('remove') else 'Linked'} {a['id']} {a['type']} {a['target']}."
    if name == "tracker_project":
        return tr.set_project(a.get("name"), a["kind"], a.get("goal"))
    if name == "tracker_record":
        tr.record(a["kind"], a["text"], a.get("task"), who="agent")
        return f"Recorded {a['kind']}."
    if name == "tracker_metric":
        added = tr.metric(a["name"], a["value"], a.get("date"), a.get("unit", ""), who="agent")
        return f"Recorded {a['name']} = {a['value']}." if added else "Already recorded."
    if name == "tracker_metric_fix":
        if a.get("delete"):
            tr.metric_delete(a["id"])
            return f"Removed figure {a['id']}."
        tr.metric_fix(a["id"], a["value"])
        return f"Corrected figure {a['id']} to {a['value']}."
    if name == "tracker_metrics":
        es = tr.metrics_list(a.get("name"))
        return UNTRUSTED + ("\n".join(f"{e['id']}  {e['date']}  {e['name']} = {e['value']} {e.get('unit','')} ({e.get('source','')})" for e in es) or "No figures yet.")
    if name == "tracker_set_field":
        t = tr.set_field(a["id"], a["field"], a["value"], who="agent")
        return f"{t} {a['field']} set."
    if name == "tracker_add_field":
        sample = tr.add_field(a["name"], a.get("type", "string"), a.get("formula"))
        return f"Field {a['name']} added." + (f" Example value: {sample}" if sample is not None else "")
    if name == "tracker_invoice":
        if a["action"] == "paid":
            return f"{tr.invoice_paid(a['id'])['id']} marked as paid."
        return f"Added {tr.add_invoice(a['client'], a['amount'], a['due'])}."
    if name == "tracker_archive":
        tr.archive(a["id"], a.get("reason", ""))
        return f"{a['id'].upper()} archived."
    if name == "tracker_undo":
        lines, locked = tr.undo()
        return ("Undone:\n" + "\n".join(lines)) if lines else "Nothing to undo."
    if name == "tracker_report":
        return UNTRUSTED + tr.report(a.get("audience", "all"))
    if name == "tracker_catchup":
        return UNTRUSTED + tr.catchup(a.get("since"))
    if name == "tracker_whois":
        return UNTRUSTED + tr.whois(a["query"])
    if name == "tracker_assign":
        t, who = tr.assign(a["id"], a["person"])
        return f"{t} is now owned by {who}."
    if name == "tracker_sync":
        r = tr.sync()
        return f"Synced. {r.changed} change(s)." + ("".join(f"\nWarning: {w}" for w in r.warnings))
    raise TrackerError(f"unknown tool {name}")


def handle(tr, msg):
    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if method == "initialize":
        return {"protocolVersion": params.get("protocolVersion", "2024-11-05"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "footnote", "version": "0.2.0"},
                "instructions": SERVER_INSTRUCTIONS}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        try:
            text = call_tool(tr, params.get("name"), params.get("arguments") or {})
            return {"content": [{"type": "text", "text": text}]}
        except TrackerError as e:
            return {"content": [{"type": "text", "text": str(e)}], "isError": True}
        except Exception as e:  # never crash the agent's session
            return {"content": [{"type": "text", "text": f"Tracker problem: {e}"}], "isError": True}
    if method == "ping":
        return {}
    if mid is None:
        return None      # notification
    raise KeyError(method)


def serve(project, vault=None, stdin=sys.stdin, stdout=sys.stdout):
    tr = Tracker(project, vault)
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        try:
            res = handle(tr, msg)
            out = None if res is None else {"jsonrpc": "2.0", "id": msg.get("id"), "result": res}
        except KeyError:
            out = {"jsonrpc": "2.0", "id": msg.get("id"), "error": {"code": -32601, "message": "method not found"}}
        if out:
            stdout.write(json.dumps(out) + "\n")
            stdout.flush()
