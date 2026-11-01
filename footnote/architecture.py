"""Discover what is being built, from the files themselves. Re-run on every sync, so it can never go stale.

Works for any code project (JS/TS, Python, Ruby, PHP, Go, static HTML...) by reading manifests, folder
layout and well-known route/model patterns. For non-code projects it simply reports little, which is fine.
Never reads secrets: only .env.example-style files, and only variable NAMES.
"""
import json
import re
from pathlib import Path
from .store import now, iso

SKIP = {".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build", ".next", ".nuxt", "target",
        ".footnote", ".obsidian", "vendor", ".cache", "coverage", ".idea", ".vscode", ".claude", "Pods"}
CODE_EXT = {".js", ".jsx", ".ts", ".tsx", ".py", ".rb", ".php", ".go", ".rs", ".java", ".kt", ".swift", ".vue",
            ".svelte", ".astro", ".html", ".css", ".scss", ".dart", ".cs"}
KNOWN = {  # dependency name -> (friendly name, category)
    "next": ("Next.js", "framework"), "react": ("React", "framework"), "vue": ("Vue", "framework"),
    "nuxt": ("Nuxt", "framework"), "svelte": ("Svelte", "framework"), "astro": ("Astro", "framework"),
    "@angular/core": ("Angular", "framework"), "gatsby": ("Gatsby", "framework"), "vite": ("Vite", "tooling"),
    "tailwindcss": ("Tailwind CSS", "styling"), "bootstrap": ("Bootstrap", "styling"), "framer-motion": ("Framer Motion", "styling"),
    "express": ("Express", "backend"), "fastify": ("Fastify", "backend"), "koa": ("Koa", "backend"), "nestjs": ("NestJS", "backend"),
    "@nestjs/core": ("NestJS", "backend"), "django": ("Django", "backend"), "flask": ("Flask", "backend"),
    "fastapi": ("FastAPI", "backend"), "rails": ("Ruby on Rails", "backend"), "laravel/framework": ("Laravel", "backend"),
    "prisma": ("Prisma", "database"), "@prisma/client": ("Prisma", "database"), "mongoose": ("MongoDB (Mongoose)", "database"),
    "sequelize": ("Sequelize", "database"), "typeorm": ("TypeORM", "database"), "sqlalchemy": ("SQLAlchemy", "database"),
    "pg": ("PostgreSQL", "database"), "mysql2": ("MySQL", "database"), "supabase": ("Supabase", "database"),
    "@supabase/supabase-js": ("Supabase", "database"), "firebase": ("Firebase", "database"),
    "stripe": ("Stripe payments", "service"), "@stripe/stripe-js": ("Stripe payments", "service"),
    "@shopify/shopify-api": ("Shopify", "service"), "paypal": ("PayPal", "service"), "nodemailer": ("Email (Nodemailer)", "service"),
    "@sendgrid/mail": ("SendGrid email", "service"), "resend": ("Resend email", "service"), "twilio": ("Twilio", "service"),
    "next-auth": ("NextAuth login", "service"), "@clerk/nextjs": ("Clerk login", "service"), "auth0": ("Auth0", "service"),
    "@sentry/node": ("Sentry", "service"), "@sentry/react": ("Sentry", "service"), "algoliasearch": ("Algolia search", "service"),
    "jest": ("Jest tests", "testing"), "vitest": ("Vitest", "testing"), "cypress": ("Cypress", "testing"),
    "@playwright/test": ("Playwright", "testing"), "pytest": ("pytest", "testing"), "mocha": ("Mocha", "testing"),
    "typescript": ("TypeScript", "language"),
}
ROLE = {"components": "UI components", "pages": "Pages / routes", "app": "App routes", "api": "API", "routes": "Routes",
        "public": "Static assets", "static": "Static assets", "assets": "Assets", "styles": "Styling", "css": "Styling",
        "lib": "Shared code", "utils": "Utilities", "hooks": "UI hooks", "models": "Data models", "controllers": "Controllers",
        "views": "Views / templates", "templates": "Views / templates", "tests": "Tests", "test": "Tests",
        "__tests__": "Tests", "docs": "Documentation", "scripts": "Scripts", "prisma": "Database schema",
        "migrations": "Database migrations", "services": "Business logic", "store": "State management",
        "images": "Images", "content": "Content", "data": "Data", "src": "Source", "server": "Server", "client": "Client"}


def walk(root):
    root = Path(root)
    stack = [root]
    while stack:
        d = stack.pop()
        try:
            for p in sorted(d.iterdir()):
                if p.name in SKIP or p.name.startswith(".") and p.name not in (".github", ".env.example"):
                    continue
                if p.is_dir():
                    stack.append(p)
                else:
                    yield p
        except OSError:
            continue


def _json(p):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _read(p, n=200_000):
    try:
        return p.read_text(errors="ignore", encoding="utf-8")[:n]
    except OSError:
        return ""


def route_from_next(rel, kind):
    parts = [x for x in rel.split("/")]
    parts = parts[:-1] if kind == "app" else parts[:-1] + [Path(parts[-1]).stem]
    parts = [p for p in parts if not (p.startswith("(") and p.endswith(")")) and p not in ("index",)]
    return "/" + "/".join(parts)


def scan(project, vault=None):
    root = Path(project)
    files = [p for p in walk(root) if not (vault and Path(vault).resolve() in p.resolve().parents)]
    rels = [str(p.relative_to(root)).replace("\\", "/") for p in files]
    code = [r for r in rels if Path(r).suffix in CODE_EXT]
    a = {"stack": [], "scripts": {}, "structure": [], "pages": [], "api": [], "models": [], "components": [],
         "env": [], "tooling": {}, "docs": [], "file_count": len(rels), "code_files": len(code), "languages": {}}

    # ---- dependencies -> stack
    deps, py = {}, ""
    pj = _json(root / "package.json")
    deps.update(pj.get("dependencies", {})); deps.update(pj.get("devDependencies", {}))
    a["scripts"] = pj.get("scripts", {})
    for f in ("requirements.txt", "pyproject.toml", "Pipfile", "Gemfile", "composer.json", "go.mod", "pubspec.yaml"):
        txt = _read(root / f)
        py += "\n" + txt
        if f == "composer.json":
            deps.update(_json(root / f).get("require", {}))
    for name in re.findall(r"^\s*['\"]?([A-Za-z0-9_.\-/@]+)['\"]?\s*[=<>~!;\[]?", py, re.M):
        deps.setdefault(name.lower(), "")
    seen = {}
    for d in deps:
        if d in KNOWN:
            label, cat = KNOWN[d]
            seen[label] = cat
    a["stack"] = sorted([{"name": n, "kind": c} for n, c in seen.items()], key=lambda x: (x["kind"], x["name"]))
    a["dependencies"] = len(deps)
    exts = {}
    for r in code:
        exts[Path(r).suffix] = exts.get(Path(r).suffix, 0) + 1
    a["languages"] = dict(sorted(exts.items(), key=lambda kv: -kv[1]))

    # ---- structure: top folders with role guesses
    tops = {}
    for r in rels:
        top = r.split("/")[0] if "/" in r else "(project root)"
        tops[top] = tops.get(top, 0) + 1
    a["structure"] = [{"path": k + ("/" if k != "(project root)" else ""), "files": v, "role": ROLE.get(k.lower(), "")}
                      for k, v in sorted(tops.items(), key=lambda kv: -kv[1])[:25]]

    # ---- pages, API endpoints, components, models
    pages, api, comps, models = set(), set(), set(), set()
    for r in rels:
        low = r.lower()
        base = Path(r).name
        m = re.match(r"^(?:src/)?app/(.*)/?(page|route)\.(?:js|jsx|ts|tsx)$", r) or re.match(r"^(?:src/)?app/(page|route)\.(?:js|jsx|ts|tsx)$", r)
        if m:
            path = "/" + "/".join(p for p in r.split("app/", 1)[1].split("/")[:-1] if not (p.startswith("(") and p.endswith(")")))
            (api if base.startswith("route") else pages).add(path if path != "/" else "/")
            continue
        m = re.match(r"^(?:src/)?pages/(.+)\.(?:js|jsx|ts|tsx|vue|astro|svelte|md|mdx)$", r)
        if m and not base.startswith("_"):
            route = route_from_next(r.split("pages/", 1)[1], "pages")
            (api if route.startswith("/api") else pages).add(route or "/")
            continue
        if re.match(r"^(?:src/)?routes/.+\.(?:svelte|js|ts|jsx|tsx)$", r) and ("+page" in base):
            pages.add("/" + "/".join(r.split("routes/", 1)[1].split("/")[:-1]))
        if "/" not in r and base.endswith(".html"):
            pages.add("/" + ("" if base == "index.html" else base))
        if re.search(r"(^|/)components?/", low) and Path(r).suffix in {".jsx", ".tsx", ".vue", ".svelte", ".astro", ".js", ".ts", ".html"}:
            comps.add(Path(r).stem)
        if r.endswith("schema.prisma"):
            models |= set(re.findall(r"^model\s+(\w+)\s*\{", _read(root / r), re.M))
    page_src, api_src = {}, {}
    for r in rels:                                      # remember which file defines each route (for the diagram)
        m = re.match(r"^(?:src/)?app/(.*)/?(page|route)\.(?:js|jsx|ts|tsx)$", r) or re.match(r"^(?:src/)?app/(page|route)\.(?:js|jsx|ts|tsx)$", r)
        if m:
            path = "/" + "/".join(p for p in r.split("app/", 1)[1].split("/")[:-1] if not (p.startswith("(") and p.endswith(")")))
            (api_src if Path(r).name.startswith("route") else page_src)[path or "/"] = r
        m = re.match(r"^(?:src/)?pages/(.+)\.(?:js|jsx|ts|tsx|vue|astro|svelte|md|mdx)$", r)
        if m and not Path(r).name.startswith("_"):
            route = route_from_next(r.split("pages/", 1)[1], "pages") or "/"
            (api_src if route.startswith("/api") else page_src)[route] = r
        if "/" not in r and Path(r).name.endswith(".html"):
            page_src["/" + ("" if Path(r).name == "index.html" else Path(r).name)] = r
    for r in code:
        low = r.lower()
        name = Path(r).name
        if name in ("urls.py", "routes.rb", "web.php", "api.php") or name.endswith(("Controller.java", "Controller.kt")):
            txt = _read(root / r, 60_000)
            for p in re.findall(r"\b(?:re_)?path\(\s*r?['\"]([^'\"]*)", txt) if name == "urls.py" else []:
                api.add("/" + p.lstrip("^/").rstrip("$")); api_src["/" + p.lstrip("^/").rstrip("$")] = r
            if name == "routes.rb":
                for verb, p in re.findall(r"\b(get|post|put|patch|delete)\s+['\"]([^'\"]+)", txt):
                    api.add(f"{verb.upper()} /{p.lstrip('/')}"); api_src[f"{verb.upper()} /{p.lstrip('/')}"] = r
                for res in re.findall(r"\bresources?\s+:(\w+)", txt):
                    api.add(f"/{res}"); api_src[f"/{res}"] = r
            for verb, p in re.findall(r"Route::(get|post|put|patch|delete)\(\s*['\"]([^'\"]+)", txt):
                api.add(f"{verb.upper()} /{p.lstrip('/')}"); api_src[f"{verb.upper()} /{p.lstrip('/')}"] = r
            for verb, p in re.findall(r"@(Get|Post|Put|Delete|Patch|Request)Mapping\(\s*(?:value\s*=\s*)?['\"]([^'\"]+)", txt):
                api.add(f"{verb.upper()} {p}"); api_src[f"{verb.upper()} {p}"] = r
        if Path(r).suffix in {".js", ".ts", ".py", ".rb", ".php", ".go"} and not re.search(r"node_modules|test|spec", low):
            txt = _read(root / r, 60_000)
            for verb, path in re.findall(r"\b(?:app|router|server)\.(get|post|put|delete|patch)\(\s*['\"]([^'\"]+)", txt):
                api.add(f"{verb.upper()} {path}")
            for path in re.findall(r"@(?:app|bp|router)\.(?:route|get|post|put|delete)\(\s*['\"]([^'\"]+)", txt):
                api.add(path)
            if Path(r).suffix == ".py":
                models |= set(re.findall(r"^class\s+(\w+)\((?:[\w.]*\bModel\b|db\.Model|Base)\)", txt, re.M))
            if Path(r).suffix == ".js" or Path(r).suffix == ".ts":
                models |= set(re.findall(r"mongoose\.model\(\s*['\"](\w+)", txt))
    a["pages"], a["api"], a["components"], a["models"] = sorted(pages), sorted(api), sorted(comps), sorted(models)
    a["edges"] = _edges(root, a, page_src, api_src)

    # ---- environment variable NAMES (never values), tooling, docs
    for envf in (".env.example", ".env.sample", ".env.template"):
        if (root / envf).exists():
            a["env"] = sorted(set(re.findall(r"^\s*([A-Z][A-Z0-9_]+)\s*=", _read(root / envf), re.M)))
    t = {}
    t["tests"] = any(re.search(r"(^|/)(tests?|__tests__|spec)/|\.(test|spec)\.", r) for r in rels)
    t["ci"] = any(r.startswith(".github/workflows/") or r in (".gitlab-ci.yml", ".circleci/config.yml") for r in rels)
    t["docker"] = any(Path(r).name in ("Dockerfile", "docker-compose.yml") for r in rels)
    t["deploy"] = sorted({n for n, f in (("Vercel", "vercel.json"), ("Netlify", "netlify.toml"), ("Fly.io", "fly.toml"),
                                         ("Heroku", "Procfile"), ("Render", "render.yaml"), ("GitHub Pages", "CNAME")) if f in rels})
    t["readme"] = any(Path(r).name.lower().startswith("readme") for r in rels)
    a["tooling"] = t
    a["docs"] = [r for r in rels if r.lower().endswith(".md") and r.count("/") <= 1][:20]
    return a


def _edges(root, a, page_src, api_src):
    """Real dependencies, found by reading the files: page -> API route it calls, API -> data model / service it uses."""
    edges = set()
    svc = {s["name"]: s["name"].split()[0].lower() for s in a["stack"] if s["kind"] in ("service", "database")}
    texts = {}

    def text(rel):
        if rel not in texts:
            texts[rel] = _read(root / rel, 80_000)
        return texts[rel]
    for route, f in list(page_src.items())[:60]:
        t = text(f)
        for ar in a["api"]:
            lit = ar.split(" ", 1)[-1]
            if lit.startswith("/api") and lit in t:
                edges.add((f"page:{route}", f"api:{ar}"))
        for name, kw in svc.items():
            if kw in t.lower() and kw not in ("react", "next"):
                edges.add((f"page:{route}", f"svc:{name}"))
    for route, f in list(api_src.items())[:60]:
        t = text(f)
        for m in a["models"]:
            if re.search(rf"\b{re.escape(m)}\b", t):
                edges.add((f"api:{route}", f"model:{m}"))
        for name, kw in svc.items():
            if kw in t.lower():
                edges.add((f"api:{route}", f"svc:{name}"))
    return sorted([list(e) for e in edges])


def mermaid(a):
    """A flowchart of how the pieces connect (only what the code actually shows)."""
    if not a.get("code_files") or not (a["pages"] or a["api"] or a["models"]):
        return ""
    ids, lines = {}, ["flowchart LR"]

    def nid(key):
        ids.setdefault(key, f"n{len(ids)}")
        return ids[key]

    def label(s):
        return re.sub(r'["\[\]{}<>]', "", s)[:40]
    shown = {"page": a["pages"][:10], "api": a["api"][:8], "model": a["models"][:8]}
    svcs = [s["name"] for s in a["stack"] if s["kind"] in ("service", "database")][:6]
    groups = (("Pages", "page", shown["page"]), ("API", "api", shown["api"]), ("Data", "model", shown["model"]))
    for title, kind, items in groups:
        if items:
            lines.append(f"  subgraph {title}")
            lines += [f'    {nid(f"{kind}:{i}")}["{label(i)}"]' for i in items]
            lines.append("  end")
    if svcs:
        lines.append("  subgraph Services")
        lines += [f'    {nid(f"svc:{s}")}(["{label(s)}"])' for s in svcs]
        lines.append("  end")
    n = 0
    for f, t in a.get("edges", []):
        if f in ids and t in ids:
            lines.append(f"  {ids[f]} --> {ids[t]}")
            n += 1
    if not n:                                           # no file-level links found: show the layers
        for x, y in (("Pages", "API"), ("API", "Data")):
            if any(g[0] == x for g in groups if g[2]) and any(g[0] == y for g in groups if g[2]):
                lines.append(f"  {x} --> {y}")
    return "\n".join(lines)


ADR_DIRS = ("docs/adr", "docs/decisions", "adr", "doc/adr", "decisions", "docs/architecture/decisions", "architecture/decisions")


def read_adrs(project):
    """Architecture Decision Records already in the repo -> [(file, one-line decision)]"""
    root, out = Path(project), []
    for d in ADR_DIRS:
        for p in sorted((root / d).glob("*.md")) if (root / d).is_dir() else []:
            if p.name.lower() in ("readme.md", "template.md", "index.md"):
                continue
            txt = _read(p, 20_000)
            title = re.search(r"^#\s+(?:\d+[.)]?\s*|ADR[- ]?\d+[:.]?\s*)?(.+)$", txt, re.M)
            status = re.search(r"^\s*(?:\*\*)?status(?:\*\*)?\s*[:\-]\s*(\w[\w ]*)", txt, re.I | re.M) or \
                re.search(r"^##\s*status\s*\n+\s*(\w[\w ]*)", txt, re.I | re.M)
            dec = re.search(r"^##\s*(?:decision|outcome|decision outcome)\s*\n+(.+?)(?:\n\n|\n##|\Z)", txt, re.I | re.S | re.M)
            line = (title.group(1).strip() if title else p.stem)
            if status:
                line += f" [{status.group(1).strip().lower()}]"
            if dec:
                first = re.split(r"(?<=[.!?])\s", " ".join(dec.group(1).split()))[0]
                line += f" — {first[:200]}"
            out.append((p.relative_to(root).as_posix(), line))
    return out


def diff(prev, new):
    """Human sentences describing what changed in the architecture since the last scan."""
    if not prev:
        bits = [s["name"] for s in new["stack"][:6]]
        return [f"Architecture first captured: {len(new['pages'])} pages, {len(new['api'])} API routes, "
                f"{len(new['models'])} data models" + (f"; stack: {', '.join(bits)}" if bits else "")] if new["code_files"] else []
    out = []
    ps, ns = {s["name"] for s in prev["stack"]}, {s["name"] for s in new["stack"]}
    out += [f"Added to the stack: {n}" for n in sorted(ns - ps)] + [f"Removed from the stack: {n}" for n in sorted(ps - ns)]
    for key, word in (("pages", "page"), ("api", "API route"), ("models", "data model"), ("components", "component")):
        add, rem = sorted(set(new[key]) - set(prev[key])), sorted(set(prev[key]) - set(new[key]))
        if add:
            out.append(f"New {word}{'s' if len(add) > 1 else ''}: {', '.join(add[:6])}{' …' if len(add) > 6 else ''}")
        if rem:
            out.append(f"Removed {word}{'s' if len(rem) > 1 else ''}: {', '.join(rem[:6])}")
    for k, word in (("tests", "automated tests"), ("ci", "CI pipeline"), ("docker", "Docker setup")):
        if new["tooling"].get(k) and not prev["tooling"].get(k):
            out.append(f"Added {word}")
    for d in sorted(set(new["tooling"].get("deploy", [])) - set(prev["tooling"].get("deploy", []))):
        out.append(f"Deployment configured for {d}")
    for e in sorted(set(new["env"]) - set(prev["env"]))[:5]:
        out.append(f"New environment setting needed: {e}")
    return out


def load(vault):
    try:
        return json.loads((Path(vault) / "_architecture.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save(vault, a):
    (Path(vault) / "_architecture.json").write_text(json.dumps(a, indent=1, sort_keys=True), encoding="utf-8")


def render(vault, a):
    o = ["# Architecture", "", f"_Discovered automatically from the project files — refreshed on every sync "
         f"({now().strftime('%Y-%m-%d')})._", ""]
    if not a["code_files"]:
        o += ["_No code found yet. This page fills in as soon as the project has code._"]
        (Path(vault) / "Architecture.md").write_text("\n".join(o) + "\n", encoding="utf-8")
        return
    if a["stack"]:
        o += ["## Tech stack", ""]
        for kind in sorted({s["kind"] for s in a["stack"]}):
            o.append(f"- **{kind.title()}:** " + ", ".join(s["name"] for s in a["stack"] if s["kind"] == kind))
        o.append("")
    langs = ", ".join(f"{e} ({n})" for e, n in list(a["languages"].items())[:6])
    o += [f"**Size:** {a['file_count']} files, {a['code_files']} code files — {langs}", ""]
    for key, title in (("pages", "Pages"), ("api", "API routes"), ("models", "Data models"), ("components", "Components")):
        if a[key]:
            o += [f"## {title} ({len(a[key])})", ""] + [f"- `{x}`" for x in a[key][:60]] + [""]
    mm = mermaid(a)
    if mm:
        o += ["## How it fits together", "", "_Drawn from what the code actually references._", "", "```mermaid", mm, "```", ""]
    o += ["## Folder layout", "", "| Folder | Files | Role |", "|---|---|---|"] + \
         [f"| `{s['path']}` | {s['files']} | {s['role']} |" for s in a["structure"]] + [""]
    if a["scripts"]:
        o += ["## How to run it", ""] + [f"- `{k}` → `{v}`" for k, v in list(a["scripts"].items())[:10]] + [""]
    if a["env"]:
        o += ["## Settings it needs (names only)", "", ", ".join(f"`{e}`" for e in a["env"]), ""]
    t = a["tooling"]
    o += ["## Quality & delivery", "", f"- Automated tests: {'yes' if t.get('tests') else '**none found**'}",
          f"- CI pipeline: {'yes' if t.get('ci') else 'no'}", f"- Docker: {'yes' if t.get('docker') else 'no'}",
          f"- Deployment config: {', '.join(t.get('deploy')) or '**none found**'}", ""]
    (Path(vault) / "Architecture.md").write_text("\n".join(o) + "\n", encoding="utf-8")
