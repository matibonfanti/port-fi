"""Timing sensitivity: the same end-state curve reached immediately, early, gradually or late."""
from __future__ import annotations

import numpy as np

from ..paths.path import ExpectationPath
from .attribution import Book

PROFILES = [
    ("immediate", "Immediate", lambda s: np.minimum(1.0, s / 0.02)),
    ("early", "Early (first quarter)", lambda s: np.minimum(1.0, s / 0.25)),
    ("linear", "Linear", lambda s: s),
    ("late", "Late (last quarter)", lambda s: np.clip((s - 0.75) / 0.25, 0, 1)),
]


def timing(book: Book, path: ExpectationPath, t: np.ndarray, basis, infl=None) -> dict:
    H = float(t[-1])
    end_dev = path.dev_knots(np.array([H]))[0]
    end_spread = float(path.spread(np.array([H]))[0])
    out = []
    s_nodes = np.unique(np.concatenate([np.linspace(0, 1, 81)[1:], [0.02, 0.25, 0.75]]))
    base = book.attribute(path, t, basis, infl)
    gm = max(book.gross_mv, 1.0)
    rows = [("your_path", "Your path", base.total)]
    for key, label, w in PROFILES:
        wt = w(s_nodes)
        p = ExpectationPath(path.anchor, s_nodes * H, np.outer(wt, end_dev),
                            (wt * end_spread) if end_spread else None, "linear")
        a = book.attribute(p, t, basis, infl)
        rows.append((key, label, a.total))
    for key, label, tot in rows:
        # realisation time: first time the path's deviation reaches (and stays at) its end state
        peak = np.maximum.accumulate(tot)
        dd = float(np.min(tot - peak))
        out.append({"key": key, "label": label, "total": tot.tolist(), "pnl_H": float(tot[-1]),
                    "max_drawdown": dd, "min_pnl": float(tot.min()), "avg_pnl": float(np.mean(tot))})
    real = {"immediate": 0.02, "early": 0.25, "linear": 1.0, "late": 1.0}
    for r in out:
        if r["key"] in real:
            s = real[r["key"]]
            te = s * H
            i = int(np.argmin(np.abs(t - te)))
            pnl_te = r["total"][i]
            r["realised_t"] = float(t[i])
            r["pnl_at_realisation"] = float(pnl_te)
            r["ann_bp_if_exit"] = float(pnl_te / gm * 1e4 / max(t[i], 1 / 52))
    return {"profiles": out, "note": "Buy-and-hold horizon P&L depends only on the curve at the horizon; "
                                     "timing changes the path, the drawdown and the return if you exit on realisation."}
