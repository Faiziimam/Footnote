"""Relationships between tasks: ONE open-ended column, `relations`, holding "type:ID" strings.

    relations: ["parent:T-001", "depends_on:T-004", "related:T-009"]

Think of it as an edge table (from, type, to). New relationship kinds (e.g. "duplicates",
"caused_by") need no schema change. Only the forward edge is stored; inverses (children,
blocks) are computed. Auto-discovery only ever ADDS edges; `unlink` records a tombstone
in `unlinked` so automation never re-adds an edge a human removed.
"""
import re

REL = re.compile(r"^([a-z_]+):(T-\d{3,})$")
KNOWN_ORDER = ["parent", "depends_on", "related"]


def parse(rel):
    m = REL.match(rel or "")
    return (m.group(1), m.group(2)) if m else None


def add(fm, rtype, target, store, why=""):
    rel = f"{rtype}:{target}"
    fm.setdefault("relations", [])
    if rel in fm["relations"] or rel in fm.get("unlinked", []) or target == fm["id"]:
        return False
    if rtype == "related":  # symmetric: skip if the reverse is expressed elsewhere by caller
        pass
    fm["relations"].append(rel)
    store.log(f"{fm['id']} +relation `{rel}`" + (f" ({why})" if why else ""))
    return True


def edges(tasks):
    """Yield (from_id, type, to_id) for every well-formed edge."""
    for tid, (fm, _) in sorted(tasks.items()):
        for r in fm.get("relations", []):
            p = parse(r)
            if p:
                yield tid, p[0], p[1]


def waiting_on(tasks):
    """{task_id: [open dependency ids]} for depends_on edges."""
    w = {}
    for src, t, dst in edges(tasks):
        if t == "depends_on" and dst in tasks and tasks[dst][0]["status"] != "done":
            w.setdefault(src, []).append(dst)
    return w


def validate(tasks, known=None):
    """Referential integrity: dangling targets, malformed values, dependency cycles."""
    problems = []
    for tid, (fm, _) in sorted(tasks.items()):
        for r in fm.get("relations", []):
            p = parse(r)
            if not p:
                problems.append(f"{tid}: malformed relation `{r}` (expected type:T-001)")
            elif p[1] not in tasks and p[1] not in (known or ()):
                problems.append(f"{tid}: `{r}` points to a task that does not exist")
    graph = {}
    for src, t, dst in edges(tasks):
        if t in ("depends_on", "parent"):
            graph.setdefault(src, set()).add(dst)
    seen, stack = set(), []

    def visit(n):
        if n in stack:
            problems.append("cycle: " + " → ".join(stack[stack.index(n):] + [n]))
            return
        if n in seen:
            return
        seen.add(n); stack.append(n)
        for m in sorted(graph.get(n, ())):
            visit(m)
        stack.pop()
    for n in sorted(graph):
        visit(n)
    return problems


def children(tasks):
    c = {}
    for src, t, dst in edges(tasks):
        if t == "parent":
            c.setdefault(dst, []).append(src)
    return c
