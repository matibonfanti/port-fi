"""Risk context at the horizon: factor ±1σ, total volatility, return per unit of vol, Monte-Carlo.
Books with TIPS use the joint covariance of nominal key-tenor zeros and breakevens (TIPS era)."""
from __future__ import annotations

import numpy as np

from ..config import BE_TENORS
from ..curves.history import HistoryStats
from ..curves.interp import tent_weights
from ..paths.path import ExpectationPath
from .attribution import BP, KT, Book
from .scenario import context, pnl

BT = np.array(BE_TENORS)


def horizon_risk(book: Book, path: ExpectationPath, H: float, stats: HistoryStats, basis_kind: str,
                 expected: float, infl=None, n_sims: int = 4000, seed: int = 7, do_mc: bool = True) -> dict:
    basis = stats.basis(basis_kind)
    Hh = max(H, 1 / 252)
    c = context(book, path, infl, H, "view")
    base = float(pnl(book, H, c)[0])
    be_fn = (lambda tau: c.be(tau)[None, :]) if c.be is not None else None
    I_H = float(np.asarray(c.index(np.array([H])))[0]) if c.index is not None else None
    dv01, krd, fx, bkrd = book.exposures_at(H, lambda tau: c.nominal(tau)[None, :], basis, c.spread, be_fn, I_H)
    joint = book.has_real and stats.joint_cov is not None
    if book.has_real and not joint:
        raise ValueError("Breakeven risk needs a TIPS-era covariance window (2003 onward).")
    if joint:
        e = np.concatenate([krd, bkrd])
        C = stats.joint_cov / BP**2 * Hh
    else:
        e, C = krd, stats.knot_cov / BP**2 * Hh
    sigma = float(np.sqrt(max(e @ C @ e, 0.0)))
    fvol = basis.vols / BP * np.sqrt(Hh)
    factors = []
    for k, lab in enumerate(basis.labels):
        shock = lambda sgn, k=k: (lambda tau: c.nominal(tau)[None, :] + sgn * fvol[k] * BP * basis.loadings(tau)[None, :, k])
        up = float(pnl(book, H, c, nominal_fn=shock(1))[0]) - base
        dn = float(pnl(book, H, c, nominal_fn=shock(-1))[0]) - base
        factors.append({"factor": lab, "sigma_bp": float(fvol[k]), "vol_ann_bp": float(basis.vols[k] / BP),
                        "up": up, "down": dn, "expo_per_bp": float(fx[k])})
    if joint:
        bvol = float(np.sqrt(stats.joint_cov[len(KT) + 2, len(KT) + 2]) / BP * np.sqrt(Hh))  # 10y breakeven
        up = float(pnl(book, H, c, be_fn=lambda tau: c.be(tau)[None, :] + bvol * BP)[0]) - base
        dn = float(pnl(book, H, c, be_fn=lambda tau: c.be(tau)[None, :] - bvol * BP)[0]) - base
        factors.append({"factor": "Breakevens (parallel)", "sigma_bp": bvol, "vol_ann_bp": bvol / np.sqrt(Hh),
                        "up": up, "down": dn, "expo_per_bp": float(bkrd.sum())})
    out = {"sigma": sigma, "expected": expected, "ratio": expected / sigma if sigma > 0 else None,
           "ratio_ann": (expected / H) / (sigma / np.sqrt(Hh)) if sigma > 0 and H > 0 else None,
           "factors": factors, "dv01": float(dv01), "krd": krd.tolist(), "be_krd": bkrd.tolist() if book.has_real else None,
           "knot_vol_ann_bp": (np.sqrt(np.diag(stats.knot_cov)) / BP).tolist(),
           "window": list(stats.window), "n_obs": stats.n_obs, "joint": joint}
    if do_mc:
        rng = np.random.default_rng(seed)
        w, V = np.linalg.eigh(C)
        X = rng.standard_normal((n_sims, len(e))) @ (V * np.sqrt(np.clip(w, 0, None))).T * BP
        Xn, Xb = X[:, :len(KT)], X[:, len(KT):]
        nom = lambda tau: c.nominal(tau)[None, :] + Xn @ tent_weights(KT, tau).T
        be = (lambda tau: c.be(tau)[None, :] + Xb @ tent_weights(BT, tau).T) if joint else None
        p = pnl(book, H, c, nominal_fn=nom, be_fn=be)
        pct = np.percentile(p, [1, 5, 25, 50, 75, 95, 99])
        hist, edges = np.histogram(p, bins=50)
        out["mc"] = {"n": n_sims, "mean": float(p.mean()), "std": float(p.std()), "p_loss": float((p < 0).mean()),
                     "pct": dict(zip(["p1", "p5", "p25", "p50", "p75", "p95", "p99"], map(float, pct))),
                     "es5": float(p[p <= pct[1]].mean()), "hist": hist.tolist(), "edges": edges.tolist()}
    return out
