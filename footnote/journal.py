"""The project's memory: decisions, risks, learnings, milestones, and notes, in order, forever."""
import json
from .store import now, iso
from .security import clean_text

FILE = "_journal.jsonl"
KINDS = ["decision", "risk", "learning", "milestone", "note", "issue", "architecture", "resolved"]


def add(vault, kind, text, task=None, source="agent", ts=None):
    kind = (kind or "note").strip().lower()
    if kind not in KINDS:
        kind = "note"
    text = " ".join(clean_text(text).split())
    if not text:
        return None
    entries = read(vault)
    if any(e["kind"] == kind and e["text"] == text for e in entries):   # same fact twice = once
        return None
    e = {"id": f"J-{len(entries) + 1:03d}", "ts": ts or iso(now()), "kind": kind, "text": text,
         "task": task or "", "source": source}
    (vault).mkdir(parents=True, exist_ok=True)
    with open(vault / FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(e, ensure_ascii=False) + "\n")
    return e


def read(vault):
    p = vault / FILE
    out = []
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def open_risks(entries):
    closed = {e["text"].split()[0] for e in entries if e["kind"] == "resolved"}
    return [e for e in entries if e["kind"] in ("risk", "issue") and e["id"] not in closed]


def render(vault):
    es = read(vault)
    out = ["# Journal", "", "_Decisions, risks, learnings and milestones — the project's memory. "
           "Added by you and your AI tools; never edited automatically._", ""]
    for kind, title in (("milestone", "Milestones"), ("decision", "Decisions (and why)"),
                        ("learning", "Learnings"), ("note", "Notes"), ("architecture", "Architecture changes")):
        items = [e for e in es if e["kind"] == kind]
        if items:
            out += [f"## {title}", ""] + [f"- {e['ts'][:10]} · {e['text']}" + (f" ([[{e['task']}]])" if e["task"] else "")
                                           + f" _{e['id']}_" for e in items] + [""]
    risks = open_risks(es)
    out += ["## Open risks & issues", ""] + ([f"- {e['ts'][:10]} · {e['text']} _{e['id']}_" for e in risks] or ["_none_"]) + [""]
    (vault / "Journal.md").write_text("\n".join(out), encoding="utf-8")
