"""FOMC decision dates: parsed from federalreserve.gov by the data refresh and stored in the snapshot.
The policy builder uses them as confirmed dates; any years they don't cover fall back to config
(flagged as estimated), then to an 8-a-year pattern (also flagged)."""
from __future__ import annotations

import datetime as dt
import json
import re

from ..config import SNAPSHOT_DIR

URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
MONTHS = {m: i for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July", "August",
                                      "September", "October", "November", "December"], 1)}
_ABBR = {m[:3]: i for m, i in MONTHS.items()}


def parse(html: str) -> list[str]:
    """Decision (second-day) dates, ISO, from the Fed's calendar page."""
    out = []
    parts = re.split(r"(\d{4}) FOMC Meetings", html)
    for k in range(1, len(parts) - 1, 2):
        year, body = int(parts[k]), parts[k + 1]
        for mon, days in re.findall(r'fomc-meeting__month[^>]*>\s*<strong>([^<]+)</strong>.*?fomc-meeting__date[^>]*>([^<]+)<',
                                    body, re.S):
            mon, days = mon.strip(), days.strip().rstrip("*").strip()
            m = re.match(r"(\d{1,2})(?:-(\d{1,2}))?", days)
            if not m:
                continue
            last_day = int(m.group(2) or m.group(1))
            names = mon.split("/")
            mname = names[-1][:3] if (m.group(2) and int(m.group(2)) < int(m.group(1))) or len(names) == 1 else names[-1][:3]
            mi = _ABBR.get(mname)
            if mi is None:
                continue
            try:
                out.append(dt.date(year, mi, last_day).isoformat())
            except ValueError:
                continue
    return sorted(set(out))


def fetch() -> list[str]:
    import httpx

    r = httpx.get(URL, timeout=30, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (port-fi data refresh)"})
    r.raise_for_status()
    dates = parse(r.text)
    if len(dates) < 8:
        raise ValueError("FOMC calendar page could not be parsed")
    return dates


def confirmed() -> list[str]:
    f = SNAPSHOT_DIR / "fomc.json"
    return json.loads(f.read_text()).get("dates", []) if f.exists() else []
