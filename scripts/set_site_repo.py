"""Point the website's links at a repository (use it again when you move the project):

    python scripts/set_site_repo.py OWNER/REPO        for example:  python scripts/set_site_repo.py my-org/footnote

It finds the repository the site currently links to and replaces it everywhere in site/*.html."""
import re
import sys
from pathlib import Path

NEW = sys.argv[1] if len(sys.argv) == 2 else ""
if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", NEW):
    sys.exit("usage: python scripts/set_site_repo.py OWNER/REPO   (for example: my-org/footnote)")
site = Path(__file__).resolve().parent.parent / "site"
current = {m for p in site.glob("*.html") for m in re.findall(r"https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)", p.read_text(encoding="utf-8"))}
if len(current) != 1:
    sys.exit(f"expected the site to link to exactly one repository, found: {sorted(current)}")
old = current.pop()
for p in site.glob("*.html"):
    p.write_text(p.read_text(encoding="utf-8").replace(f"github.com/{old}", f"github.com/{NEW}"), encoding="utf-8")
    print(f"updated {p.name}: {old} -> {NEW}")
