"""Excel / Numbers / any spreadsheet app: a plain CSV file you can open and edit."""
import csv
import os
from pathlib import Path
from .base import Mirror, MirrorError


class CsvMirror(Mirror):
    type = "csv"

    @property
    def path(self):
        return Path(self.cfg.get("path") or self.project / "Tracker.csv").expanduser()

    def where(self):
        return str(self.path)

    def ping(self):
        ok = self.path.parent.exists() and os.access(self.path.parent, os.W_OK)
        return ok, f"can write {self.path}" if ok else f"cannot write to {self.path.parent}"

    def pull(self):
        if not self.path.exists():
            return []
        with open(self.path, newline="", encoding="utf-8-sig") as f:
            return [{(k or "").strip().lower().replace(" ", "_"): (v or "") for k, v in r.items()}
                    for r in csv.DictReader(f)]

    def push(self, columns, all_rows, changed_ids):
        tmp = self.path.with_suffix(".csv.tmp")
        try:
            with open(tmp, "w", newline="", encoding="utf-8-sig") as f:  # BOM: Excel reads UTF-8
                w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
                w.writeheader()
                w.writerows(all_rows)
            os.replace(tmp, self.path)
        except OSError as e:
            raise MirrorError(f"cannot write {self.path} (is it open in Excel?): {e}")
