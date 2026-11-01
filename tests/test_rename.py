"""The product used to be called 'autotracker'. Anyone who tried it keeps working after the rename."""
import json, tempfile, unittest
from pathlib import Path
from footnote import cli, config, connect
from footnote.api import Tracker
from tests.test_project import git


class FromTheOldName(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp()); git(self.d, "init", "-q", "-b", "main")

    def test_the_old_settings_folder_moves_over_with_everything_in_it(self):
        old = self.d / ".autotracker"; old.mkdir()
        (old / "config.json").write_text(json.dumps({"vault": "Tracker", "mirrors": [], "notify": {"digest": "weekly"}}), encoding="utf-8")
        (old / "last_seen.json").write_text('{"a@b.c": "2026-01-01T00:00:00+00:00"}', encoding="utf-8")
        tr = Tracker(self.d)
        self.assertFalse(old.exists()); self.assertTrue((self.d / ".footnote" / "last_seen.json").exists())
        self.assertEqual(tr.cfg["notify"]["digest"], "weekly")                          # settings survived
        tr.add_task("works"); self.assertEqual(len(Tracker(self.d).tasks()), 1)

    def test_it_never_overwrites_a_folder_that_already_exists(self):
        (self.d / ".autotracker").mkdir(); (self.d / ".autotracker" / "x").write_text("old", encoding="utf-8")
        (self.d / ".footnote").mkdir(); (self.d / ".footnote" / "y").write_text("new", encoding="utf-8")
        Tracker(self.d)
        self.assertTrue((self.d / ".autotracker" / "x").exists()); self.assertTrue((self.d / ".footnote" / "y").exists())

    def test_old_instruction_blocks_and_server_entries_are_replaced_not_duplicated(self):
        (self.d / "CLAUDE.md").write_text("# mine\n\n<!-- autotracker:start -->\nold rules about autotracker\n<!-- autotracker:end -->\n\nkeep me\n", encoding="utf-8")
        (self.d / ".mcp.json").write_text(json.dumps({"mcpServers": {"autotracker": {"command": "python", "args": ["-m", "autotracker", "mcp"]}, "other": {"command": "x"}}}), encoding="utf-8")
        connect.connect("claude", self.d)
        t = (self.d / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertNotIn("autotracker", t); self.assertIn("keep me", t); self.assertEqual(t.count("footnote:start"), 1)
        servers = json.loads((self.d / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]
        self.assertEqual(sorted(servers), ["footnote", "other"])                        # the stale entry is gone, a stranger's is untouched

    def test_old_hooks_are_removed_when_the_new_one_is_installed(self):
        (self.d / ".claude").mkdir()
        old = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "PYTHONPATH=/x python3 -m autotracker sync --quiet"}]}, {"hooks": [{"type": "command", "command": "echo mine"}]}]}}
        (self.d / ".claude" / "settings.json").write_text(json.dumps(old), encoding="utf-8")
        self.assertEqual(cli.main(["--project", str(self.d), "install-hook"]), 0)
        cmds = [h["command"] for e in json.loads((self.d / ".claude" / "settings.json").read_text(encoding="utf-8"))["hooks"]["Stop"] for h in e["hooks"]]
        self.assertEqual(len(cmds), 2); self.assertIn("echo mine", cmds); self.assertFalse(any("autotracker" in c for c in cmds))

    def test_no_trace_of_the_old_name_in_what_users_see(self):
        root = Path(__file__).resolve().parent.parent
        skip = {"test_rename.py"}
        hits = []
        for p in list(root.glob("*.md")) + list((root / "docs").rglob("*")) + list((root / "site").rglob("*")) + list((root / "footnote").rglob("*.py")) \
                + list((root / ".github").rglob("*")) + list((root / "tests").rglob("*.py")):
            if p.is_file() and p.name not in skip and p.suffix in (".md", ".html", ".css", ".js", ".py", ".yml", ".gs", ".txt", ".svg"):
                t = p.read_text(encoding="utf-8", errors="ignore")
                if "autotracker" in t.lower() and p.name not in ("connect.py", "config.py", "cli.py", "CHANGELOG.md"):
                    hits.append(p.name)
        self.assertEqual(hits, [])
