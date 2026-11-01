"""Build ONE file you can hand to anyone who has Python:   python build_pyz.py   ->  dist/footnote.pyz
Run it with:  python footnote.pyz        (no pip, no install)

The build is REPRODUCIBLE: the same source always produces byte-identical output, so anyone can rebuild it and compare
the SHA-256 with the one we publish (see SECURITY.md). Every entry gets a fixed timestamp (SOURCE_DATE_EPOCH, default 2020-01-01)."""
import hashlib
import os
import sys
import time
import zipfile
from pathlib import Path

MAIN = "# -*- coding: utf-8 -*-\nimport sys\nfrom footnote.cli import main\nsys.exit(main())\n"   # keeps the exit code
here = Path(__file__).resolve().parent
out = Path(sys.argv[1]) if len(sys.argv) > 1 else here / "dist"
out.mkdir(parents=True, exist_ok=True)
epoch = int(os.environ.get("SOURCE_DATE_EPOCH", "1577836800"))
stamp = time.gmtime(max(epoch, 315532800))[:6]
target = out / "footnote.pyz"
files = sorted(p for p in (here / "footnote").rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc")
with open(target, "wb") as raw:
    raw.write(b"#!/usr/bin/env python3\n")
    with zipfile.ZipFile(raw, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        def add(name, data):
            info = zipfile.ZipInfo(name, stamp)
            info.compress_type, info.external_attr = zipfile.ZIP_DEFLATED, 0o644 << 16
            z.writestr(info, data)
        add("__main__.py", MAIN)
        for legal in ("LICENSE", "NOTICE"):                         # Apache-2.0: copies we distribute carry the licence
            add(legal, (here / legal).read_bytes())
        for p in files:
            add(p.relative_to(here).as_posix(), p.read_bytes())
target.chmod(0o755)
digest = hashlib.sha256(target.read_bytes()).hexdigest()
(out / "footnote.pyz.sha256").write_text(f"{digest}  footnote.pyz\n", encoding="utf-8")
print(f"built {target} ({target.stat().st_size // 1024} KB)\nsha256 {digest}")
