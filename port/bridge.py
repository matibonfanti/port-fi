"""Single JSON entry point used by both transports: the FastAPI server and the in-browser (Pyodide)
worker. Python stays the only place where financial logic lives."""
from __future__ import annotations

import json
import traceback

from . import service
from .config import ROOT

_METHODOLOGY = None


def _methodology(_):
    global _METHODOLOGY
    if _METHODOLOGY is None:
        for p in (ROOT / "docs" / "METHODOLOGY.md", ROOT / "METHODOLOGY.md"):
            if p.exists():
                _METHODOLOGY = p.read_text()
                break
    return {"text": _METHODOLOGY or "Methodology not bundled."}


HANDLERS = {
    "market": lambda p: service.market_info((p or {}).get("asof")),
    "analyze": service.analyze,
    "analogue": service.compile_analogue,
    "preset": service.compile_preset,
    "methodology": _methodology,
}


def call(name: str, payload_json: str) -> str:
    try:
        out = HANDLERS[name](json.loads(payload_json) if payload_json else None)
        return json.dumps(out, separators=(",", ":"))
    except Exception as e:  # errors go back to the UI as messages, never silently
        return json.dumps({"error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc(limit=3)})
