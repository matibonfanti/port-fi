"""Positions: items (bond, TIPS, steepener, flattener, butterfly, breakeven) expanded into weighted
bond lines, plus the financing / return-basis assumption."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import numpy as np

from ..config import parse_date
from .bond import Bond, generic_bond

BP = 1e-4


@dataclass
class Line:
    bond: Bond
    face: float                 # $mm face, signed (+ long). For TIPS: inflation-adjusted face at valuation.
    spread: float = 0.0         # Z-spread over the fitted curve, decimal (cc)
    label: str = ""
    item: str = ""
    role: str = ""
    credit: bool = False        # spread path applies
    real: bool = False          # inflation-linked (TIPS): real cash flows × index ratio
    t: np.ndarray = field(default=None, repr=False)
    c: np.ndarray = field(default=None, repr=False)

    def attach(self, settle: dt.date):
        self.t, self.c, _ = self.bond.cashflows(settle)
        return self


@dataclass
class Financing:
    """basis 'excess': P&L over financing the dirty price (repo / cash account G).
       basis 'total' : plain holding-period return — no financing of the principal; coupons are
                       reinvested at the same rate G (flat cash rate, or the implied short-rate path)."""
    mode: str = "flat"          # "flat" | "implied"
    rate_pct: float = 4.0       # flat: money-market rate, ACT/360 simple, for the horizon term
    spread_bp: float = 0.0      # implied: spread over the implied short-rate path
    basis: str = "excess"       # "excess" | "total"

    def growth(self, z0, t, horizon: float) -> np.ndarray:
        t = np.asarray(t, float)
        if self.mode == "implied":
            return np.exp(self.spread_bp * BP * t) / z0.df(t)
        return np.exp(self.cc_rate(horizon) * t)

    def cc_rate(self, horizon: float) -> float:
        h = max(horizon, 1 / 365)
        return float(np.log1p(self.rate_pct / 100 * h * 365 / 360) / h)

    @staticmethod
    def mm_from_cc(r_cc: float, horizon: float) -> float:
        h = max(horizon, 1 / 365)
        return float(np.expm1(r_cc * h) / (h * 365 / 360) * 100)

    @classmethod
    def from_dict(cls, d: dict | None) -> "Financing":
        d = d or {}
        return cls(d.get("mode", "flat"), float(d.get("rate_pct", 4.0)), float(d.get("spread_bp", 0.0)),
                   d.get("basis", "excess"))


# ----------------------------------------------------------------------------------- pricing
def price(t, c, curve, spread=0.0) -> float:
    return float(c @ np.exp(-(curve.z(t) + spread) * t))


def own_yield(t, c, p) -> float:
    """Continuously-compounded yield y with sum c exp(-y t) = p."""
    y = 0.04
    for _ in range(100):
        d = np.exp(-y * t)
        f = c @ d - p
        if abs(f) < 1e-14:
            break
        y -= f / (-(c * t) @ d)
    return float(y)


def par_coupon(curve, tenor: float, floor: float = 0.0) -> float:
    """Par coupon for a new generic bond, rounded to 1/8 of a percent (Treasury auction style)."""
    y = float(curve.par_yield(np.array([max(tenor, 1.0)]))[0])
    return max(floor, np.round(y * 100 * 8) / 8 / 100)


@dataclass
class Context:
    settle: dt.date
    z0: object                      # nominal curve
    r0: object | None = None        # real curve (None before 2003)
    otr: list = field(default_factory=list)
    otr_tips: list = field(default_factory=list)
    flags: list = field(default_factory=list)


def resolve_bond(spec: dict, ctx: Context, real: bool = False) -> Bond:
    curve = ctx.r0 if real else ctx.z0
    book = ctx.otr_tips if real else ctx.otr
    kind = "TIPS" if real else "Treasury"
    if spec.get("otr"):
        term = float(spec["otr"])
        for o in book:
            if o["term"] == term:
                return Bond(parse_date(o["maturity"]), o["coupon"] / 100, label=o["label"])
        ctx.flags.append({"level": "warn", "code": "otr_missing",
                          "msg": f"No on-the-run {term:g}Y {kind} available for {ctx.settle}; using a generic "
                                 f"{term:g}Y par-coupon bond instead."})
        spec = {"tenor": term, "coupon": None}
    pre = "TII " if real else ""
    if spec.get("maturity"):
        mat = parse_date(spec["maturity"])
        if mat <= ctx.settle:
            raise ValueError(f"maturity {mat} is not after the valuation date {ctx.settle}")
        cpn = spec.get("coupon")
        tenor = (mat - ctx.settle).days / 365.0
        cpn = par_coupon(curve, tenor, 0.00125 if real else 0.0) if cpn is None else float(cpn) / 100
        return Bond(mat, cpn, label=spec.get("label") or f"{pre}{cpn*100:g}% {mat:%m/%d/%y}")
    tenor = float(spec.get("tenor", 10))
    if tenor <= 0:
        raise ValueError("tenor must be positive")
    cpn = spec.get("coupon")
    cpn = par_coupon(curve, tenor, 0.00125 if real else 0.0) if cpn is None else float(cpn) / 100
    b = generic_bond(ctx.settle, tenor, cpn)
    b.label = spec.get("label") or f"{pre}{tenor:g}y {cpn*100:.3f}%".replace("0%", "%")
    return b


def dv01_unit(line: Line, curve) -> float:
    """Price change per 1bp parallel rise in the line's own discount curve, per 1 face (positive)."""
    d = np.exp(-(curve.z(line.t) + line.spread) * line.t)
    return float((line.c * line.t * d).sum() * BP)


def factor_expo_unit(line: Line, curve, basis) -> np.ndarray:
    d = np.exp(-(curve.z(line.t) + line.spread) * line.t)
    return (line.c * line.t * d) @ basis.loadings(line.t) * BP


def build_lines(items: list[dict], ctx: Context, pca_basis) -> list[Line]:
    """Expand position items into signed, weighted lines."""
    z0 = ctx.z0
    lines: list[Line] = []

    def need_real(what):
        if ctx.r0 is None:
            raise ValueError(f"{what} needs the TIPS real yield curve, which is only published from 2003-01-02; "
                             f"no real curve exists for {ctx.settle}.")

    for k, it in enumerate(items):
        kind = it.get("kind", "bond")
        name = it.get("label") or kind
        size = float(it.get("size_mm", it.get("face_mm", 1.0)))
        spread = float(it.get("spread_bp", 0.0)) * BP
        credit = bool(it.get("credit", spread != 0.0))
        weighting = it.get("weighting", "dv01")

        def mk(spec, face, role, real=False):
            b = resolve_bond(spec, ctx, real)
            return Line(b, face, 0.0 if real else spread, b.label, name, role, credit and not real, real).attach(ctx.settle)

        curve_of = lambda ln: ctx.r0 if ln.real else z0
        if kind == "bond":
            lines.append(mk(it["bond"], float(it.get("face_mm", 1.0)), "outright"))
            continue
        if kind == "tips":
            need_real("A TIPS position")
            lines.append(mk(it["bond"], float(it.get("face_mm", 1.0)), "outright", real=True))
            continue
        legs = it["legs"]
        if kind == "breakeven":
            need_real("A breakeven trade")
            tips = mk(legs[0], 1.0, "TIPS leg", real=True)
            nom = mk(legs[1], 1.0, "nominal leg")
            sgn = 1.0 if it.get("direction", "long") == "long" else -1.0   # long BE = long TIPS, short nominal
            tips.face = sgn * size
            if weighting == "manual":
                nom.face = float(legs[1].get("face_mm", -tips.face))
            elif weighting == "notional":
                nom.face = -tips.face * (tips.c @ np.exp(-ctx.r0.z(tips.t) * tips.t)) / (nom.c @ np.exp(-z0.z(nom.t) * nom.t))
            else:
                nom.face = -tips.face * dv01_unit(tips, ctx.r0) / dv01_unit(nom, z0)
            lines += [tips, nom]
        elif kind in ("steepener", "flattener"):
            front = mk(legs[0], 1.0, "front leg")
            back = mk(legs[1], 1.0, "back leg")
            if weighting == "manual":
                front.face, back.face = float(legs[0].get("face_mm", 1)), float(legs[1].get("face_mm", -1))
            else:
                if weighting == "pca":
                    xf, xb = factor_expo_unit(front, z0, pca_basis)[0], factor_expo_unit(back, z0, pca_basis)[0]
                else:
                    xf, xb = dv01_unit(front, z0), dv01_unit(back, z0)
                sgn = 1.0 if kind == "steepener" else -1.0      # steepener: long front, short back
                back.face = -sgn * size
                front.face = sgn * size * xb / xf
            lines += [front, back]
        elif kind == "butterfly":
            w1, belly, w2 = mk(legs[0], 1.0, "wing"), mk(legs[1], 1.0, "belly"), mk(legs[2], 1.0, "wing")
            if weighting == "manual":
                for ln, lg in zip((w1, belly, w2), legs):
                    ln.face = float(lg.get("face_mm", 1))
            else:
                sgn = -1.0 if it.get("direction", "short_belly") == "short_belly" else 1.0
                belly.face = sgn * size
                if weighting == "pca":
                    E = np.array([factor_expo_unit(x, z0, pca_basis)[:2] for x in (w1, w2)]).T
                    eb = factor_expo_unit(belly, z0, pca_basis)[:2]
                    w1.face, w2.face = np.linalg.solve(E, -belly.face * eb)
                else:
                    xb = dv01_unit(belly, z0)
                    w1.face = -0.5 * belly.face * xb / dv01_unit(w1, z0)
                    w2.face = -0.5 * belly.face * xb / dv01_unit(w2, z0)
            lines += [w1, belly, w2]
        else:
            raise ValueError(f"unknown item kind {kind}")
    for ln in lines:
        if ln.t is None or len(ln.t) == 0:
            raise ValueError(f"{ln.label} has no cash flows after {ctx.settle}")
    return lines
