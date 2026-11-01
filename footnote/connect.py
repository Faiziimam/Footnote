"""`footnote connect <tool>`: write the config files that make an AI tool use the tracker."""
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path
from .guide import RULES
from .security import shell_safe_path

TOOLS = ["claude", "cursor", "codex", "gemini", "copilot", "windsurf", "generic"]
MARK = "<!-- footnote -->"


def server_cmd(project):
    exe = shutil.which("footnote")
    pkg_parent = str(Path(__file__).resolve().parent.parent)
    if exe:
        return {"command": exe, "args": ["--project", str(project), "mcp"]}
    if zipfile.is_zipfile(pkg_parent):                 # running from the single-file installer (footnote.pyz)
        return {"command": sys.executable, "args": [pkg_parent, "--project", str(project), "mcp"]}
    return {"command": sys.executable, "args": ["-m", "footnote", "--project", str(project), "mcp"],
            "env": {"PYTHONPATH": pkg_parent}}


def hook_command(project):
    """A command that works in cmd, PowerShell, bash and zsh: no env-var prefix, only double quotes.
    A tiny launcher in .footnote/ finds the package, so it also works when we were never pip-installed."""
    project = Path(project).resolve()
    shell_safe_path(project)
    shell_safe_path(sys.executable)
    exe = shutil.which("footnote")
    if exe:
        shell_safe_path(exe)
    q = lambda x: '"%s"' % x
    if exe:
        return f"{q(exe)} --project {q(project)} sync --quiet"
    d = project / ".footnote"
    d.mkdir(exist_ok=True)
    pkg_parent = Path(__file__).resolve().parent.parent
    (d / "run.py").write_text(
        "import sys\nsys.path.insert(0, %r)\nfrom footnote.cli import main\n"
        "raise SystemExit(main(['--project', %r] + sys.argv[1:]))\n" % (str(pkg_parent), str(project)), encoding="utf-8")
    return f"{q(sys.executable)} {q(d / 'run.py')} sync --quiet"


def _json_merge(path, section, name, entry):
    path.parent.mkdir(parents=True, exist_ok=True)
    cfg = json.loads(path.read_text(encoding="utf-8")) if path.exists() and path.read_text(encoding="utf-8").strip() else {}
    servers = cfg.setdefault(section, {})
    old = servers.get("autotracker")
    if old and "autotracker" in json.dumps(old):                    # replace the pre-rename server entry, do not keep both
        del servers["autotracker"]
    servers[name] = entry
    path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    return str(path)


START, END = "<!-- footnote:start -->", "<!-- footnote:end -->"
OLD_START, OLD_END = "<!-- autotracker:start -->", "<!-- autotracker:end -->"
OLD_MARK = "<!-- autotracker -->"


def _rules_file(path, text=RULES, header=""):
    """Write the tracker rules; on re-run, replace our block in place (user's other text untouched)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    cur = path.read_text(encoding="utf-8") if path.exists() else ""
    if OLD_START in cur and OLD_END in cur:                        # written when the product was called autotracker
        a, b = cur.index(OLD_START), cur.index(OLD_END) + len(OLD_END)
        cur = cur[:a] + START + "\n" + END + cur[b:]
    elif OLD_MARK in cur:
        cur = cur.replace(OLD_MARK, MARK)
    block = f"{START}\n{text.rstrip()}\n{END}\n"
    if START in cur and END in cur:
        a, b = cur.index(START), cur.index(END) + len(END)
        new = cur[:a] + block.rstrip("\n") + cur[b:]
        verb = "updated tracker rules in"
    elif MARK in cur:                       # v1 block: marker + one heading section, no end marker
        a = cur.index(MARK)
        m = re.search(r"\n#{1,2} (?!Project tracker)", cur[a + len(MARK):])
        b = a + len(MARK) + m.start() + 1 if m else len(cur)
        new = cur[:a] + block + cur[b:]
        verb = "updated tracker rules in"
    else:
        new = cur + ("\n" if cur and not cur.endswith("\n") else "") + header + block
        verb = "wrote"
    path.write_text(new, encoding="utf-8")
    return f"{path} ({verb.replace('wrote', 'new rules')})" if verb != "wrote" else str(path)


def connect(tool, project):
    project = Path(project)
    entry = server_cmd(project)
    wrote, notes = [], []
    if tool == "claude":
        wrote.append(_json_merge(project / ".mcp.json", "mcpServers", "footnote", entry))
        wrote.append(_rules_file(project / "CLAUDE.md"))
        notes.append("Claude Code will ask you once to approve the project's MCP server. "
                     "Run `footnote install-hook` too if you want updates after every command.")
    elif tool == "cursor":
        wrote.append(_json_merge(project / ".cursor" / "mcp.json", "mcpServers", "footnote", entry))
        wrote.append(_rules_file(project / ".cursor" / "rules" / "footnote.mdc",
                                 header="---\ndescription: Keep the project tracker updated\nalwaysApply: true\n---\n"))
    elif tool == "gemini":
        wrote.append(_json_merge(project / ".gemini" / "settings.json", "mcpServers", "footnote", entry))
        wrote.append(_rules_file(project / "GEMINI.md"))
    elif tool == "copilot":
        wrote.append(_json_merge(project / ".vscode" / "mcp.json", "servers", "footnote", {"type": "stdio", **entry}))
        wrote.append(_rules_file(project / ".github" / "copilot-instructions.md"))
    elif tool == "codex":
        wrote.append(_rules_file(project / "AGENTS.md"))
        args = ", ".join(json.dumps(a) for a in entry["args"])
        notes.append("Codex keeps MCP servers in ~/.codex/config.toml. Add this:\n\n"
                     f"[mcp_servers.footnote]\ncommand = {json.dumps(entry['command'])}\nargs = [{args}]\n")
    elif tool == "windsurf":
        wrote.append(_rules_file(project / ".windsurfrules"))
        notes.append("Windsurf keeps MCP servers in ~/.codeium/windsurf/mcp_config.json. Add under \"mcpServers\":\n\n"
                     + json.dumps({"footnote": entry}, indent=2))
    elif tool == "generic":
        wrote.append(_rules_file(project / "AGENTS.md"))
        notes.append("Any tool can also use: the command `footnote say \"finished X\"`, the web address from "
                     "`footnote ui`, or a JSON line in .footnote/inbox.jsonl. See docs/agents.md.")
    else:
        raise ValueError(f"unknown tool {tool!r}; choose from {', '.join(TOOLS)}")
    return wrote, notes
