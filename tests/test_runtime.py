"""The browser build runs the engine under Pyodide with numpy only: guard against runtime dependencies creeping in."""
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

SCRIPT = r"""
import sys, json, builtins
blocked = {"pandas", "scipy", "httpx", "fastapi", "uvicorn", "pydantic"}
real_import = builtins.__import__
def guard(name, *a, **k):
    if name.split(".")[0] in blocked:
        raise ImportError("blocked in browser runtime: " + name)
    return real_import(name, *a, **k)
builtins.__import__ = guard
sys.path.insert(0, sys.argv[1])
from port import bridge
m = json.loads(bridge.call("market", "{}"))
assert "error" not in m, m
req = {"horizon": 0.5, "view": m["defaults"]["views"][2], "position": m["defaults"]["positions"][0], "target_pct": 4}
r = json.loads(bridge.call("analyze", json.dumps(req)))
assert "error" not in r, r
print(json.dumps({"ok": True, "flags": [f["code"] for f in r["flags"]], "id": max(r["identity"].values())}))
"""


@pytest.mark.skipif(not (ROOT / "data" / "snapshot" / "ust_par.csv").exists(), reason="no snapshot")
def test_engine_runs_with_numpy_only_in_browser_mode(tmp_path):
    env = {**os.environ, "PORT_FI_RUNTIME": "browser", "PORT_FI_DATA": str(ROOT / "data" / "snapshot")}
    out = subprocess.run([sys.executable, "-c", SCRIPT, str(ROOT)], capture_output=True, text=True, env=env, timeout=300)
    assert out.returncode == 0, out.stderr[-2000:]
    res = json.loads(out.stdout.strip().splitlines()[-1])
    assert res["ok"] and res["id"] < 1e-6
    assert "nominal_snapshot" in res["flags"]          # the snapshot source is disclosed, not silent


def test_static_build_contents(tmp_path):
    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_static.py")], capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    z = zipfile.ZipFile(ROOT / "dist" / "engine.zip")
    names = set(z.namelist())
    assert "port/bridge.py" in names and "docs/METHODOLOGY.md" in names and "data/snapshot/ust_par.csv" in names
    assert "port/api/server.py" not in names
    html = (ROOT / "dist" / "index.html").read_text()
    assert 'content="pyodide"' in html and '"/static/' not in html
