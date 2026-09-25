"""Plain-English narrative generated from the analysis numbers."""
from __future__ import annotations

import numpy as np

from ..config import KEY_TENORS
from .attribution import BP

I2, I10 = KEY_TENORS.index(2.0), KEY_TENORS.index(10.0)


def _bp(x, gross):
    return x / gross * 1e4


def _f(x, d=0):
    return f"{x:+.{d}f}"


def _p(x_bp):
    """Return in bp -> signed percent, 2dp."""
    return f"{x_bp / 100:+.2f}%"


def _mo(t):
    m = t * 12
    return f"{m:.1f} months" if m < 24 else f"{t:.1f} years"


def _hz(H):
    m = round(H * 12)
    return f"{m}m" if m < 24 or m % 12 else f"{m // 12}y"


def narrative(out: dict, att, book, basis, H: float) -> dict:
    g = max(book.gross_mv, 1.0)
    bp = lambda x: _bp(float(x), g)
    carry, roll = bp(att.carry[-1]), bp(att.roll[-1])
    cr = carry + roll
    pm = bp(att.priced.total[-1])
    pin = bp(att.priced_in[-1])
    edge = bp(att.edge.total[-1] + att.spread[-1] + att.inflation[-1])
    total_basis = book.fin.basis == "total"
    over = "holding-period return" if total_basis else "excess return over financing"
    total = bp(att.total[-1])
    usd_total = float(att.total[-1])
    keys = out["keys"]
    today, fwd, user = np.array(keys["today"]), np.array(keys["fwd"][-1]), np.array(keys["user"][-1])
    f10 = (fwd[I10] - today[I10]) * 100
    f_2s10s = ((fwd[I10] - fwd[I2]) - (today[I10] - today[I2])) * 100
    e10 = (user[I10] - fwd[I10]) * 100
    e_2s10s = ((user[I10] - user[I2]) - (fwd[I10] - fwd[I2])) * 100
    hz = _hz(H)
    s = []

    verb = "earn" if cr >= 0 else "cost"
    what = "Coupon income, pull-to-par and roll-down" if total_basis else "Carry (net of financing) and roll-down"
    s.append(f"{what} {verb} {abs(cr) / 100:.2f}% over {hz} (carry {_p(carry)}, roll {_p(roll)}) if today's curve is unchanged.")

    steep = "steepening" if f_2s10s >= 0 else "flattening"
    move = "rise" if f10 >= 0 else "fall"
    s.append(f"The forwards price a {abs(f10):.0f}bp {move} in the 10y zero and {abs(f_2s10s):.0f}bp of 2s10s {steep}; "
             f"if realised that is worth {_p(pm)}, leaving {_p(pin)} {'in total' if total_basis else 'over financing'}.")

    # edge by factor, phrased against what is priced
    labels = basis.labels
    be = att.edge.beta[-1]
    bpz = att.priced.beta[-1]
    contrib = att.edge.factors[-1]
    parts = []
    for k in np.argsort(-np.abs(contrib)):
        c = bp(contrib[k])
        if abs(c) < max(0.5, 0.1 * abs(edge)):
            continue
        p, e = bpz[k], be[k]
        if k == 0:
            prior = f"price a {abs(p):.0f}bp {'rise' if p > 0 else 'fall'} in the level factor"
            mine = f"you are {abs(e):.0f}bp {'higher' if e > 0 else 'lower'}"
        elif k == 1:
            prior = f"price {abs(p):.0f}bp of {'steepening' if p > 0 else 'flattening'} in the slope factor"
            mine = f"you expect {abs(e):.0f}bp {'more steepening' if e > 0 else 'more flattening'}" if p * e > 0 or abs(p) < 0.5 \
                else f"you expect {abs(e):.0f}bp {'less flattening' if e > 0 else 'less steepening'}" if abs(e) <= abs(p) \
                else f"you expect {abs(e) - abs(p):.0f}bp of {'steepening' if e > 0 else 'flattening'} instead"
        else:
            prior = f"price {abs(p):.0f}bp of belly {'cheapening' if p > 0 else 'richening'}"
            mine = f"you are {abs(e):.0f}bp {'cheaper' if e > 0 else 'richer'} in the belly"
        parts.append(f"{prior}; {mine}, worth {_p(c)}")
    if abs(edge) < 0.5:
        s.append("Your path is essentially the forwards: nothing comes from a view versus what is priced.")
    else:
        lead = f"Your view versus the forwards adds {_p(edge)} (10y {_f(e10)}bp vs forward, 2s10s {_f(e_2s10s)}bp)."
        s.append(lead)
        if edge > 0 and pm < 0:
            s.append("Caveat: the forwards embed term premium, so part of this can be compensation for bearing "
                     "duration risk rather than a forecasting edge.")
        if parts:
            s.append("By factor: " + " — ".join(("the forwards " if i == 0 else "they ") + p for i, p in enumerate(parts[:2])) + ".")
    other = bp(att.edge.other[-1])
    if abs(other) > max(1.0, 0.25 * abs(edge)):
        s.append(f"{_p(other)} of it comes from curve shape outside level/slope/curvature.")
    if book.has_real:
        inf = bp(att.inflation[-1])
        rep = (out.get("inflation") or {})
        cu, cm = rep.get("horizon_user_yoy"), rep.get("horizon_mkt_yoy")
        if cu is not None and cm is not None:
            s.append(f"Inflation: you expect CPI of {cu:.2f}% a year to horizon vs {cm:.2f}% priced by breakevens; "
                     f"on the TIPS accrual that is worth {_p(inf)}.")
    if book.be0 is not None:
        fr, fb = bp(att.curve.fo_real[-1]), bp(att.curve.fo_be[-1])
        if abs(fr) + abs(fb) > 1:
            s.append(f"Of the first-order curve change vs today, real yields contribute {_p(fr)} and breakevens {_p(fb)}.")

    s.append(f"Expected {over}: {_p(total)} (${usd_total:,.0f}).")

    bev = out["breakevens"]
    pt, pf = bev["today"]["parallel"], bev["forwards"]["parallel"]
    if pt is not None:
        dirn = "selloff" if pt > 0 else "rally"
        extra = f" ({abs(pf):.0f}bp {'selloff' if pf > 0 else 'rally'} vs the forwards)" if pf is not None else ""
        s.append(f"Break-even: a {abs(pt):.0f}bp parallel {dirn} from today's curve{extra} makes the {over} zero.")
    else:
        st = bev["today"]["slope"]
        if st is not None:
            s.append(f"No parallel break-even (the position is level-neutral); slope break-even: "
                     f"{abs(st):.0f}bp of 2s10s {'steepening' if st > 0 else 'flattening'} vs today.")
    cv = out["cover"]
    if cv["t_star"] is not None:
        s.append(f"Carry and roll cover a {cv['move_bp']:.0f}bp adverse {cv['kind']} move after {_mo(cv['t_star'])}.")
    else:
        s.append(f"Carry and roll do not cover a {cv['move_bp']:.0f}bp adverse {cv['kind']} move within {hz}.")
    rk = out["risk"]
    if rk.get("sigma"):
        sig = bp(rk["sigma"])
        s.append(f"Horizon 1σ ≈ ±{sig / 100:.2f}% from historical curve vol; expected return per unit of vol {rk['ratio']:.2f}.")
    headline = f"{_p(total)} over {hz}: {_p(cr)} carry & roll, {_p(pm)} priced-in move, {_p(edge)} from your view vs forwards"
    return {"headline": headline, "sentences": s}
