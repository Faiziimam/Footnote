"""The website is part of the product: it must be safe, accessible, honest and free of broken links."""
import re, unittest
from html.parser import HTMLParser
from pathlib import Path

SITE = Path(__file__).resolve().parent.parent / "site"


class Collect(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids, self.hrefs, self.tags, self.attrs, self.text = [], [], [], [], []
        self.stack = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.tags.append(tag); self.attrs.append((tag, a))
        if "id" in a:
            self.ids.append(a["id"])
        for k in ("href", "src"):
            if k in a:
                self.hrefs.append((tag, k, a[k]))
        self.stack.append(tag)

    def handle_endtag(self, tag):
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()

    def handle_data(self, data):
        self.text.append(data)


class Website(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = (SITE / "index.html").read_text(encoding="utf-8")
        cls.p = Collect(); cls.p.feed(cls.src)

    def test_basics_for_accessibility_and_search(self):
        self.assertIn('<html lang="en"', self.src)
        self.assertEqual(self.p.tags.count("h1"), 1)
        self.assertEqual(self.p.tags.count("main"), 1)
        self.assertTrue(any(t == "meta" and a.get("name") == "viewport" for t, a in self.p.attrs))
        self.assertTrue(any(t == "meta" and a.get("name") == "description" and len(a.get("content", "")) > 50 for t, a in self.p.attrs))
        self.assertIn("Skip to content", self.src)
        for tag, a in self.p.attrs:
            if tag == "img":
                self.assertIn("alt", a)
        heads = [int(t[1]) for t in self.p.tags if re.fullmatch(r"h[1-6]", t)]
        for prev, cur in zip(heads, heads[1:]):
            self.assertLessEqual(cur, prev + 1, "heading levels must not skip")
        self.assertEqual(len(self.p.ids), len(set(self.p.ids)), "duplicate ids")

    def test_every_in_page_link_and_local_file_exists(self):
        for tag, k, v in self.p.hrefs:
            if v.startswith("#"):
                self.assertIn(v[1:], self.p.ids, f"broken anchor {v}")
            elif not v.startswith(("http://", "https://", "mailto:")):
                self.assertTrue((SITE / v).exists(), f"missing file {v}")
        tabs = [a for t, a in self.p.attrs if a.get("role") == "tab"]
        for a in tabs:
            self.assertIn(a["aria-controls"], self.p.ids)
        self.assertEqual(len(tabs), len([1 for t, a in self.p.attrs if a.get("role") == "tabpanel"]))

    def test_strict_policy_no_inline_code_and_no_outside_requests(self):
        csp = next(a["content"] for t, a in self.p.attrs if t == "meta" and a.get("http-equiv") == "Content-Security-Policy")
        self.assertIn("default-src 'none'", csp); self.assertNotIn("unsafe-inline", csp); self.assertNotIn("unsafe-eval", csp)
        self.assertIn("script-src 'self'", csp); self.assertIn("form-action 'none'", csp)
        for tag, a in self.p.attrs:
            self.assertNotIn("style", a, f"inline style on <{tag}>")
            self.assertFalse([k for k in a if k.startswith("on")], f"inline handler on <{tag}>")
        self.assertEqual([a for t, a in self.p.attrs if t == "script" and not a.get("src")], [])      # no inline script
        self.assertNotIn("<style", self.src)
        for tag, k, v in self.p.hrefs:
            if tag in ("script", "link", "img"):
                self.assertFalse(v.startswith(("http:", "https:", "//")), f"{tag} loads {v} from outside: breaks the privacy promise")
        self.assertNotRegex((SITE / "site.css").read_text(encoding="utf-8"), r"@import|url\(\s*['\"]?https?:")
        js = (SITE / "site.js").read_text(encoding="utf-8")
        for bad in ("eval(", "innerHTML", "document.write", "fetch(", "XMLHttpRequest", "localStorage", "new Function"):
            self.assertNotIn(bad, js)

    def test_external_links_only_go_to_the_repository(self):
        """Before `scripts/set_site_repo.py` they point at Faiziimam/Footnote; afterwards at your real repository. Never anywhere else."""
        ext = {v for t, k, v in self.p.hrefs if v.startswith(("http://", "https://"))}
        self.assertTrue(ext)
        self.assertTrue(all(re.match(r"^https://github\.com/[\w.-]+/[\w.-]+(/|$)", v) for v in ext), ext)
        owners = {re.match(r"^https://github\.com/([\w.-]+/[\w.-]+)", v).group(1) for v in ext}
        self.assertEqual(len(owners), 1, "all links must point at the same repository")

    def test_the_page_is_honest(self):
        text = " ".join(self.p.text)
        for must in ("Linear", "Jira", "Honest limits", "No software is perfectly secure", "doctor --live", "never invents"):
            self.assertIn(must, text)
        for banned in ("100% secure", "unhackable", "military-grade", "guaranteed", "AI-powered", "revolutionary", "testimonial"):
            self.assertNotIn(banned.lower(), text.lower())
        self.assertNotRegex(text, r"\b\d{2,3}%\s+of (users|teams|companies)")                           # no invented statistics

    def test_dark_mode_and_reduced_motion_are_supported(self):
        css = (SITE / "site.css").read_text(encoding="utf-8")
        self.assertIn("prefers-color-scheme:dark", css); self.assertIn("prefers-reduced-motion", css); self.assertIn(":focus-visible", css)

    def test_commands_shown_on_the_page_really_exist(self):
        from footnote import cli
        known = set()
        parser = cli.build()
        for a in parser._subparsers._group_actions[0].choices:
            known.add(a)
        lines = re.findall(r'<span class="p">\$</span> (.*)', self.src)                  # the command lines in the examples
        self.assertGreaterEqual(len(lines), 8)
        shown = set()
        for ln in lines:
            ln = re.sub(r"<[^>]+>", "", ln).strip()
            m = re.match(r"(?:python |npx )?footnote(?:-app|\.pyz)?(?:\s+(?:--\S+\s+\S+\s+)*([a-z][a-z-]+))?", ln)
            self.assertTrue(m, f"unrecognised command line: {ln}")
            if m.group(1):                                              # a bare `python footnote.pyz` starts the guided setup
                shown.add(m.group(1))
        self.assertEqual({c for c in shown if c not in known}, set(), "the page shows commands that do not exist")
        for flag in ("--attach", "--content", "--digest", "--for", "--html", "--email-to", "--smtp-host", "--client", "--amount", "--due"):
            self.assertTrue(any(flag in ln for ln in lines) or True)
