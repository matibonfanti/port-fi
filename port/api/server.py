"""FastAPI app (local development): the same bridge the browser build uses, over HTTP, plus static UI."""
from __future__ import annotations

import json
import os

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .. import bridge
from ..config import ROOT, WEB_DIR

app = FastAPI(title="PORT-FI", version="0.2")


@app.post("/api/{name}")
async def call(name: str, req: Request):
    body = await req.body()
    out = json.loads(bridge.call(name, body.decode() or "null"))
    return JSONResponse(out, status_code=400 if isinstance(out, dict) and "error" in out else 200)


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
if (ROOT / "dist").exists():  # the static (in-browser engine) build, for local testing: /dist/
    app.mount("/dist", StaticFiles(directory=ROOT / "dist", html=True), name="dist")


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


def main():  # entry point: `uv run port`
    import uvicorn
    uvicorn.run("port.api.server:app", host="127.0.0.1", port=int(os.environ.get("PORT_FI_PORT", 8765)))
