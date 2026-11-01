"""Plain-English updates -> actions. No AI needed (an agent can also pass explicit ids).

    "I finished the login page and started on checkout"
    "blocked on payments"          "add task: design the logo"          "reopen T-004"

Safety rule: if the match is not clearly ONE task, change nothing and suggest candidates.
"""
import re
from .signals import tokens

ADD = re.compile(r"^(?:please\s+)?(?:(?:add|create|new)\s+(?:a\s+)?(?:new\s+)?(?:task|todo|to-do|item)|"
                 r"todo|to-do|remind me to|i need to|we need to|need to)\s*[:\-]?\s*(.+)$", re.I)
REOPEN = re.compile(r"\b(reopen(?:ed)?|re-open(?:ed)?|not (?:yet )?(?:done|finished|complete[d]?)|isn'?t (?:done|finished|complete[d]?))\b", re.I)
DONE = re.compile(r"\b(finished|finishing|completed?|done with|done|shipped|wrapped up|closed|launched|delivered|"
                  r"merged|released|submitted|sent)\b", re.I)
BLOCK = re.compile(r"\b(blocked|stuck|waiting (?:on|for)|on hold|can'?t continue|cannot continue)\b", re.I)
START = re.compile(r"\b(started|starting|start|began|begun|beginning|working on|work on|picked up|kicked off|"
                   r"in progress|tackling|doing)\b", re.I)
SPLIT = re.compile(r"[.;\n]+|\s*(?:,|\band\b)\s+(?=(?:(?:i|we)(?:['\u2019](?:m|ve|re))?\s+|also\s+|am\s+|is\s+|are\s+)*(?:%s)\b)" %
                   "|".join(["finished", "completed?", "started", "begun", "began", "working on", "blocked",
                             "stuck", "shipped", "launched", "done", "add", "reopen"]), re.I)
FILLER = {"the", "a", "an", "i", "we", "have", "has", "had", "just", "now", "task", "work", "on", "with", "of",
          "my", "our", "to", "is", "are", "it", "that", "this", "also", "up", "off", "as", "for", "about",
          "been", "was", "were", "finally", "mostly", "all", "everything"}
ID = re.compile(r"\bT-\d{3,}\b", re.I)
DUE = re.compile(r"\b(?:is |are |was |will be |should be )?(?:due|deadline(?: is)?)\s*(?:on |by |for )?(.+?)\s*$", re.I)


def stem(w):
    for suf in ("ing", "ed", "es", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[: -len(suf)]
    return w


def words(s):
    return {stem(w) for w in tokens(s) if w not in FILLER}


def intent(clause):
    m = ADD.match(clause.strip())
    if m:
        return "add", m.group(1).strip(" ."), ""
    m = DUE.search(clause)
    if m:
        return "due", clause[:m.start()].strip(), m.group(1)
    for name, rx in (("reopen", REOPEN), ("blocked", BLOCK), ("done", DONE), ("active", START)):
        m = rx.search(clause)
        if m:
            return name, (clause[:m.start()] + " " + clause[m.end():]).strip(), ""
    return None, clause, ""


def best_match(phrase, tasks, prefer_open=True):
    """-> (task_id | None, [(score, id, title) candidates])"""
    pw = words(phrase)
    if not pw:
        return None, []
    scored = []
    for tid, (fm, _) in tasks.items():
        tw = words(fm["title"].replace("Implement:", ""))
        if not tw:
            continue
        inter = len(pw & tw)
        score = inter / len(tw) * 0.6 + inter / len(pw) * 0.4
        if prefer_open and fm["status"] == "done":
            score *= 0.8
        scored.append((round(score, 3), tid, fm["title"]))
    scored.sort(reverse=True)
    if scored and scored[0][0] >= 0.55 and (len(scored) == 1 or scored[0][0] - scored[1][0] >= 0.12):
        return scored[0][1], scored[:3]
    return None, [c for c in scored[:3] if c[0] >= 0.25]


def parse(text, tasks, create_missing=False):
    """-> list of {op, ...}. Unresolved clauses come back as {op:'unclear', message}."""
    actions = []
    text = re.sub(r"\s*,?\s*\bthen\b\s+", "; ", text)
    for clause in [c.strip() for c in SPLIT.split(text) if c and c.strip()]:
        kind, rest, extra = intent(clause)
        if kind is None:
            actions.append({"op": "unclear", "clause": clause,
                            "message": f"I couldn't tell what to do with “{clause}”. "
                                       "Try: “finished X”, “started X”, “blocked on X”, or “add task: X”."})
            continue
        if kind == "add":
            actions.append({"op": "add", "title": rest[:1].upper() + rest[1:], "clause": clause})
            continue
        if kind == "due":
            from . import dates
            when = dates.parse(extra)
            if not when:
                actions.append({"op": "unclear", "clause": clause, "message": f"I couldn't read the date “{extra}”. Try: tomorrow, next friday, in 3 days, dec 12, or 2026-12-01."})
                continue
            ids = [i.upper() for i in ID.findall(clause)]
            tid, cands = (ids[0], []) if ids else best_match(rest, tasks)
            if tid:
                actions.append({"op": "field", "id": tid, "field": "due", "value": when, "clause": clause})
            else:
                actions.append({"op": "unclear", "clause": clause, "message": f"I wasn't sure which task “{rest}” is. Say the task ID (e.g. T-004)."})
            continue
        status = {"done": "done", "active": "active", "blocked": "blocked", "reopen": "todo"}[kind]
        ids = [i.upper() for i in ID.findall(clause)]
        if ids:
            for i in ids:
                actions.append({"op": "status", "id": i, "status": status, "clause": clause})
            continue
        tid, cands = best_match(rest, tasks, prefer_open=(kind != "reopen"))
        if tid:
            actions.append({"op": "status", "id": tid, "status": status, "clause": clause})
        elif create_missing and not cands and status in ("done", "active", "blocked") and words(rest):
            lead = re.sub(r"^(?:(?:%s)\\b\\s*)+" % "|".join(sorted(FILLER)), "", rest.strip(" .,"), flags=re.I).strip()
            actions.append({"op": "add_status", "title": (lead[:1].upper() + lead[1:]) or rest.strip(),
                            "status": status, "clause": clause})
        else:
            hint = "; ".join(f"{i} “{t}”" for _, i, t in cands)
            actions.append({"op": "unclear", "clause": clause,
                            "message": f"I wasn't sure which task “{rest.strip() or clause}” is" +
                                       (f". Closest: {hint}. Say the task ID (e.g. {cands[0][1]}) to be exact."
                                        if cands else ". Say the task ID, or “add task: …” to create it.")})
    return actions
