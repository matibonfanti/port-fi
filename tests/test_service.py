"""End-to-end analysis on the cached market data (skipped if no data is cached)."""
import datetime as dt

import pytest

from port.config import SNAPSHOT_DIR
from port.paths.policy import meetings_after

pytestmark = pytest.mark.skipif(not (SNAPSHOT_DIR / "ust_par.csv").exists(), reason="no data snapshot")

POS = {"items": [{"kind": "bond", "bond": {"tenor": 10}, "face_mm": 1},
                 {"kind": "butterfly", "legs": [{"tenor": 2}, {"tenor": 5}, {"tenor": 10}], "weighting": "pca", "size_mm": 1}],
       "financing": {"mode": "flat", "rate_pct": 4.0}}


def test_meetings_fallback_for_historical_dates():
    m = meetings_after(dt.date(2008, 12, 15), 2.0)
    assert len(m) >= 15 and all(x["estimated"] for x in m)
    assert all(b["t"] > a["t"] for a, b in zip(m, m[1:]))


@pytest.mark.parametrize("asof", [None, "2020-03-20", "1995-06-01"])
@pytest.mark.parametrize("view", [
    {"anchor": "forwards", "nodes": []},
    {"anchor": "today", "nodes": [{"t": 0.5, "dev": [10] * 11, "spread": 5}]},
    {"anchor": "forwards", "nodes": [], "builder": {"type": "policy", "params": {"moves_scale": 0.5, "tp": {"10": 20}}}},
])
def test_analyze_end_to_end(asof, view):
    from port import service
    r = service.analyze({"asof": asof, "horizon": 1.0, "basis": "pca", "view": view, "position": POS})
    gross = r["position"]["gross_mv"]
    for k, v in r["identity"].items():
        assert v < 1e-7 * gross, k
    assert r["summary"]["sentences"] and r["heatmap"]["pnl"] and r["risk"]["mc"]["n"] == 4000
    if view["anchor"] == "forwards" and not view.get("builder"):
        assert abs(r["attribution"]["edge"]["total"][-1]) < 1e-7 * gross


def test_fomc_page_parser():
    from port.data.fomc import parse
    html = ('2027 FOMC Meetings <div class="fomc-meeting__month"><strong>January</strong></div>'
            '<div class="fomc-meeting__date">26-27</div> <div class="fomc-meeting__month"><strong>Apr/May</strong></div>'
            '<div class="fomc-meeting__date">30-1*</div> <div class="fomc-meeting__month"><strong>June</strong></div>'
            '<div class="fomc-meeting__date">8-9*</div>')
    assert parse(html) == ["2027-01-27", "2027-05-01", "2027-06-09"]
