"""Parallel/slope break-evens, the Δlevel × Δslope horizon-return map, and time-to-cover."""
from __future__ import annotations

import numpy as np

from ..curves.history import FactorBasis
from ..paths.path import ExpectationPath
from .attribution import BP, KT, Book
from .inverse import _solve
from .scenario import context, pnl


def breakevens(book: Book, H: float, basis: FactorBasis, path=None, infl=None) -> dict:
    """Moves (bp) at the horizon that make P&L zero: parallel & slope, vs today & vs forwards."""
    out = {}
    grid = np.linspace(-600, 600, 241)
    for base in ("today", "forwards"):
        c = context(book, path, infl, H, base)
        par = lambda xs, c=c: pnl(book, H, c, nominal_fn=lambda tau: c.nominal(tau)[None, :] + np.asarray(xs)[:, None] * BP)
        slo = lambda xs, c=c: pnl(book, H, c, nominal_fn=lambda tau: c.nominal(tau)[None, :]
                                  + np.asarray(xs)[:, None] * BP * basis.loadings(tau)[None, :, 1])
        rp, rs = _solve(par, grid, 0.0, 0.0), _solve(slo, grid, 0.0, 0.0)
        out[base] = {"parallel": rp.get("x"), "slope": rs.get("x"), "parallel_reason": rp.get("reason"),
                     "slope_reason": rs.get("reason"), "pnl_at_base": float(pnl(book, H, c)[0])}
    return out


def heatmap(book: Book, H: float, basis: FactorBasis, path: ExpectationPath, infl=None, base: str = "today",
            n: int = 41, levels=None) -> dict:
    """Horizon P&L on a grid of Δlevel × Δslope applied to today's curve (or the forwards) at H.
    Breakevens and CPI follow the same base (today: b0 & priced CPI; forwards: Bf & priced CPI)."""
    z0 = book.z0
    real_only = all(l.real for l in book.lines) and infl is not None
    if real_only:   # TIPS-only book: the axes are real-yield moves (breakevens held), markers from real curves
        r0 = book.r0
        zk0, Fk = r0.z(KT), r0.fwd(H, KT)
        Uk = path.curve(z0, np.array([H]), KT)[0] - infl.be_curve(np.array([H]), KT)[0]
    else:
        zk0 = z0.z(KT)
        Fk = z0.fwd(H, KT)
        Uk = path.curve(z0, np.array([H]), KT)[0]
    P = basis.projector
    b_fwd = (Fk - zk0) @ P.T / BP
    b_view = (Uk - zk0) @ P.T / BP
    if base == "forwards":
        b_fwd, b_view, b_today = np.zeros(3), b_view - b_fwd, -b_fwd
    else:
        b_today = np.zeros(3)
    sig = basis.vols / BP * np.sqrt(max(H, 1 / 12))
    spanL = max(2.5 * sig[0], 1.25 * max(abs(b_fwd[0]), abs(b_view[0]), abs(b_today[0])), 25)
    spanS = max(2.5 * sig[1], 1.25 * max(abs(b_fwd[1]), abs(b_view[1]), abs(b_today[1])), 15)
    spanL, spanS = float(np.ceil(spanL / 5) * 5), float(np.ceil(spanS / 5) * 5)
    L = np.linspace(-spanL, spanL, n)
    S = np.linspace(-spanS, spanS, n)
    LL, SS = np.meshgrid(L, S)
    c = context(book, path, infl, H, base)

    def fn(tau):
        ld = basis.loadings(tau)
        return c.nominal(tau)[None, :] + (LL.reshape(-1)[:, None] * ld[None, :, 0] + SS.reshape(-1)[:, None] * ld[None, :, 1]) * BP

    Z = pnl(book, H, c, nominal_fn=fn).reshape(n, n)
    return {"base": base, "level": L.tolist(), "slope": S.tolist(), "pnl": Z.tolist(),
            "markers": {"today": b_today[:2].tolist(), "forwards": b_fwd[:2].tolist(), "view": b_view[:2].tolist()},
            "sigma": sig[:2].tolist(), "contours": levels or [{"key": "breakeven", "label": "Break even", "value": 0.0}],
            "space": "real" if real_only else ("nominal_be_held" if book.has_real else "nominal")}


def time_to_cover(book: Book, att, basis: FactorBasis, move_bp: float = 25.0) -> dict:
    """First t at which carry + roll-down covers an adverse move of `move_bp` applied at t.
    Adverse = parallel in the losing direction; for (near) duration-neutral books, slope."""
    z0 = book.z0
    t = att.t
    cr = att.carry + att.roll
    today = lambda tau: z0.z(tau)[None, :]
    dv01, _, fx, bk = book.exposures_at(0.0, today, basis)
    neutral = abs(dv01) < 0.05 * max(abs(fx[1]), abs(bk.sum()), 1e-9) or abs(dv01) < 1e-6 * book.gross_mv
    if neutral and book.has_real and abs(bk.sum()) > abs(fx[1]):
        return _cover_breakeven(book, att, move_bp)
    use_slope = neutral
    loss = np.zeros(len(t))
    cushion = np.full(len(t), np.nan)
    for n, tt in enumerate(t):
        d, _, f, _ = book.exposures_at(tt, today, basis)
        if use_slope:
            sgn, sens = (1.0 if f[1] > 0 else -1.0), abs(f[1])
            shape = lambda tau: basis.loadings(tau)[:, 1]
        else:
            sgn, sens = (1.0 if d > 0 else -1.0), abs(d)
            shape = lambda tau: np.ones_like(tau)
        base = book.pnl_at(tt, today)[0]
        shocked = book.pnl_at(tt, lambda tau: (z0.z(tau) - sgn * move_bp * BP * shape(tau))[None, :])[0]
        loss[n] = shocked - base
        cushion[n] = cr[n] / sens if sens > 0 else np.nan
    net = cr + loss
    t_star = None
    idx = np.where(net[1:] >= 0)[0]
    if len(idx):
        i = idx[0] + 1
        t_star = float(t[i - 1] + (t[i] - t[i - 1]) * (-net[i - 1]) / (net[i] - net[i - 1])) if net[i - 1] < 0 else float(t[i])
    return {"move_bp": move_bp, "kind": "slope" if use_slope else "parallel", "t_star": t_star,
            "loss": loss.tolist(), "cushion_bp": cushion.tolist(), "carry_roll": cr.tolist()}


def _cover_breakeven(book: Book, att, move_bp: float) -> dict:
    """Time-to-cover for inflation books that are rate-neutral: adverse parallel breakeven move."""
    z0, be0 = book.z0, book.be0
    t = att.t
    cr = att.carry + att.roll
    today = lambda tau: z0.z(tau)[None, :]
    loss = np.zeros(len(t))
    cushion = np.full(len(t), np.nan)
    for n, tt in enumerate(t):
        _, _, _, bk = book.exposures_at(tt, today)
        s = bk.sum()
        sgn = 1.0 if s > 0 else -1.0
        base = book.pnl_at(tt, today)[0]
        shocked = book.pnl_at(tt, today, be_fn=lambda tau: (be0.z(tau) - sgn * move_bp * BP)[None, :])[0]
        loss[n] = shocked - base
        cushion[n] = cr[n] / abs(s) if abs(s) > 0 else np.nan
    net = cr + loss
    t_star = None
    idx = np.where(net[1:] >= 0)[0]
    if len(idx):
        i = idx[0] + 1
        t_star = float(t[i - 1] + (t[i] - t[i - 1]) * (-net[i - 1]) / (net[i] - net[i - 1])) if net[i - 1] < 0 else float(t[i])
    return {"move_bp": move_bp, "kind": "breakeven", "t_star": t_star, "loss": loss.tolist(),
            "cushion_bp": cushion.tolist(), "carry_roll": cr.tolist()}
