"""Horizon scenario contexts shared by break-evens, the inverse engine, heatmap and risk.

A context fixes what is NOT being solved for: the nominal base curve at H, the breakeven curve and the
CPI index path (TIPS lines only). Bases:
    today     nominal z0(τ),      breakevens b0(τ),       CPI as priced
    forwards  nominal F(H, τ),    breakevens Bf(H, τ),    CPI as priced
    view      nominal Z_u(H, τ),  breakevens B_u(H, τ),   CPI per your inflation view
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class Ctx:
    nominal: object      # tau -> (M,)
    be: object           # tau -> (M,) or None
    index: object        # s -> (M,) or None
    spread: float        # credit spread change (decimal)


def context(book, path, infl, H: float, base: str) -> Ctx:
    z0, be0 = book.z0, book.be0
    if base == "view":
        nominal = lambda tau: path.curve(z0, np.array([H]), tau)[0]
        be = (lambda tau: infl.be_curve(np.array([H]), tau)[0]) if infl is not None else None
        index = infl.index_fn if infl is not None else None
        spread = float(path.spread(np.array([H]))[0]) * 1e-4
    elif base == "forwards":
        nominal = lambda tau: z0.fwd(H, tau)
        be = (lambda tau: be0.fwd(H, tau)) if be0 is not None else None
        index, spread = None, 0.0
    else:
        nominal = lambda tau: z0.z(tau)
        be = (lambda tau: be0.z(tau)) if be0 is not None else None
        index, spread = None, 0.0
    return Ctx(nominal, be, index, spread)


def pnl(book, H, ctx: Ctx, nominal_fn=None, be_fn=None, index_fn=None):
    """P&L ($) at H under the context, with optional overrides returning (S, M) scenario arrays."""
    return book.pnl_at(H, nominal_fn or (lambda tau: ctx.nominal(tau)[None, :]), ctx.spread,
                       be_fn or ((lambda tau: ctx.be(tau)[None, :]) if ctx.be is not None else None),
                       index_fn or ctx.index)
