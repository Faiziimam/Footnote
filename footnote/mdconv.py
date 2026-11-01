"""Markdown -> Notion blocks / plain sheet rows. Only the small subset our generated pages use."""
import re

LINK = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")


def plain(s):
    s = LINK.sub(lambda m: m.group(2) or m.group(1), s)
    return re.sub(r"[*_`]{1,2}", "", s).strip()


def rich(text):
    text = LINK.sub(lambda m: m.group(2) or m.group(1), text)
    out = []
    for part in re.split(r"(\*\*[^*]+\*\*|`[^`]+`)", text):
        if not part:
            continue
        ann = {}
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            part, ann = part[2:-2], {"bold": True}
        elif part.startswith("`") and part.endswith("`") and len(part) > 2:
            part, ann = part[1:-1], {"code": True}
        part = part.replace("_", "") if part.startswith("_") and part.endswith("_") else part
        for i in range(0, len(part), 1900):
            piece = {"type": "text", "text": {"content": part[i:i + 1900]}}
            if ann:
                piece["annotations"] = ann
            out.append(piece)
    return out or [{"type": "text", "text": {"content": " "}}]


def blocks(md):
    out = []

    def add(kind, text):
        out.append({"object": "block", "type": kind, kind: {"rich_text": rich(text)}})
    for line in md.splitlines():
        s = line.rstrip()
        if not s.strip() or re.fullmatch(r"\|?[\s:\-|]+\|?", s):
            continue
        m = re.match(r"^(#{1,3})\s+(.*)", s)
        if m:
            add(f"heading_{len(m.group(1))}", m.group(2))
        elif s.lstrip().startswith(("- ", "* ")):
            add("bulleted_list_item", s.lstrip()[2:])
        elif re.match(r"^\s*\d+\.\s", s):
            add("numbered_list_item", re.sub(r"^\s*\d+\.\s", "", s))
        elif s.startswith("> "):
            add("quote", s[2:])
        elif s.startswith("|"):
            add("bulleted_list_item", " · ".join(c.strip() for c in s.strip("|").split("|") if c.strip()))
        else:
            add("paragraph", s.strip())
    return out


def rows(md):
    return [[plain(l)] for l in md.splitlines() if l.strip() and not re.fullmatch(r"\|?[\s:\-|]+\|?", l)] or [[" "]]
