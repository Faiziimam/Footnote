"""Optional AI help. OFF unless you run `footnote add-llm`. Uses a command YOU choose (default: `claude -p`), so this
tool holds no API keys. What is sent: task titles/statuses, or the numbers in the report, never file contents or secrets.

Safety rules: the AI may only (a) pick from tasks that already exist, (b) rephrase facts we give it, (c) propose
formulas that our own checker accepts. Anything else it says is discarded.
"""
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess  # nosec B404
import time
from pathlib import Path
from . import formulas, log
from .store import atomic_write

STATUSES = ("todo", "active", "blocked", "done")


def enabled(cfg, feature=None):
    c = (cfg or {}).get("llm")
    if not c:
        return False
    if not (c.get("command") or shutil.which("claude")):
        return False
    return c.get(feature, True) if feature else True


def split_command(cmdline, windows=None):
    """Split a command line the way the user's system would. POSIX rules would eat the backslashes in C:\\Tools\\claude.cmd."""
    if (os.name == "nt") if windows is None else windows:
        return [t[1:-1] if len(t) > 1 and t[0] == t[-1] and t[0] in "\"'" else t for t in shlex.split(cmdline, posix=False)]
    return shlex.split(cmdline)


def ask(cfg, prompt, project=None, timeout=120):
    c = cfg["llm"]
    cmd = split_command(c.get("command") or "claude -p")
    def run(use_stdin):
        return subprocess.run(cmd + ([] if use_stdin else [prompt]), input=prompt if use_stdin else None, capture_output=True,  # nosec B603 B607
                              text=True, encoding="utf-8", errors="replace", timeout=timeout)
    try:
        try:
            r = run(bool(c.get("stdin")))
        except UnicodeEncodeError:                 # a legacy system locale can't pass this text as an argument: use stdin
            r = run(True)
    except Exception as e:
        if project:
            log.write(project, "warn", f"AI command failed: {e}")
        return None
    if r.returncode != 0:
        if project:
            log.write(project, "warn", f"AI command exited {r.returncode}: {r.stderr.strip()[:200]}")
        return None
    return r.stdout.strip()


def ask_json(cfg, prompt, project=None):
    out = ask(cfg, prompt, project)
    if not out:
        return None
    for open_, close in (("{", "}"), ("[", "]")):
        i, j = out.find(open_), out.rfind(close)
        if i != -1 and j > i:
            try:
                return json.loads(out[i:j + 1])
            except ValueError:
                continue
    return None


# ------------------------------------------------------------------ 1. understand an update the keyword matcher couldn't
def resolve_update(cfg, project, clause, tasks):
    """-> {"id", "status"} (both validated against reality) or None."""
    listing = [{"id": t, "title": fm["title"], "status": fm["status"]} for t, (fm, _) in tasks.items() if not fm.get("archived")][:80]
    prompt = ("You map a person's status update (any language) onto ONE existing task.\n"
              f"Tasks: {json.dumps(listing, ensure_ascii=False)}\n"
              f"Update: {json.dumps(clause, ensure_ascii=False)}\n"
              'Reply with ONLY JSON: {"id": "T-001" or null, "status": "todo"|"active"|"blocked"|"done" or null}. '
              "Use null for both if the update does not clearly refer to exactly one task and one status.")
    res = ask_json(cfg, prompt, project)
    if not isinstance(res, dict):
        return None
    tid, st = str(res.get("id") or "").upper(), res.get("status")
    if tid in tasks and not tasks[tid][0].get("archived") and st in STATUSES:
        return {"id": tid, "status": st}
    return None


# ------------------------------------------------------------------ 2. a plain-language paragraph for the report
def narrative(vault, cfg, project, facts):
    """Rephrase `facts` in 3-4 sentences. Discarded if it contains any number not in the facts. Cached per facts."""
    if not enabled(cfg, "narrative"):
        return ""
    blob = json.dumps(facts, sort_keys=True, ensure_ascii=False)
    h = hashlib.sha1(blob.encode(), usedforsecurity=False).hexdigest()[:10]
    p = Path(vault) / "_narrative.json"
    try:
        cache = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    if cache.get("hash") == h or (cache.get("text") and time.time() - cache.get("at", 0) < 6 * 3600):
        return cache.get("text", "")
    out = ask(cfg, "Write 3-4 plain sentences summarising this project's state for a busy non-technical reader. Use ONLY these facts, "
                   "invent nothing, no jargon, no headings.\nFacts: " + blob, project)
    if not out:
        return cache.get("text", "")
    allowed = set(re.findall(r"\d+(?:[.,]\d+)?", blob))
    if any(n not in allowed for n in re.findall(r"\d+(?:[.,]\d+)?", out)):
        log.write(project, "warn", "AI summary discarded: it contained a number that is not in the facts")
        return cache.get("text", "")
    atomic_write(p, json.dumps({"hash": h, "text": out, "at": time.time()}))
    return out


def facts_for(tasks, mets, risks):
    fms = [fm for fm, _ in tasks.values()]
    done = sum(1 for f in fms if f["status"] == "done")
    return {"percent_done": round(100 * done / len(fms)) if fms else 0, "tasks_total": len(fms), "tasks_done": done, "in_progress": sum(1 for f in fms if f["status"] == "active"),
            "blocked": [f["title"] for f in fms if f["status"] == "blocked"][:5], "open_risks": [e["text"] for e in risks][:4],
            "figures": {n: round(m["latest"]) for n, m in list(mets.items())[:5]}}


# ------------------------------------------------------------------ 3. propose calculated fields
def suggest_fields(cfg, project, kind, schema, sample_tasks):
    """-> [{"name", "type", "formula", "why"}] that our formula checker accepts on a real task."""
    prompt = ("Suggest up to 4 genuinely useful CALCULATED fields for a project tracker.\n"
              f"Project kind: {kind}. Existing fields: {sorted(schema['fields'])}.\n"
              "Formula language: arithmetic, comparisons, `a if cond else b`, and functions days_since(date) days_until(date) "
              "days_between(a,b) round min max iif(c,a,b). Variables: any existing field plus age_days, is_overdue, n_children, "
              "children_done, n_blockers, est_left.\n"
              'Reply ONLY with JSON: [{"name":"snake_case","type":"number|string|bool","formula":"...","why":"one sentence"}]')
    res = ask_json(cfg, prompt, project)
    out = []
    for item in res if isinstance(res, list) else []:
        try:
            name, formula = str(item["name"]), str(item["formula"])
        except (KeyError, TypeError):
            continue
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,30}", name) or name in schema["fields"]:
            continue
        try:
            formulas.check(formula)
            if sample_tasks:
                formulas.evaluate(formula, formulas.task_env(sample_tasks[0]))
        except formulas.FormulaError as e:
            if "unknown field" in str(e) or "isn't allowed" in str(e) or "only these" in str(e) or "could not" in str(e):
                continue
        out.append({"name": name, "type": item.get("type") if item.get("type") in ("number", "string", "bool") else "string",
                    "formula": formula, "why": str(item.get("why", ""))[:160]})
    return out[:4]
