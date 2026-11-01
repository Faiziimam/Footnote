"""SQLite database: table `tasks` plus an edge table `relations(src, type, dst)` for SQL joins."""
import sqlite3
from pathlib import Path
from .base import Mirror, MirrorError
from .. import relations as rel
from ..security import sqlite_ident


class SqliteMirror(Mirror):
    type = "sqlite"

    @property
    def path(self):
        return Path(self.cfg.get("path") or self.project / "tracker.db").expanduser()

    def where(self):
        return str(self.path)

    def ping(self):
        import os
        ok = self.path.parent.exists() and os.access(self.path.parent, os.W_OK)
        return ok, f"can write {self.path}" if ok else f"cannot write to {self.path.parent}"

    def pull(self):
        if not self.path.exists():
            return []
        con = sqlite3.connect(self.path)
        try:
            con.row_factory = sqlite3.Row
            rows = [dict(r) for r in con.execute("SELECT * FROM tasks")]
            edges = {}
            for r in con.execute("SELECT src, type, dst FROM relations"):
                edges.setdefault(r["src"], []).append(f"{r['type']}:{r['dst']}")
        except sqlite3.Error:
            return []
        finally:
            con.close()
        for r in rows:
            r["relations"] = ", ".join(sorted(edges.get(r.get("id"), [])))
            for k, v in r.items():
                r[k] = "" if v is None else str(v)
        return rows

    def push(self, columns, all_rows, changed_ids):
        try:
            con = sqlite3.connect(self.path)
            with con:
                con.execute("DROP TABLE IF EXISTS tasks")
                con.execute("DROP TABLE IF EXISTS relations")
                con.execute("DROP VIEW IF EXISTS ready_tasks")
                con.execute("CREATE TABLE tasks (%s, PRIMARY KEY (id))" %  # nosec B608
                            ", ".join(f"{sqlite_ident(c)} TEXT" for c in columns))
                con.execute("CREATE TABLE relations (src TEXT, type TEXT, dst TEXT, "
                            "FOREIGN KEY (src) REFERENCES tasks(id))")
                q = ",".join("?" for _ in columns)
                con.executemany(f"INSERT INTO tasks VALUES ({q})",  # nosec B608
                                [[r.get(c, "") for c in columns] for r in all_rows])
                for r in all_rows:
                    for token in (r.get("relations") or "").split(","):
                        p = rel.parse(token.strip())
                        if p:
                            con.execute("INSERT INTO relations VALUES (?,?,?)", (r["id"], p[0], p[1]))
                con.execute("CREATE VIEW ready_tasks AS SELECT * FROM tasks "
                            "WHERE status IN ('Not started','In progress') AND (waiting_on IS NULL OR waiting_on='')")
            con.close()
        except sqlite3.Error as e:
            raise MirrorError(f"database error: {e}")
