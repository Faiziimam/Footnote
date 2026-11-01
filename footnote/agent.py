"""Optional LLM agent: ask Claude Code (headless) to propose a tracker from the docs.

Falls back silently (returns None) if the `claude` CLI is missing or output is bad,
so the heuristic scanner in scan.py always works.
"""
import json
import shutil
import subprocess  # nosec B404
from .scan import md_files, make_key

PROMPT = """You are bootstrapping a project tracker. Read the documents below and
return ONLY a JSON array of tasks: [{"epic": str, "title": str, "status": "todo"}].
Group tasks into epics (components/milestones). 5-40 tasks. No prose.

"""


def propose(project, vault, limit_chars=30000):
    if not shutil.which("claude"):
        return None
    docs, used = [], 0
    for p in md_files(project, vault):
        t = p.read_text(errors="ignore", encoding="utf-8")[:6000]
        used += len(t)
        if used > limit_chars:
            break
        docs.append(f"### FILE {p.relative_to(project)}\n{t}")
    try:
        r = subprocess.run(["claude", "-p", PROMPT + "\n\n".join(docs)],  # nosec B603 B607
                           capture_output=True, text=True, timeout=180, encoding="utf-8", errors="replace")
        txt = r.stdout[r.stdout.find("["): r.stdout.rfind("]") + 1]
        items = json.loads(txt)
        out = []
        for it in items:
            out.append({"epic": str(it["epic"]), "title": str(it["title"]),
                        "status": "todo", "source": "agent",
                        "key": make_key(it["epic"], it["title"])})
        return out or None
    except Exception:
        return None
