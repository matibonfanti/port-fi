"""Inverse engine: what market outcome delivers a target return at the horizon?

Targets (on the active return basis):
    breakeven   P&L = 0 (excess basis: return equals financing; total basis: no loss)
    cash        total basis only: return equals the cash rate, P&L = Σ face·P0·(G(H) − 1)
    target      a target return, % per year on gross MV: P&L = gross · ((1 + X)^H − 1)
                (excess basis: gross · X · H)
Moves solved for, each with every other input held at its context (see scenario.py):
    parallel_today     z0 + x                    parallel_fwd    F(H) + x       parallel_view   Z_u(H) + x
    slope_today        z0 + x·L_slope
    view_fraction      z0 + k·(Z_u(H) − z0) (and breakevens / CPI scaled likewise); latest realisation = H/k
    cpi (TIPS books)   realised CPI π with rates and breakevens per your view: index(s) = (1 + π)^s
    be_view (TIPS)     breakevens B_u(H) + x
Roots: grid scan for sign changes, then Illinois refinement; the root closest to the base is reported and
substituted back into the pricing engine (the residual is returned). No root → reason ('always' / 'never').
"""
from __future__ import annotations

import numpy as np

from ..config import KEY_TENORS
from ..curves.interp import root_scalar
from .scenario import context, pnl

BP = 1e-4
REPORT_TENORS = [2.0, 5.0, 10.0, 30.0]


def targets(book, H: float, target_pct: float | None) -> list[dict]:
    fin, g = book.fin, book.gross_mv
    out = [{"key": "breakeven", "label": "Break even" if fin.basis == "total" else "Beat financing", "value": 0.0}]
    if fin.basis == "total":
        G = float(fin.growth(book.z0, np.array([H]), H)[0])
        net = float(np.sum(book.face * 1e6 * book.P0))
        out.append({"key": "cash", "label": f"Beat cash ({fin.rate_pct:.2f}%)" if fin.mode == "flat" else "Beat cash (implied)",
                    "value": net * (G - 1)})
    if target_pct is not None:
        v = g * ((1 + target_pct / 100) ** H - 1) if fin.basis == "total" else g * target_pct / 100 * H
        out.append({"key": "target", "label": f"Return {target_pct:.2f}%/yr", "value": v})
    return out


def _solve(f_vec, grid, target, ref, scalar=None):
    ys = f_vec(grid) - target
    s = np.sign(ys)
    idx = np.where(s[:-1] * s[1:] < 0)[0]
    exact = np.where(ys == 0)[0]
    roots = [float(grid[i]) for i in exact]
    fs = scalar or (lambda x: float(f_vec(np.array([x]))[0]) - target)
    for i in idx:
        try:
            roots.append(root_scalar(fs, float(grid[i]), float(grid[i + 1]), xtol=1e-9))
        except ValueError:
            pass
    if not roots:
        return {"ok": False, "reason": "always" if np.all(ys > 0) else "never", "lo": float(grid[0]), "hi": float(grid[-1])}
    x = min(roots, key=lambda r: abs(r - ref))
    return {"ok": True, "x": x, "residual": float(fs(x)), "n_roots": len(roots)}


def solve_all(book, path, infl, H: float, basis, target_pct: float | None = None) -> dict:
    z0 = book.z0
    tg = targets(book, H, target_pct)
    c_today, c_fwd, c_view = (context(book, path, infl, H, b) for b in ("today", "forwards", "view"))
    shift = lambda ctx: (lambda xs: pnl(book, H, ctx, nominal_fn=lambda tau: ctx.nominal(tau)[None, :] + np.asarray(xs)[:, None] * BP))
    slope = lambda xs: pnl(book, H, c_today, nominal_fn=lambda tau: c_today.nominal(tau)[None, :]
                           + np.asarray(xs)[:, None] * BP * basis.loadings(tau)[None, :, 1])

    def frac(ks):
        ks = np.asarray(ks)[:, None]
        nom = lambda tau: z0.z(tau)[None, :] + ks * (c_view.nominal(tau) - z0.z(tau))[None, :]
        if book.has_real:
            be = lambda tau: c_today.be(tau)[None, :] + ks * (c_view.be(tau) - c_today.be(tau))[None, :]
            idx = lambda s: book.index_F(s)[None, :] * (np.asarray(infl.index_fn(s)) / book.index_F(s))[None, :] ** ks
            return pnl(book, H, c_view, nominal_fn=nom, be_fn=be, index_fn=idx)
        return pnl(book, H, c_view, nominal_fn=nom)

    moves = {
        "parallel_today": (shift(c_today), np.linspace(-600, 600, 241), 0.0),
        "parallel_fwd": (shift(c_fwd), np.linspace(-600, 600, 241), 0.0),
        "parallel_view": (shift(c_view), np.linspace(-600, 600, 241), 0.0),
        "slope_today": (slope, np.linspace(-600, 600, 241), 0.0),
        "view_fraction": (frac, np.linspace(-4, 6, 401), 1.0),
    }
    if book.has_real:
        def cpi(ps):
            ps = np.asarray(ps)[:, None]
            return pnl(book, H, c_view, index_fn=lambda s: (1 + ps / 100) ** np.asarray(s)[None, :])
        be_shift = lambda xs: pnl(book, H, c_view, be_fn=lambda tau: c_view.be(tau)[None, :] + np.asarray(xs)[:, None] * BP)
        moves["cpi"] = (cpi, np.linspace(-10, 25, 351), 2.5)
        moves["be_view"] = (be_shift, np.linspace(-600, 600, 241), 0.0)

    kt = np.array(KEY_TENORS)
    rep_idx = [KEY_TENORS.index(x) for x in REPORT_TENORS]
    rows = []
    for t in tg:
        row = {**t, "moves": {}}
        for key, (f, grid, ref) in moves.items():
            r = _solve(f, grid, t["value"], ref)
            if r["ok"] and key in ("parallel_today", "parallel_fwd", "parallel_view"):
                base = {"parallel_today": c_today, "parallel_fwd": c_fwd, "parallel_view": c_view}[key]
                r["levels"] = ((base.nominal(kt)[rep_idx] + r["x"] * BP) * 100).tolist()
            if r["ok"] and key == "view_fraction":
                k = r["x"]
                r["levels"] = ((z0.z(kt) + k * (c_view.nominal(kt) - z0.z(kt)))[rep_idx] * 100).tolist()
                r["latest_t"] = H / k if k > 1e-9 else None   # view realised linearly by T: fraction at H = H/T
            row["moves"][key] = r
        rows.append(row)
    base_pnl = {b: float(pnl(book, H, c)[0]) for b, c in (("today", c_today), ("forwards", c_fwd), ("view", c_view))}
    return {"targets": rows, "report_tenors": REPORT_TENORS, "base_pnl": base_pnl,
            "levels_today": (z0.z(kt)[rep_idx] * 100).tolist(),
            "levels_fwd": (c_fwd.nominal(kt)[rep_idx] * 100).tolist(),
            "levels_view": (c_view.nominal(kt)[rep_idx] * 100).tolist(),
            "cpi_view": infl.report.get("horizon_user_yoy") if (infl is not None and book.has_real) else None}
