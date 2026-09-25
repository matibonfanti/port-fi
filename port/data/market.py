"""Reference rates (NY Fed SOFR/EFFR) and on-the-run nominal/TIPS issues (TreasuryDirect).

Server runtime fetches live (cached 1h/12h) and falls back to the snapshot; browser runtime reads the
snapshot only. STATUS records which source was used so the UI can flag it.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import time

from ..config import CACHE_DIR, RUNTIME, SNAPSHOT_DIR

log = logging.getLogger(__name__)
STATUS: dict = {}
TERMS = {"2-Year": 2, "3-Year": 3, "5-Year": 5, "7-Year": 7, "10-Year": 10, "20-Year": 20, "30-Year": 30}


def snapshot_market() -> dict:
    f = SNAPSHOT_DIR / "market.json"
    return json.loads(f.read_text()) if f.exists() else {}


def _cached_json(name: str, url: str, max_age: float):
    f = CACHE_DIR / name
    if f.exists() and time.time() - f.stat().st_mtime < max_age:
        return json.loads(f.read_text())
    import httpx

    r = httpx.get(url, timeout=20, follow_redirects=True)
    r.raise_for_status()
    data = r.json()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(data))
    return data


def fetch_reference_rates() -> dict:
    out: dict = {}
    s = _cached_json("sofr.json", "https://markets.newyorkfed.org/api/rates/secured/sofr/last/1.json", 3600)["refRates"][0]
    out["sofr"] = {"rate": s["percentRate"], "date": s["effectiveDate"]}
    e = _cached_json("effr.json", "https://markets.newyorkfed.org/api/rates/unsecured/effr/last/1.json", 3600)["refRates"][0]
    out["effr"] = {"rate": e["percentRate"], "date": e["effectiveDate"], "target": [e.get("targetRateFrom"), e.get("targetRateTo")]}
    return out


def fetch_securities(asof: dt.date) -> dict:
    """Most recently issued nominal and TIPS per benchmark term, issued on or before asof."""
    start = (asof - dt.timedelta(days=800)).isoformat()
    nominal, tips = {}, {}
    for stype in ("Note", "Bond"):
        url = (f"https://www.treasurydirect.gov/TA_WS/securities/search?securityType={stype}"
               f"&format=json&dateFieldName=auctionDate&startDate={start}")
        for s in _cached_json(f"td_{stype.lower()}.json", url, 12 * 3600) or []:
            term = s.get("originalSecurityTerm") or s.get("securityTerm", "")
            if term not in TERMS or s.get("floatingRate") == "Yes":
                continue
            issue = dt.date.fromisoformat(s["issueDate"][:10])
            if issue > asof:
                continue
            is_tips = s.get("type") == "TIPS" or s.get("tips") == "Yes"
            book = tips if is_tips else nominal
            prev = book.get(term)
            if prev is None or issue > dt.date.fromisoformat(prev["issue"]):
                mat = s["maturityDate"][:10]
                cpn = float(s["interestRate"])
                book[term] = {"issue": issue.isoformat(), "cusip": s["cusip"], "coupon": cpn, "maturity": mat,
                              "term": TERMS[term], "tips": is_tips,
                              "label": f"{'TII' if is_tips else 'T'} {cpn:g} {dt.date.fromisoformat(mat).strftime('%m/%d/%y')}"}
    key = lambda x: x["term"]
    return {"otr": sorted(nominal.values(), key=key), "otr_tips": sorted(tips.values(), key=key)}


def market_refs(asof: dt.date, latest: dt.date) -> dict:
    """{'rates', 'otr', 'otr_tips'} for the as-of date, plus STATUS. Only valid for the latest curve date."""
    snap = snapshot_market()
    STATUS.clear()
    if asof != latest:
        STATUS["historical"] = True
        return {"rates": {}, "otr": [], "otr_tips": []}
    out = {}
    if RUNTIME == "server":
        try:
            out["rates"] = fetch_reference_rates()
            STATUS["rates"] = "live"
        except Exception as e:
            STATUS["rates"] = f"snapshot ({type(e).__name__})"
        try:
            out.update(fetch_securities(asof))
            STATUS["securities"] = "live"
        except Exception as e:
            STATUS["securities"] = f"snapshot ({type(e).__name__})"
    if "rates" not in out:
        out["rates"] = snap.get("rates", {})
        STATUS.setdefault("rates", "snapshot" if out["rates"] else "unavailable")
        STATUS["rates_asof"] = snap.get("built")
    if "otr" not in out:
        out["otr"], out["otr_tips"] = snap.get("otr", []), snap.get("otr_tips", [])
        STATUS.setdefault("securities", "snapshot" if out["otr"] else "unavailable")
        STATUS["securities_asof"] = snap.get("built")
    return out
