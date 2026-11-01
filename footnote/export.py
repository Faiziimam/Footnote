"""Markdown (our generated pages) -> one self-contained HTML file: print it to PDF, email it, attach it."""
import html
import re

CSS = """:root{--bg:#fff;--ink:#1d1d1b;--mute:#6b6b66;--line:#e3e3de;--soft:#f6f6f4;--accent:#3b5bdb}
@media(prefers-color-scheme:dark){:root{--bg:#161615;--ink:#ecece8;--mute:#9a9a94;--line:#33332f;--soft:#212120;--accent:#7c93ff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.55 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:860px;margin:0 auto;padding:32px 20px 80px}h1{font-size:28px;margin:0 0 4px}h2{font-size:20px;margin:34px 0 8px;padding-top:14px;border-top:1px solid var(--line)}
h3{font-size:16px;margin:22px 0 6px}p{margin:8px 0}ul{padding-left:22px;margin:6px 0}li{margin:3px 0}em{color:var(--mute)}
code{background:var(--soft);padding:1px 5px;border-radius:4px;font-size:.9em}pre{background:var(--soft);padding:12px;border-radius:8px;overflow:auto;font-size:13px}
table{border-collapse:collapse;width:100%;margin:10px 0;font-size:14px}th,td{border:1px solid var(--line);padding:6px 9px;text-align:left;vertical-align:top}th{background:var(--soft)}
blockquote{margin:8px 0;padding:2px 14px;border-left:3px solid var(--line);color:var(--mute)}a{color:var(--accent)}
@media print{body{background:#fff;color:#000}main{padding:0}h2{break-after:avoid}table,pre{break-inside:avoid}}"""


def inline(s):
    s = html.escape(s, quote=False)
    s = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", s)
    s = re.sub(r"\[\[([^\]]+)\]\]", r"\1", s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<![\w*])_([^_]+)_(?![\w*])", r"<em>\1</em>", s)
    s = re.sub(r"\[([^\]]+)\]\(((?:https?://|/|#)[^)\s]+)\)", r'<a href="\2">\1</a>', s)     # no javascript: links
    return s


def convert(md, title="Report"):
    out, lines, i = [], md.splitlines(), 0
    in_ul = False

    def close_ul():
        nonlocal in_ul
        if in_ul:
            out.append("</ul>")
            in_ul = False
    while i < len(lines):
        l = lines[i].rstrip()
        if l.startswith("```"):
            close_ul()
            block = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                block.append(lines[i]); i += 1
            out.append(f"<pre>{html.escape(chr(10).join(block))}</pre>")
        elif l.startswith("|"):
            close_ul()
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append(lines[i]); i += 1
            i -= 1
            cells = lambda r: [c.strip() for c in r.strip().strip("|").replace("\\|", "\x00").split("|")]
            body = [cells(r) for r in rows if not re.fullmatch(r"\|?[\s:\-|]+\|?", r)]
            if body:
                head, rest = body[0], body[1:]
                out.append("<table><thead><tr>" + "".join(f"<th>{inline(c.replace(chr(0), '|'))}</th>" for c in head) + "</tr></thead><tbody>")
                out += ["<tr>" + "".join(f"<td>{inline(c.replace(chr(0), '|'))}</td>" for c in r) + "</tr>" for r in rest]
                out.append("</tbody></table>")
        elif re.match(r"^#{1,3}\s", l):
            close_ul()
            n = len(l) - len(l.lstrip("#"))
            out.append(f"<h{n}>{inline(l[n:].strip())}</h{n}>")
        elif re.match(r"^\s*[-*]\s", l):
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            item = re.sub(r"^\s*[-*]\s", "", l)
            out.append(f"<li>{inline(item)}</li>")
        elif l.startswith("> "):
            close_ul(); out.append(f"<blockquote>{inline(l[2:])}</blockquote>")
        elif l.strip():
            close_ul(); out.append(f"<p>{inline(l.strip())}</p>")
        else:
            close_ul()
        i += 1
    close_ul()
    return (f"<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>{html.escape(title)}</title><style>{CSS}</style></head><body><main>\n" + "\n".join(out) + "\n</main></body></html>")
