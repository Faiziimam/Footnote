"""`footnote doctor`: plain-language health check. With --live it also tests each connection (read-only)."""
import json
import os
import shutil
import subprocess  # nosec B404
import sys
import time
from pathlib import Path
from . import config, lock, log, guide, metrics
from .connect import START, END
from .store import Store
from . import mirrors as M

OK, WARN, FAIL = "ok", "warn", "fail"


def run(tr, live=False):
    out = []

    def add(level, title, detail="", fix=""):
        out.append({"level": level, "title": title, "detail": detail, "fix": fix})
    project, vault = tr.project, tr.vault

    v = sys.version_info
    add(OK if v >= (3, 9) else FAIL, f"Python {v.major}.{v.minor}", "" if v >= (3, 9) else "needs 3.9 or newer", "" if v >= (3, 9) else "install a newer Python from python.org")
    g = shutil.which("git")
    if not g:
        add(WARN, "git is not installed", "Updates from commits are unavailable; saying what you did still works.", "install git from git-scm.com")
    else:
        inside = subprocess.run(["git", "-C", str(project), "rev-parse", "--is-inside-work-tree"], capture_output=True,  # nosec B603 B607
                                text=True, encoding="utf-8", errors="replace").stdout.strip() == "true"
        add(OK if inside else WARN, "git history" if inside else "this folder is not a git repository",
            "" if inside else "No commit-based updates, team view or architecture history.", "" if inside else "run: git init")
    if config.exists(project):
        try:
            json.loads(config.path_for(project).read_text(encoding="utf-8"))
            add(OK, "settings file is valid")
        except ValueError:
            add(FAIL, "settings file is damaged", str(config.path_for(project)), "delete it and run: footnote setup")
    else:
        add(WARN, "not set up yet", "", "run: footnote setup")
    cp = config.path_for(project)
    if cp.exists():
        raw = cp.read_text(encoding="utf-8", errors="replace")
        has_secret = any(f'"{k}"' in raw for k in ("token", "secret", "password", "pull_token"))
        try:
            loose = bool(cp.stat().st_mode & 0o077) and not sys.platform.startswith("win")
        except OSError:
            loose = False
        if loose:
            add(WARN, "your settings file can be read by other users on this computer", "It may contain tokens.", f"run: chmod 600 {cp}")
        elif has_secret:
            add(OK, "tokens are saved in .footnote/config.json (readable only by you)", "Environment variables (NOTION_TOKEN, …) are safer if you can.")
    try:
        vault.mkdir(parents=True, exist_ok=True)
        t = vault / ".write-test"
        t.write_text("x", encoding="utf-8")
        t.unlink()
        add(OK, f"notes folder is writable ({vault.name}/)")
    except OSError as e:
        add(FAIL, "cannot write to the notes folder", str(e), "check folder permissions")
    try:
        with lock.locked(config.lock_path(project), 0.3):
            add(OK, "no other update is running")
    except lock.Busy:
        add(WARN, "another update is running right now", "", "wait a moment and retry")
    if (vault / "_schema.json").exists():
        try:
            json.loads((vault / "_schema.json").read_text(encoding="utf-8"))
        except ValueError:
            add(FAIL, "the tracker's data file is damaged", str(vault / "_schema.json"),
                "go back to a good state: footnote history, then footnote undo --to <id>")
            return out
        n = len(Store(vault).load_tasks())
        dash = vault / "Dashboard.md"
        ago = int((time.time() - dash.stat().st_mtime) / 60) if dash.exists() else None
        add(OK if ago is not None and ago < 60 * 24 * 3 else WARN, f"{n} tasks tracked",
            f"last refreshed {ago} min ago" if ago is not None else "", "" if ago is not None and ago < 4320 else "run: footnote sync")

    # AI tools
    tools = []
    for f, label in ((".mcp.json", "Claude Code"), (".cursor/mcp.json", "Cursor"), (".gemini/settings.json", "Gemini CLI"),
                     (".vscode/mcp.json", "Copilot (VS Code)")):
        p = project / f
        if p.exists() and "footnote" in p.read_text(encoding="utf-8", errors="replace"):
            tools.append(label)
    rules_ok = []
    for f in ("CLAUDE.md", "AGENTS.md", "GEMINI.md", ".github/copilot-instructions.md", ".cursor/rules/footnote.mdc", ".windsurfrules"):
        p = project / f
        if p.exists() and START in p.read_text(encoding="utf-8", errors="replace"):
            txt = p.read_text(encoding="utf-8", errors="replace")
            rules_ok.append((f, guide.RULES.strip() in txt))
    if tools or rules_ok:
        add(OK, "AI tools connected: " + (", ".join(tools) or "instruction files only"))
        stale = [f for f, cur in rules_ok if not cur]
        if stale:
            add(WARN, "agent instructions are out of date", ", ".join(stale), "run: footnote connect <tool>  (refreshes them)")
    else:
        add(WARN, "no AI tool is connected", "Agents will not update the tracker by themselves.", "run: footnote connect claude   (or cursor, codex, gemini…)")
    hook = project / ".claude" / "settings.json"
    if hook.exists() and "sync --quiet" in hook.read_text(encoding="utf-8", errors="replace"):
        add(OK, "Claude Code hook installed (updates after commands)")

    # connected trackers & sources
    for item in tr.cfg.get("mirrors", []):
        name = item.get("name") or item["type"]
        try:
            m = M.make(item, project, vault)
        except M.MirrorError as e:
            add(FAIL, f"{name}: {e}")
            continue
        tok_env = item.get("token_env") or {"notion": "NOTION_TOKEN", "gsheets": "GOOGLE_SHEETS_TOKEN"}.get(item["type"], "")
        if item["type"] == "notion" and not (item.get("token") or (tok_env and os.environ.get(tok_env))):
            add(FAIL, f"{name}: Notion token is missing", "", f"set {tok_env} or run: footnote add-tracker notion")
            continue
        if live:
            ok, msg = m.ping()
            add(OK if ok else FAIL, f"{name}: {msg}", "" if ok else "", "" if ok else "see docs/" + ("notion.md" if item["type"] == "notion" else "google-sheets.md"))
        else:
            add(OK, f"{name} is configured", m.where() + "   (test the connection with: footnote doctor --live)")
    for src in tr.cfg.get("sources", []):
        if live:
            try:
                add(OK, f"{src['type']}: {metrics.PINGS[src['type']](src)}")
            except M.MirrorError as e:
                add(FAIL, f"{src['type']}: {e}")
        else:
            add(OK, f"{src['type']} source is configured", "test with: footnote doctor --live")

    if tr.cfg.get("github"):
        from . import github
        if live:
            try:
                add(OK, "github: " + github.ping(tr.cfg["github"], project))
            except M.MirrorError as e:
                add(FAIL, f"github: {e}")
        else:
            add(OK, "GitHub signals are configured", "test with: footnote doctor --live")
    recent = [l for l in log.tail(project, 40) if " WARN " in l or " ERROR" in l]
    if recent:
        add(WARN, "recent problems in the log", "\n    ".join(recent[-4:]), "full log: .footnote/log.txt")
    return out


def render(items):
    icon = {OK: "✅", WARN: "⚠️ ", FAIL: "❌"}
    lines = []
    for i in items:
        lines.append(f"{icon[i['level']]} {i['title']}")
        if i["detail"]:
            lines.append(f"     {i['detail']}")
        if i["fix"]:
            lines.append(f"     → {i['fix']}")
    bad = sum(1 for i in items if i["level"] == FAIL)
    warn = sum(1 for i in items if i["level"] == WARN)
    lines.append("")
    lines.append("Everything looks good." if not bad and not warn else f"{bad} problem(s), {warn} thing(s) to look at.")
    return "\n".join(lines)
