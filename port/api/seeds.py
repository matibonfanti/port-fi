"""Default views and positions offered to a new user (stored in the browser thereafter)."""
from __future__ import annotations

from ..paths import builders

PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]


def default_docs(sofr: float | None, has_real: bool, horizon: float = 1.0) -> dict:
    # Financing defaults to SOFR; if SOFR is unavailable the default is explicitly the implied short rate.
    fin = ({"mode": "flat", "rate_pct": sofr, "spread_bp": 0, "basis": "excess"} if sofr else
           {"mode": "implied", "rate_pct": 4.0, "spread_bp": 0, "basis": "excess"})
    views = [
        {"id": "v-fwd", "name": "Forwards realised", "color": PALETTE[2], **builders.preset("forwards", 0, horizon),
         "builder": {"type": "nodes"}, "notes": "The forward curve is realised: priced-in only, nothing from a view."},
        {"id": "v-unch", "name": "Curve unchanged", "color": PALETTE[1], **builders.preset("unchanged", 0, horizon),
         "builder": {"type": "nodes"}, "notes": "Today's curve holds: carry + roll-down."},
        {"id": "v-hike", "name": "One hike, not three", "color": PALETTE[0], "anchor": "forwards", "nodes": [],
         "builder": {"type": "policy", "params": {"mode": "meetings", "moves_scale": 0.33, "half_life": 2.0,
                                                  "convergence_months": 3, "tp": {"2": 0, "5": 0, "10": 0, "30": 0}}},
         "notes": "The Fed delivers about a third of the tightening priced; term premium unchanged."},
        {"id": "v-bull", "name": "Bull steepener 25bp vs fwd", "color": PALETTE[4],
         **builders.preset("bull_steepener", 25, horizon, anchor="forwards"), "builder": {"type": "nodes"},
         "notes": "Front end rallies 25bp relative to the forwards; long end as priced."},
        {"id": "v-tp", "name": "Term premium +30bp", "color": PALETTE[7], "anchor": "forwards", "nodes": [],
         "builder": {"type": "policy", "params": {"mode": "meetings", "moves_scale": 1.0, "half_life": 2.0,
                                                  "convergence_months": 3, "tp": {"2": 5, "5": 15, "10": 30, "30": 35}}},
         "notes": "Policy as priced, but investors demand more term premium: bear steepener."},
    ]
    if has_real:
        views.append({"id": "v-infl", "name": "Sticky inflation (3%+)", "color": PALETTE[3], "anchor": "forwards",
                      "nodes": [], "builder": {"type": "nodes"},
                      "inflation": {"mode": "expectations", "buckets": [3.4, 3.1, 2.9, 2.7, 2.5], "convergence_months": 3,
                                    "irp": {"2": 0, "5": 10, "10": 15, "30": 15}, "passthrough": 1.0},
                      "notes": "CPI runs above what breakevens price and the inflation risk premium rises; real yields "
                               "held, so nominal yields rise with breakevens (100% pass-through)."})
    positions = [
        {"id": "p-10y", "name": "10y UST (on-the-run)", "items": [{"kind": "bond", "bond": {"otr": 10}, "face_mm": 1}], "financing": fin},
        {"id": "p-2s10s", "name": "2s10s steepener (DV01)", "items": [{"kind": "steepener", "legs": [{"otr": 2}, {"otr": 10}],
                                                                        "weighting": "dv01", "size_mm": 1}], "financing": fin},
        {"id": "p-fly", "name": "2s5s10s fly (PCA)", "items": [{"kind": "butterfly", "legs": [{"otr": 2}, {"otr": 5}, {"otr": 10}],
                                                               "weighting": "pca", "size_mm": 1, "direction": "short_belly"}], "financing": fin},
        {"id": "p-5y30", "name": "5y + 5s30s flattener", "items": [{"kind": "bond", "bond": {"otr": 5}, "face_mm": 1},
                                                                  {"kind": "flattener", "legs": [{"otr": 5}, {"otr": 30}],
                                                                   "weighting": "dv01", "size_mm": 0.5}], "financing": fin},
        {"id": "p-ig", "name": "10y IG credit (+95bp)", "items": [{"kind": "bond", "bond": {"tenor": 10, "coupon": 6.0},
                                                                  "face_mm": 1, "spread_bp": 95, "credit": True}], "financing": fin},
    ]
    if has_real:
        positions += [
            {"id": "p-tips", "name": "10y TIPS (on-the-run)", "items": [{"kind": "tips", "bond": {"otr": 10}, "face_mm": 1}], "financing": fin},
            {"id": "p-be", "name": "10y breakeven (long TIPS / short UST)", "items": [
                {"kind": "breakeven", "legs": [{"otr": 10}, {"otr": 10}], "weighting": "dv01", "size_mm": 1, "direction": "long"}],
             "financing": fin},
        ]
    return {"views": views, "positions": positions}
