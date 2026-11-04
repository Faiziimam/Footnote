"""Assemble the npm package in a folder:   python scripts/build_npm.py dist/npm   then   cd dist/npm && npm pack
It copies the launcher, builds the (reproducible) footnote.pyz into vendor/, and adds LICENSE and NOTICE."""
import shutil
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
out = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else root / "dist" / "npm"
if out.exists():
    # Only ever delete a folder that a previous run of this script created (never a path you mistyped).
    marker = out / "package.json"
    mine = marker.is_file() and '"name": "footnote-app"' in marker.read_text(encoding="utf-8")
    if any(out.iterdir()) and not mine:
        sys.exit(f"{out} exists and is not a Footnote npm build folder; choose an empty or new folder (nothing was deleted).")
    if root == out or root in out.parents or out in root.parents:
        sys.exit("The output folder must be separate from the project folder.")
    shutil.rmtree(out)
shutil.copytree(root / "npm", out, ignore=shutil.ignore_patterns("vendor", "node_modules", "*.tgz"))
subprocess.run([sys.executable, str(root / "build_pyz.py"), str(out / "vendor")], check=True, stdout=subprocess.DEVNULL)
for name in ("LICENSE", "NOTICE"):
    shutil.copy2(root / name, out / name)
print(f"npm package assembled in {out}\nnext:  cd {out} && npm pack")
