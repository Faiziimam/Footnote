"""A review/presentation deck (.pptx) built from the project report. Pure standard library: the file is written by hand
(a .pptx is a zip of XML), so there is nothing to install and nothing to compromise.

Slides: title -> at a glance (big progress number + tiles) -> what's built (progress bars per area) -> figures (tiles)
-> schedule / decisions / risks / technical / team / handover checklist, split automatically so text never overflows."""
import datetime as dt
import math
import re
import time
import zipfile
from io import BytesIO
from html import escape        # escapes & < > and quotes: valid for XML text and attributes
from . import metrics as M
from .store import LABELS

W, H = 12192000, 6858000
IN = 914400
INK, MUTE, ACC, OK, WARN, BG, CARD, LINE, DARK = "1D1D1B", "6B6B66", "3B5BDB", "2F9E44", "E8590C", "F6F6F4", "FFFFFF", "E3E3DE", "14172B"
NS = ('xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
      'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"')
BAD_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f￾￿\ud800-\udfff]")
EMOJI = re.compile("[\U0001F000-\U0001FFFF☀-⛿✀-➿️‍]")
LINK = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
GROUP = ('<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>'
         '<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>')


def e(inches):
    return int(inches * IN)


def clean(s):
    s = BAD_XML.sub("", str(s))
    return s


def esc(s):
    return escape(clean(s))


def plain(s):
    s = LINK.sub(lambda m: m.group(2) or m.group(1), s)
    s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"`([^`]+)`", r"\1", s)
    s = re.sub(r"(?<![\w*])_([^_]+)_(?![\w*])", r"\1", s)
    return s


class Slide:
    def __init__(self, bg=CARD):
        self.shapes, self.n, self.bg = [], 1, bg

    def _id(self):
        self.n += 1
        return self.n

    def shape(self, x, y, w, h, fill=None, line=None, geom="rect", radius=None, paras=None, anchor="t", inset=0.08, txbox=False):
        i = self._id()
        av = f'<a:avLst><a:gd name="adj" fmla="val {radius}"/></a:avLst>' if (geom == "roundRect" and radius) else "<a:avLst/>"
        fill_x = f'<a:solidFill><a:srgbClr val="{fill}"/></a:solidFill>' if fill else "<a:noFill/>"
        ln_x = f'<a:ln w="12700"><a:solidFill><a:srgbClr val="{line}"/></a:solidFill></a:ln>' if line else "<a:ln><a:noFill/></a:ln>"
        body, txb = "", ' txBox="1"' if txbox else ""
        if paras is not None:
            ins = e(inset)
            body = (f'<p:txBody><a:bodyPr wrap="square" lIns="{ins}" tIns="{ins // 2}" rIns="{ins}" bIns="{ins // 2}" anchor="{anchor}"><a:noAutofit/></a:bodyPr>'
                    f'<a:lstStyle/>{"".join(paras)}</p:txBody>')
        self.shapes.append(f'<p:sp><p:nvSpPr><p:cNvPr id="{i}" name="Shape {i}"/><p:cNvSpPr{txb}/><p:nvPr/></p:nvSpPr>'
                           f'<p:spPr><a:xfrm><a:off x="{e(x)}" y="{e(y)}"/><a:ext cx="{max(e(w), 0)}" cy="{max(e(h), 0)}"/></a:xfrm>'
                           f'<a:prstGeom prst="{geom}">{av}</a:prstGeom>{fill_x}{ln_x}</p:spPr>{body}</p:sp>')

    def text(self, x, y, w, h, paras, anchor="t"):
        self.shape(x, y, w, h, paras=paras, anchor=anchor, txbox=True)

    def xml(self):
        return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<p:sld {NS}><p:cSld><p:bg><p:bgPr><a:solidFill><a:srgbClr val="{self.bg}"/></a:solidFill>'
                f'<a:effectLst/></p:bgPr></p:bg><p:spTree>{GROUP}{"".join(self.shapes)}</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>')


def run(text, size=18, color=INK, bold=False):
    return (f'<a:r><a:rPr lang="en-US" sz="{int(size * 100)}" b="{1 if bold else 0}" dirty="0"><a:solidFill><a:srgbClr val="{color}"/></a:solidFill>'
            f'<a:latin typeface="Calibri"/><a:cs typeface="Calibri"/></a:rPr><a:t>{esc(text)}</a:t></a:r>')


def para(runs, align="l", bullet=False, level=0, after=6, size=18):
    marl = 285750 + level * 285750
    ppr = (f'<a:pPr marL="{marl}" indent="-285750" algn="{align}"><a:spcAft><a:spcPts val="{after * 100}"/></a:spcAft><a:buFont typeface="Arial"/><a:buChar char="&#8226;"/></a:pPr>'
           if bullet else f'<a:pPr algn="{align}"><a:spcAft><a:spcPts val="{after * 100}"/></a:spcAft><a:buNone/></a:pPr>')
    return f'<a:p>{ppr}{"".join(runs)}<a:endParaRPr lang="en-US" sz="{int(size * 100)}" dirty="0"/></a:p>'


def rich(line, size=18, color=INK):
    """'**Progress:** 40% done' -> bold + normal runs; ✅ / ⚠ become green ✓ / orange !"""
    line = EMOJI.sub("", plain(line)) if not line.lstrip().startswith(("✅", "⚠")) else line
    runs = []
    m = re.match(r"^\s*(✅|⚠️?|✔)\s*(.*)$", line)
    if m:
        ok = m.group(1) in ("✅", "✔")
        runs.append(run("✓ " if ok else "! ", size, OK if ok else WARN, True))
        line = EMOJI.sub("", m.group(2))
    for i, part in enumerate(re.split(r"\*\*", line)):
        if part:
            runs.append(run(part, size, color, bold=bool(i % 2)))
    return runs or [run(" ", size)]


def title_bar(s, title, n, name):
    s.shape(0, 0, 13.333, 0.12, fill=ACC)
    s.text(0.6, 0.35, 12.1, 0.9, [para([run(title, 30, INK, True)], size=30)], anchor="ctr")
    s.text(0.6, 7.0, 9, 0.35, [para([run(name, 11, MUTE)], size=11)])
    s.text(11.7, 7.0, 1.1, 0.35, [para([run(str(n), 11, MUTE)], align="r", size=11)])


def bullet_slides(title, lines, name, start_n, capacity=11):
    """Split lines over as many slides as needed; each wrapped line costs one row."""
    pages, cur, used = [], [], 0
    for ln in lines:
        text = plain(ln)
        cost = max(1, math.ceil(len(text) / (88 if not ln.startswith("  ") else 80)))
        if cur and used + cost > capacity:
            pages.append(cur); cur, used = [], 0
        cur.append(ln); used += cost
    if cur:
        pages.append(cur)
    out = []
    for i, page in enumerate(pages or [[]]):
        s = Slide()
        title_bar(s, title + (f" ({i + 1}/{len(pages)})" if len(pages) > 1 else ""), start_n + i, name)
        paras = []
        for ln in page:
            lvl = 1 if ln.startswith("  ") else 0
            t = ln.strip()
            isb = t.startswith("- ")
            t = t[2:] if isb else t
            paras.append(para(rich(t, 18 if lvl == 0 else 16), bullet=isb or lvl > 0, level=lvl, size=18 if lvl == 0 else 16))
        s.text(0.6, 1.45, 12.1, 5.4, paras or [para([run("Nothing to show yet.", 18, MUTE)])])
        out.append(s)
    return out


def sections(md):
    """Report markdown -> [(title, [lines])]"""
    out, cur = [], None
    for ln in md.splitlines():
        if ln.startswith("## "):
            cur = (re.sub(r"\s+_\(.*?\)_\s*$", "", ln[3:].strip()), [])
            out.append(cur)
        elif cur is not None and ln.strip():
            cur[1].append(ln.rstrip())
    return out


def build(info, tasks, mets, report_md, audience="all", today=None):
    today = today or dt.date.today()
    name = info["name"]
    fms = [fm for fm, _ in tasks.values()]
    total, done = len(fms), sum(1 for f in fms if f["status"] == "done")
    pct = round(100 * done / total) if total else 0
    slides, n = [], 1

    # ---- title
    s = Slide(DARK)
    s.shape(0.7, 2.55, 0.9, 0.08, fill=ACC)
    s.text(0.7, 2.7, 11.5, 1.6, [para([run(name, 48, "FFFFFF", True)], size=48)], anchor="t")
    sub = f"{info['kind'].title()}" + (f"  ·  {info['goal']}" if info.get("goal") else "")
    s.text(0.7, 4.25, 11.5, 0.9, [para([run(sub, 22, "C9CCE0")], size=22)])
    aud = {"all": "Full review", "manager": "For founders & managers", "founder": "For founders & managers", "everyone": "For everyone", "developer": "For developers"}.get(audience, "Review")
    s.text(0.7, 6.55, 12, 0.45, [para([run(f"{aud}  ·  {today.strftime('%d %B %Y')}  ·  generated by Footnote", 13, "9AA0C0")], size=13)])
    slides.append(s)

    secs = [(t, [l for l in ls if not l.startswith("- Full detail")]) for t, ls in sections(report_md)]   # those point to notes pages
    byt = dict(secs)
    dec, risk = byt.get("Decisions, learnings & milestones"), byt.get("Open risks & issues")
    merged = bool(dec and risk and len(dec) <= 5 and len(risk) <= 5)
    for title, lines in secs:
        if merged and title == "Open risks & issues":
            continue
        n += 1
        if merged and title == "Decisions, learnings & milestones":
            s = Slide()
            title_bar(s, "Decisions & risks", n, name)
            for i, (head, col, items) in enumerate((("Decisions, learnings & milestones", ACC, dec), ("Open risks & issues", WARN, risk))):
                x = 0.6 + i * 6.15
                s.shape(x, 1.5, 5.95, 5.1, fill=BG, geom="roundRect", radius=4000)
                s.shape(x, 1.5, 0.12, 5.1, fill=col)
                s.text(x + 0.3, 1.65, 5.5, 0.5, [para([run(head, 16, col, True)], size=16)])
                s.text(x + 0.3, 2.25, 5.5, 4.2, [para(rich(t[2:] if t.startswith("- ") else t, 16), bullet=True, size=16, after=9) for t in items])
            slides.append(s)
            continue
        if title == "At a glance":
            s = Slide()
            title_bar(s, "Where we are", n, name)
            s.text(0.6, 1.45, 4.6, 1.5, [para([run(f"{pct}%", 80, ACC, True)], size=80)], anchor="ctr")
            s.text(0.65, 2.85, 4.5, 0.5, [para([run(f"{done} of {total} tasks done", 18, MUTE)], size=18)])
            s.shape(5.4, 1.95, 7.3, 0.34, fill=LINE, geom="roundRect", radius=50000)
            if pct:
                s.shape(5.4, 1.95, 7.3 * pct / 100, 0.34, fill=ACC, geom="roundRect", radius=50000)
            for i, (st, col) in enumerate((("done", OK), ("active", ACC), ("blocked", WARN), ("todo", MUTE))):
                x = 5.4 + i * 1.85
                cnt = sum(1 for f in fms if f["status"] == st)
                s.shape(x, 2.55, 1.7, 1.0, fill=BG, geom="roundRect", radius=12000,
                        paras=[para([run(str(cnt), 28, col, True)], align="ctr", after=0, size=28), para([run(LABELS[st], 12, MUTE)], align="ctr", after=0, size=12)], anchor="ctr")
            rest = [l for l in lines if not l.startswith("**Progress:**")]
            s.text(0.6, 3.95, 12.1, 3.0, [para(rich(l.replace("- ", "", 1) if l.startswith("- ") else l, 20), size=20, after=11) for l in rest[:6]])
            slides.append(s)
        elif title == "What has been built":
            epics = {}
            for f in fms:
                epics.setdefault(f["epic"], []).append(f)
            rows = sorted(epics.items(), key=lambda kv: (-len(kv[1]), kv[0]))
            s = Slide()
            title_bar(s, "What has been built", n, name)
            for i, (ep, fs) in enumerate(rows[:8]):
                y = 1.5 + i * 0.64
                d = sum(1 for f in fs if f["status"] == "done")
                s.text(0.6, y, 3.9, 0.5, [para([run(ep[:34], 16, INK)], size=16, after=0)], anchor="ctr")
                s.shape(4.6, y + 0.1, 6.8, 0.3, fill=LINE, geom="roundRect", radius=50000)
                if d:
                    s.shape(4.6, y + 0.1, 6.8 * d / len(fs), 0.3, fill=OK if d == len(fs) else ACC, geom="roundRect", radius=50000)
                s.text(11.5, y, 1.3, 0.5, [para([run(f"{d}/{len(fs)}", 16, MUTE, True)], align="r", size=16, after=0)], anchor="ctr")
            if len(rows) > 8:
                s.text(0.6, 6.62, 12, 0.35, [para([run(f"+ {len(rows) - 8} more areas", 12, MUTE)], size=12)])
            slides.append(s)
        elif title == "Business figures" and mets:
            s = Slide()
            title_bar(s, "Business figures", n, name)
            shown = sorted(mets.items(), key=lambda kv: -abs(kv[1]["latest"]))[:6]
            for i, (nm, m) in enumerate(shown):
                x, y = 0.6 + (i % 3) * 4.1, 1.5 + (i // 3) * 2.15
                val = f"{M.fmt(m['latest'])}{(' ' + m['unit']) if m['unit'] else ''}"
                sub = ("last 30 days" if m["kind"] == "sum" else "latest")
                if m["kind"] == "sum" and m["prev7"]:
                    ch = (m["last7"] - m["prev7"]) / m["prev7"] * 100
                    sub += f"  ·  week {'+' if ch >= 0 else ''}{ch:.0f}%"
                s.shape(x, y, 3.9, 1.95, fill=BG, geom="roundRect", radius=8000,
                        paras=[para([run(nm.replace("_", " ").title(), 14, MUTE)], size=14, after=2), para([run(val, 34, INK, True)], size=34, after=2),
                               para([run(sub, 12, MUTE)], size=12, after=0)], anchor="ctr", inset=0.2)
            extra = [l for l in lines if "not connected" not in l and l.startswith("- **") and not any(f"**{nm.replace('_', ' ').title()}:**" in l for nm in mets)]
            if extra:
                rows_used = (min(len(shown), 6) + 2) // 3
                s.text(0.6, 1.55 + rows_used * 2.15, 12.1, 1.4, [para(rich(l[2:], 18), size=18, after=8) for l in extra[:4]])
            slides.append(s)
        else:
            pages = bullet_slides(title, lines, name, n)
            slides += pages
            n += len(pages) - 1
    return package(slides, f"{name} — project review")


# ------------------------------------------------------------------ the .pptx package
THEME = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="Footnote">'
         '<a:themeElements><a:clrScheme name="Footnote"><a:dk1><a:sysClr val="windowText" lastClr="000000"/></a:dk1><a:lt1><a:sysClr val="window" lastClr="FFFFFF"/></a:lt1>'
         '<a:dk2><a:srgbClr val="14172B"/></a:dk2><a:lt2><a:srgbClr val="F6F6F4"/></a:lt2><a:accent1><a:srgbClr val="3B5BDB"/></a:accent1><a:accent2><a:srgbClr val="2F9E44"/></a:accent2>'
         '<a:accent3><a:srgbClr val="E8590C"/></a:accent3><a:accent4><a:srgbClr val="6B6B66"/></a:accent4><a:accent5><a:srgbClr val="7C93FF"/></a:accent5><a:accent6><a:srgbClr val="1D1D1B"/></a:accent6>'
         '<a:hlink><a:srgbClr val="3B5BDB"/></a:hlink><a:folHlink><a:srgbClr val="6B6B66"/></a:folHlink></a:clrScheme>'
         '<a:fontScheme name="Footnote"><a:majorFont><a:latin typeface="Calibri"/><a:ea typeface=""/><a:cs typeface=""/></a:majorFont><a:minorFont><a:latin typeface="Calibri"/><a:ea typeface=""/><a:cs typeface=""/></a:minorFont></a:fontScheme>'
         '<a:fmtScheme name="Footnote"><a:fillStyleLst>' + '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>' * 3 + '</a:fillStyleLst><a:lnStyleLst>'
         + "".join(f'<a:ln w="{w}"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>' for w in (9525, 25400, 38100)) +
         '</a:lnStyleLst><a:effectStyleLst>' + "<a:effectStyle><a:effectLst/></a:effectStyle>" * 3 + '</a:effectStyleLst><a:bgFillStyleLst>' + '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>' * 3 +
         '</a:bgFillStyleLst></a:fmtScheme></a:themeElements></a:theme>')
MASTER = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<p:sldMaster {NS}><p:cSld><p:bg><p:bgPr><a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill><a:effectLst/></p:bgPr></p:bg>'
          f'<p:spTree>{GROUP}</p:spTree></p:cSld><p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" '
          'accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/><p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>'
          '<p:txStyles><p:titleStyle><a:lvl1pPr algn="l"><a:defRPr sz="3000" b="1"/></a:lvl1pPr></p:titleStyle><p:bodyStyle><a:lvl1pPr marL="0" indent="0"><a:defRPr sz="1800"/></a:lvl1pPr></p:bodyStyle>'
          '<p:otherStyle><a:lvl1pPr><a:defRPr sz="1800"/></a:lvl1pPr></p:otherStyle></p:txStyles></p:sldMaster>')
LAYOUT = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<p:sldLayout {NS} type="blank" preserve="1"><p:cSld name="Blank"><p:spTree>{GROUP}</p:spTree></p:cSld>'
          '<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>')
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"


def rels(items):
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="%s">' % PKG
            + "".join(f'<Relationship Id="{i}" Type="{t}" Target="{tg}"/>' for i, t, tg in items) + "</Relationships>")


def package(slides, title):
    n = len(slides)
    ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
          '<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>'
          '<Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>'
          '<Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>'
          '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
          + "".join(f'<Override PartName="/ppt/slides/slide{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>' for i in range(1, n + 1)) + "</Types>")
    pres = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<p:presentation {NS}><p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst><p:sldIdLst>'
            + "".join(f'<p:sldId id="{255 + i}" r:id="rId{i + 1}"/>' for i in range(1, n + 1)) +
            '</p:sldIdLst><p:sldSz cx="12192000" cy="6858000"/><p:notesSz cx="6858000" cy="9144000"/></p:presentation>')
    core = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            f'<dc:title>{esc(title)}</dc:title><dc:creator>Footnote</dc:creator></cp:coreProperties>')
    parts = {
        "[Content_Types].xml": ct,
        "_rels/.rels": rels([("rId1", f"{REL}/officeDocument", "ppt/presentation.xml"),
                             ("rId2", "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties", "docProps/core.xml")]),
        "docProps/core.xml": core, "ppt/presentation.xml": pres,
        "ppt/_rels/presentation.xml.rels": rels([("rId1", f"{REL}/slideMaster", "slideMasters/slideMaster1.xml")] +
                                                [(f"rId{i + 1}", f"{REL}/slide", f"slides/slide{i}.xml") for i in range(1, n + 1)] +
                                                [(f"rId{n + 2}", f"{REL}/theme", "theme/theme1.xml")]),
        "ppt/slideMasters/slideMaster1.xml": MASTER,
        "ppt/slideMasters/_rels/slideMaster1.xml.rels": rels([("rId1", f"{REL}/slideLayout", "../slideLayouts/slideLayout1.xml"), ("rId2", f"{REL}/theme", "../theme/theme1.xml")]),
        "ppt/slideLayouts/slideLayout1.xml": LAYOUT,
        "ppt/slideLayouts/_rels/slideLayout1.xml.rels": rels([("rId1", f"{REL}/slideMaster", "../slideMasters/slideMaster1.xml")]),
        "ppt/theme/theme1.xml": THEME,
    }
    for i, s in enumerate(slides, 1):
        parts[f"ppt/slides/slide{i}.xml"] = s.xml()
        parts[f"ppt/slides/_rels/slide{i}.xml.rels"] = rels([("rId1", f"{REL}/slideLayout", "../slideLayouts/slideLayout1.xml")])
    buf = BytesIO()
    stamp = time.gmtime(1577836800)[:6]
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name in ["[Content_Types].xml"] + sorted(k for k in parts if k != "[Content_Types].xml"):
            info = zipfile.ZipInfo(name, stamp)
            info.compress_type, info.external_attr = zipfile.ZIP_DEFLATED, 0o644 << 16
            z.writestr(info, parts[name])
    return buf.getvalue()
