"""US Treasury nominal (CMT) and real (TIPS) par-yield curves from treasury.gov.

Sources, in order: the committed data snapshot (data/snapshot, rebuilt daily by
scripts/update_data.py), then — in server runtime only — live fetches of recent years. Every
fallback is recorded in STATUS and surfaced to the UI as a data flag; nothing is substituted silently.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import logging
import time
from functools import lru_cache

import numpy as np

from ..config import (CACHE_DIR, HISTORY_START_YEAR, RUNTIME, SNAPSHOT_DIR, TIPS_COLUMNS,
                      TIPS_START_YEAR, UST_COLUMNS)
from .panel import Panel, to_date

log = logging.getLogger(__name__)

URL = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
       "daily-treasury-rates.csv/{y}/all?type={kind}&field_tdr_date_value={y}&page&_format=csv")
KINDS = {
    "nominal": {"type": "daily_treasury_yield_curve", "cols": UST_COLUMNS, "start": HISTORY_START_YEAR,
                "snapshot": "ust_par.csv", "cache": "ust_par_{y}.csv"},
    "real": {"type": "daily_treasury_real_yield_curve", "cols": TIPS_COLUMNS, "start": TIPS_START_YEAR,
             "snapshot": "ust_real.csv", "cache": "ust_real_{y}.csv"},
}
REFRESH_SECONDS = 6 * 3600
# kind -> {"source": "snapshot"|"live"|"cache"|"none", "last": date, "errors": [str]}
STATUS: dict = {}


def parse_csv(text: str, colmap: dict) -> Panel:
    rows = list(csv.reader(io.StringIO(text)))
    head = rows[0]
    keep = [(i, h) for i, h in enumerate(head) if h in colmap]
    cols = [colmap[h] for _, h in keep]
    ds, vals = [], []
    for r in rows[1:]:
        if not r or not r[0]:
            continue
        m, d, y = r[0].split("/")
        ds.append(f"{y}-{m}-{d}")
        vals.append([float(r[i]) if i < len(r) and r[i] not in ("", "N/A") else np.nan for i, _ in keep])
    order = np.argsort(np.array(ds, dtype="datetime64[D]"))
    return Panel(np.array(ds, dtype="datetime64[D]")[order], cols, np.array(vals, float).reshape(len(ds), len(cols))[order])


def fetch_year(year: int, kind: str = "nominal", force: bool = False) -> Panel:
    """One calendar year, live (server runtime) with a per-year raw cache."""
    import httpx  # server runtime only

    k = KINDS[kind]
    f = CACHE_DIR / k["cache"].format(y=year)
    current = year >= dt.date.today().year
    if f.exists() and not force and (not current or time.time() - f.stat().st_mtime < REFRESH_SECONDS):
        return parse_csv(f.read_text(), k["cols"])
    r = httpx.get(URL.format(y=year, kind=k["type"]), timeout=30, follow_redirects=True)
    r.raise_for_status()
    p = parse_csv(r.text, k["cols"])
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    f.write_text(r.text)
    return p


def _all_cols(kind):
    return sorted(set(KINDS[kind]["cols"].values()))


def load_snapshot(kind: str) -> Panel | None:
    f = SNAPSHOT_DIR / KINDS[kind]["snapshot"]
    return Panel.read_csv(f) if f.exists() else None


@lru_cache(maxsize=4)
def _history(kind: str, stamp: int) -> Panel:
    k = KINDS[kind]
    cols = _all_cols(kind)
    status = {"source": "none", "errors": []}
    snap = load_snapshot(kind)
    parts = [snap] if snap is not None else []
    if snap is not None:
        status["source"] = "snapshot"
        status["snapshot_last"] = snap.last.isoformat()
    if RUNTIME == "server":
        years = range(k["start"], dt.date.today().year + 1) if snap is None else \
            range(max(k["start"], snap.last.year), dt.date.today().year + 1)
        from concurrent.futures import ThreadPoolExecutor

        def one(y):
            try:
                return fetch_year(y, kind)
            except Exception as e:  # recorded, never silent
                status["errors"].append(f"{y}: {type(e).__name__}")
                return None

        with ThreadPoolExecutor(8) as ex:
            live = [p for p in ex.map(one, years) if p is not None]
        if live:
            parts += live
            status["source"] = "live" if not status["errors"] else "partial"
    if not parts:
        raise RuntimeError(f"No {kind} Treasury data available (no snapshot, fetch failed)")
    h = Panel.concat(parts, cols)
    status["last"] = h.last.isoformat()
    STATUS[kind] = status
    return h


def history(kind: str = "nominal") -> Panel:
    """Daily par yields in PERCENT; columns are tenors in years (NaN where not published)."""
    return _history(kind, int(time.time() // REFRESH_SECONDS))


def par_history() -> Panel:
    return history("nominal")


def par_curve(asof=None, kind: str = "nominal"):
    """(curve date, tenors, par yields as decimals, missing tenors) on or before `asof`."""
    h = history(kind)
    d, row = h.row_on_or_before(asof or h.last)
    if d is None:
        raise ValueError(f"No {kind} Treasury curve on or before {asof} (history starts {h.first})")
    ok = ~np.isnan(row)
    ten = np.array(h.cols)[ok]
    missing = [c for c, o in zip(h.cols, ok) if not o]
    return d, ten, row[ok] / 100.0, missing
