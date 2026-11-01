import subprocess, tempfile, textwrap, unittest
from pathlib import Path
from footnote import engine
from footnote.store import Store


def sh(cwd, *c):
    subprocess.run(c, cwd=cwd, check=True, capture_output=True)


class E2E(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        sh(self.d, "git", "init", "-q", "-b", "main")
        sh(self.d, "git", "config", "user.email", "t@t"); sh(self.d, "git", "config", "user.name", "t")
        (self.d / "ARCHITECTURE.md").write_text(textwrap.dedent("""\
            # Product
            ## Auth service
            ## Billing service
            """), encoding="utf-8")
        sh(self.d, "git", "add", "-A"); sh(self.d, "git", "commit", "-qm", "init")
        self.vault = self.d / "Tracker"

    def sync(self):
        return engine.sync(self.d, self.vault)

    def status(self):
        return {f["title"]: f["status"] for f, _ in Store(self.vault).load_tasks().values()}

    def test_bootstrap_from_architecture(self):
        self.sync()
        self.assertEqual(set(self.status().values()), {"todo"})
        self.assertEqual(len(self.status()), 2)
        self.assertTrue((self.vault / "Dashboard.md").exists())

    def test_idempotent(self):
        self.sync()
        changed, _ = self.sync()
        self.assertEqual(changed, 0)

    def test_commit_moves_states(self):
        self.sync()
        (self.d / "a.txt").write_text("x", encoding="utf-8"); sh(self.d, "git", "add", "-A")
        sh(self.d, "git", "commit", "-qm", "wip T-001 auth")
        self.sync()
        self.assertEqual(self.status()["Implement: Auth service"], "active")
        (self.d / "b.txt").write_text("x", encoding="utf-8"); sh(self.d, "git", "add", "-A")
        sh(self.d, "git", "commit", "-qm", "Closes T-001")
        self.sync()
        self.assertEqual(self.status()["Implement: Auth service"], "done")
        self.assertEqual(self.status()["Implement: Billing service"], "todo")

    def test_fuzzy_title_match_and_checkbox(self):
        (self.d / "TODO.md").write_text("# Sprint\n- [ ] Add billing service\n- [x] Setup CI\n", encoding="utf-8")
        self.sync()
        s = self.status()
        self.assertEqual(s["Setup CI"], "done")
        self.assertEqual(s["Add billing service"], "todo")

    def test_lock_and_new_field(self):
        self.sync()
        p = self.vault / "Tasks" / "T-001.md"
        p.write_text(p.read_text(encoding="utf-8").replace('locked: false', 'locked: true')
                     .replace("\n---\n", '\nbudget: 500\n---\n', 1), encoding="utf-8")
        (self.d / "a.txt").write_text("x", encoding="utf-8"); sh(self.d, "git", "add", "-A")
        sh(self.d, "git", "commit", "-qm", "Closes T-001")
        self.sync()
        self.assertEqual(self.status()["Implement: Auth service"], "todo")  # locked
        self.assertIn("budget", Store(self.vault).schema()["fields"])
        self.assertIn("budget", (self.vault / "Dashboard.md").read_text(encoding="utf-8"))

if __name__ == "__main__":
    unittest.main()


class Relations(E2E):
    def rel(self):
        return {f["id"]: f["relations"] for f, _ in Store(self.vault).load_tasks().values()}

    def test_nesting_and_text_refs(self):
        (self.d / "TODO.md").write_text(
            "# Plan\n- [ ] Build API\n  - [ ] Write schema\n  - [ ] Add endpoints\n"
            "- [ ] Ship docs depends on T-003\n", encoding="utf-8")
        self.sync()
        titles = {f["title"]: f for f, _ in Store(self.vault).load_tasks().values()}
        api, schema = titles["Build API"]["id"], titles["Write schema"]["id"]
        self.assertIn(f"parent:{api}", titles["Write schema"]["relations"])
        self.assertIn(f"parent:{api}", titles["Add endpoints"]["relations"])
        self.assertTrue(any(r.startswith("depends_on:T-003") for r in titles["Ship docs"]["relations"]))
        dash = (self.vault / "Dashboard.md").read_text(encoding="utf-8")
        self.assertIn("Parent roll-up", dash)
        self.assertTrue((self.vault / "Relations.md").exists())

    def test_heading_hierarchy(self):
        (self.d / "ARCHITECTURE.md").write_text("# P\n## Auth\n### Tokens\n### Sessions\n", encoding="utf-8")
        self.sync()
        r = self.rel()
        by = {f["title"]: f["id"] for f, _ in Store(self.vault).load_tasks().values()}
        self.assertEqual(r[by["Implement: Tokens"]], [f"parent:{by['Implement: Auth']}"])

    def test_commit_with_two_ids_relates(self):
        self.sync()
        (self.d / "a.txt").write_text("x", encoding="utf-8"); sh(self.d, "git", "add", "-A")
        sh(self.d, "git", "commit", "-qm", "wire T-001 into T-002")
        self.sync()
        self.assertIn("related:T-002", self.rel()["T-001"])

    def test_unlink_tombstone_and_idempotent(self):
        self.sync()
        (self.d / "a.txt").write_text("x", encoding="utf-8"); sh(self.d, "git", "add", "-A")
        sh(self.d, "git", "commit", "-qm", "wire T-001 into T-002")
        self.sync()
        from footnote import cli
        cli.main(["--project", str(self.d), "link", "T-001", "related", "T-002", "--remove"])
        self.sync()
        self.assertEqual(self.rel()["T-001"], [])
        self.assertEqual(self.sync()[0], 0)

    def test_dangling_and_cycle_flagged_not_dropped(self):
        self.sync()
        from footnote import cli
        cli.main(["--project", str(self.d), "link", "T-001", "depends_on", "T-002"])
        cli.main(["--project", str(self.d), "link", "T-002", "depends_on", "T-001"])
        p = self.vault / "Tasks" / "T-001.md"
        p.write_text(p.read_text(encoding="utf-8").replace('relations: ["depends_on:T-002"]', 'relations: ["depends_on:T-002", "caused_by:T-099"]'), encoding="utf-8")
        self.sync()
        dash = (self.vault / "Dashboard.md").read_text(encoding="utf-8")
        self.assertIn("cycle", dash); self.assertIn("does not exist", dash)
        self.assertIn("caused_by:T-099", self.rel()["T-001"])  # custom type kept

    def test_old_vault_without_relations_still_works(self):
        self.sync()
        import json
        sp = self.vault / "_schema.json"; sc = json.loads(sp.read_text(encoding="utf-8"))
        sc["fields"].pop("relations"); sc["fields"].pop("unlinked"); sp.write_text(json.dumps(sc), encoding="utf-8")
        for p in (self.vault / "Tasks").glob("T-*.md"):
            p.write_text("\n".join(l for l in p.read_text(encoding="utf-8").split("\n") if not l.startswith(("relations:", "unlinked:"))), encoding="utf-8")
        self.sync()
        self.assertIn("relations", Store(self.vault).schema()["fields"])
        self.assertEqual(self.sync()[0], 0)
