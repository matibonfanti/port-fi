"""Build the static site (dist/) — the Python engine runs in the visitor's browser via Pyodide.

    python3 scripts/build_static.py          (stdlib only; uses the committed data snapshot)

Output: dist/index.html (+ css, js, vendor) and dist/engine.zip (port/ package, methodology, data snapshot).
Deploy dist/ to any static host: Vercel (vercel.json), GitHub Pages (.github/workflows/pages.yml), Netlify…
"""
from __future__ import annotations

import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"


def main():
    if DIST.exists():
        shutil.rmtree(DIST)
    shutil.copytree(ROOT / "web", DIST, ignore=shutil.ignore_patterns("dev", ".DS_Store"))
    idx = DIST / "index.html"
    html = idx.read_text().replace('"/static/', '"./').replace("'/static/", "'./")
    html = html.replace("<head>", '<head>\n  <meta name="portfi-runtime" content="pyodide" />', 1)
    idx.write_text(html)
    snap = ROOT / "data" / "snapshot"
    if not (snap / "ust_par.csv").exists():
        sys.exit("data/snapshot is missing — run: uv run python scripts/update_data.py")
    with zipfile.ZipFile(DIST / "engine.zip", "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in sorted((ROOT / "port").rglob("*.py")):
            if "__pycache__" in f.parts or f.name == "server.py":
                continue
            z.write(f, f.relative_to(ROOT))
        z.write(ROOT / "docs" / "METHODOLOGY.md", "docs/METHODOLOGY.md")
        for f in sorted(snap.iterdir()):
            z.write(f, f.relative_to(ROOT))
    (DIST / ".nojekyll").write_text("")
    size = (DIST / "engine.zip").stat().st_size / 1e6
    print(f"dist/ built · engine.zip {size:.2f} MB")


if __name__ == "__main__":
    main()
