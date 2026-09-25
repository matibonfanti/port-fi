"""Global conventions and reference data."""
from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
WEB_DIR = ROOT / "web"
# "server": may fetch live data (local FastAPI).  "browser": Pyodide, snapshot data only, no network.
RUNTIME = os.environ.get("PORT_FI_RUNTIME", "server")
SNAPSHOT_DIR = Path(os.environ.get("PORT_FI_DATA", str(DATA_DIR / "snapshot")))

# Key-rate tenors (years). These are the knots of every user deviation curve, the
# key-rate-duration buckets, and the grid on which PCA / covariances are estimated.
KEY_TENORS = [1 / 12, 0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 7.0, 10.0, 20.0, 30.0]
KEY_LABELS = ["1M", "3M", "6M", "1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"]

# Treasury CMT column names -> tenor in years.
UST_COLUMNS = {
    "1 Mo": 1 / 12, "1.5 Month": 1.5 / 12, "2 Mo": 2 / 12, "3 Mo": 0.25, "4 Mo": 4 / 12,
    "6 Mo": 0.5, "1 Yr": 1.0, "2 Yr": 2.0, "3 Yr": 3.0, "5 Yr": 5.0, "7 Yr": 7.0,
    "10 Yr": 10.0, "20 Yr": 20.0, "30 Yr": 30.0,
}
HISTORY_START_YEAR = 1990
# Treasury real (TIPS) par yield curve columns -> tenor in years (published since 2003).
TIPS_COLUMNS = {"5 YR": 5.0, "7 YR": 7.0, "10 YR": 10.0, "20 YR": 20.0, "30 YR": 30.0}
TIPS_START_YEAR = 2003
BE_TENORS = [5.0, 7.0, 10.0, 20.0, 30.0]

# Year fraction for curve time: ACT/365F from the as-of (settlement) date.
DAYS_PER_YEAR = 365.0

# FOMC meetings (second day = decision date). 2026-2027 from federalreserve.gov;
# 2028 are estimates following the usual pattern (flagged in the UI).
FOMC_MEETINGS = [
    ("2026-01-28", False), ("2026-03-18", False), ("2026-04-29", False), ("2026-06-17", False),
    ("2026-07-29", False), ("2026-09-16", False), ("2026-10-28", False), ("2026-12-09", False),
    ("2027-01-27", False), ("2027-03-17", False), ("2027-04-28", False), ("2027-06-09", False),
    ("2027-07-28", False), ("2027-09-15", False), ("2027-10-27", False), ("2027-12-08", False),
    ("2028-01-26", True), ("2028-03-15", True), ("2028-05-03", True), ("2028-06-14", True),
    ("2028-07-26", True), ("2028-09-20", True), ("2028-11-01", True), ("2028-12-13", True),
]

# Historical analogues: (key, label, start date, description).
ANALOGUES = [
    ("hike2022", "2022 hiking cycle", "2022-01-03", "Fed lifts off and hikes 425bp; bear flattener."),
    ("taper2013", "2013 taper tantrum", "2013-05-01", "Bernanke taper signal; bear steepener."),
    ("massacre1994", "1994 bond massacre", "1994-01-31", "Surprise hikes; violent selloff."),
    ("cuts2019", "2019 insurance cuts", "2019-05-01", "Three 'mid-cycle' cuts; bull flattener."),
    ("covid2020", "2020 Covid shock", "2020-02-14", "Emergency cuts to zero; bull steepener."),
    ("gfc2008", "2008 GFC", "2008-09-01", "Lehman; flight to quality."),
    ("bearsteep2023", "2023 term-premium selloff", "2023-07-17", "10y to 5%; bear steepener."),
    ("cuts2024", "2024 first cuts", "2024-07-01", "Cutting cycle begins; bull steepener."),
    ("easing2001", "2001 easing cycle", "2001-01-02", "475bp of cuts; massive bull steepener."),
    ("hikes2004", "2004 measured pace", "2004-06-01", "Conundrum: hikes, long end rallies."),
]

DEFAULT_HORIZON = 1.0


def parse_date(s: str | dt.date) -> dt.date:
    if isinstance(s, dt.date):
        return s
    return dt.date.fromisoformat(str(s)[:10])


def year_frac(d0: dt.date, d1: dt.date) -> float:
    return (d1 - d0).days / DAYS_PER_YEAR
