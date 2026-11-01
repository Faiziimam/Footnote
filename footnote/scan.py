"""Bootstrap/refresh: derive tasks from the project's markdown files.

1. Checkbox items (`- [ ] ...`, `- [x] ...`) become tasks; the nearest heading is the epic.
2. If no checkboxes exist anywhere, architecture/design/spec docs are read and each
   H2/H3 section becomes an "Implement: <section>" task (cold-start from architecture).
Optional: an LLM agent (`claude -p`) can propose tasks instead (see agent.py).
"""
import hashlib
import re
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".obsidian"}
ARCH_NAMES = re.compile(r"(architecture|design|spec|requirements|roadmap|plan)", re.I)
README = re.compile(r"readme", re.I)
HEAD = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
BOX = re.compile(r"^\s*[-*]\s+\[([ xX~])\]\s+(.*?)\s*$")


def md_files(project, vault):
    vault = Path(vault).resolve()
    for p in sorted(Path(project).rglob("*.md")):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        rel_parts = p.relative_to(project).parts
        if any(part.startswith(".") for part in rel_parts[:-1]) or re.search(r"template", p.name, re.I):
            continue                      # hidden folders (.github...) and templates hold forms to fill in, not work to do
        if vault in p.resolve().parents:
            continue
        yield p


def make_key(epic, title):
    norm = re.sub(r"\W+", " ", f"{epic}|{title}".lower()).strip()
    return hashlib.sha1(norm.encode(), usedforsecurity=False).hexdigest()[:10]  # stable task fingerprint


TARGET = r'(?:T-\d{3,}|"[^"]+"|\u201c[^\u201d]+\u201d|\[\[[^\]]+\]\])'
PHRASE = re.compile(
    r"\s*[\(\[]?\s*\b(depends on|blocked by|requires|after|relates to|related to|see)\b\s*:?\s*"
    rf"({TARGET}(?:\s*(?:,|and)\s*{TARGET})*)\s*[\)\]]?", re.I)
ONE = re.compile(TARGET)
KIND = {"depends on": "depends_on", "blocked by": "depends_on", "requires": "depends_on", "after": "depends_on",
        "relates to": "related", "related to": "related", "see": "related"}


ATTR_DUE = re.compile(r"\s*\(?\bdue[: ]\s*([^)\s][^)]*?)\)?(?=\s*(?:$|\(|~|!|est[: ]|priority[: ]))", re.I)
ATTR_EST = re.compile(r"\s*\(?(?:~|\best[: ]\s*)(\d+(?:\.\d+)?\s*(?:d|days?|w|wks?|weeks?|h|hrs?|hours?|pts?)?)\)?", re.I)
ATTR_PRI = re.compile(r"\s*\(?(?:!|priority[: ]\s*)(urgent|high|medium|med|low|p[0-3])\b\)?", re.I)
PRI = {"urgent": "urgent", "p0": "urgent", "high": "high", "p1": "high", "medium": "medium", "med": "medium", "p2": "medium", "low": "low", "p3": "low"}


def extract_attrs(text):
    """'Launch site (due 2026-12-01) ~3d !high' -> ('Launch site', {'due': ..., 'estimate': 3, 'priority': 'high'})"""
    from . import dates
    attrs = {}
    m = ATTR_DUE.search(text)
    if m and dates.parse(m.group(1)):
        attrs["due"] = dates.parse(m.group(1))
        text = text[:m.start()] + text[m.end():]
    m = ATTR_EST.search(text)
    if m and dates.parse_estimate(m.group(1)) is not None:
        attrs["estimate"] = dates.parse_estimate(m.group(1))
        text = text[:m.start()] + text[m.end():]
    m = ATTR_PRI.search(text)
    if m:
        attrs["priority"] = PRI[m.group(1).lower()]
        text = text[:m.start()] + text[m.end():]
    return text.strip(" -:,") or text, attrs


def split_refs(text):
    """-> (clean_title, [(type, 'T-001' | 'Some title'), ...])"""
    refs = []
    for m in PHRASE.finditer(text):
        for t in ONE.findall(m.group(2)):
            ref = t.strip('"\u201c\u201d').removeprefix("[[").removesuffix("]]").strip()
            refs.append((KIND[m.group(1).lower()], ref.upper() if t.upper().startswith("T-") else ref))
    clean = PHRASE.sub("", text).strip(" -:,") or text
    return clean, refs


def scan_checkboxes(project, vault):
    found = []
    for p in md_files(project, vault):
        rel = p.relative_to(project).as_posix()
        heading = p.stem
        stack = []  # (indent, key) of enclosing checkboxes
        for line in p.read_text(errors="ignore", encoding="utf-8").splitlines():
            h = HEAD.match(line)
            if h:
                heading = h.group(2)
                stack = []
                continue
            b = BOX.match(line)
            if b:
                ex = line.expandtabs(4)
                indent = len(ex) - len(ex.lstrip())
                while stack and stack[-1][0] >= indent:
                    stack.pop()
                epic = f"{p.stem} / {heading}" if heading != p.stem else p.stem
                state = {"x": "done", "X": "done", "~": "active"}.get(b.group(1), "todo")
                body_text, attrs = extract_attrs(b.group(2))
                title, refs = split_refs(body_text)
                key = make_key(epic, title)
                found.append({"epic": epic, "title": title, "status": state,
                              "source": rel, "key": key, "legacy_key": make_key(epic, b.group(2)),
                              "parent_key": stack[-1][1] if stack else None, "refs": refs, "attrs": attrs})
                stack.append((indent, key))
    return found


def scan_architecture(project, vault, include_readme=False):
    found = []
    for p in md_files(project, vault):
        if not (ARCH_NAMES.search(p.name) or (include_readme and README.search(p.name))):
            continue
        rel = p.relative_to(project).as_posix()
        h2_key = None
        for line in p.read_text(errors="ignore", encoding="utf-8").splitlines():
            h = HEAD.match(line)
            if h and len(h.group(1)) in (2, 3):
                title = f"Implement: {h.group(2)}"
                key = make_key(p.stem, title)
                is_h3 = len(h.group(1)) == 3
                found.append({"epic": p.stem, "title": title, "status": "todo",
                              "source": rel, "key": key,
                              "parent_key": h2_key if is_h3 else None, "refs": []})
                if not is_h3:
                    h2_key = key
    return found


def scan(project, vault, cold_start=True):
    """cold_start: nothing is tracked yet, so README headings may seed a first plan; afterwards only real
    architecture/design/spec docs keep adding tasks (a README of a finished project is not a to-do list)."""
    items = scan_checkboxes(project, vault)
    if not items:
        items = scan_architecture(project, vault, include_readme=cold_start)
    for it in items:
        it.setdefault("key", make_key(it["epic"], it["title"]))
    return items
