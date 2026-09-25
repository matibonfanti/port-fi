"""Zero curves: nominal (fitted to CMT par yields), breakeven and real (fitted to TIPS real par yields).

Representation: continuously-compounded zero rates z_k at the instrument tenors, joined by a
natural cubic spline in maturity, flat beyond the first/last knot. Instruments:
  * tenor <= 6m : Treasury bill, bond-equivalent simple yield  DF = 1 / (1 + y tau)
  * tenor >= 1y : par bond, semi-annual coupon y/2, priced at par (dirty = clean at a coupon date)
The zero knots solve price(instrument) = target exactly (Newton, analytic Jacobian).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np

from .interp import NaturalCubic, spline_basis

BILL_MAX = 0.5 + 1e-9


@lru_cache(maxsize=64)
def _structure(tenors: tuple):
    """Instrument cash-flow times and spline bases — depend only on the tenor set."""
    ten = np.array(tenors)
    out = []
    for tau in ten:
        if tau <= BILL_MAX:
            out.append(None)
            continue
        n = int(round(tau * 2))
        t = np.arange(1, n + 1) / 2.0
        out.append((t, spline_basis(ten, t)))
    return out


def fit_zero_knots(tenors, yields, z_init=None, tol=1e-13, max_iter=50) -> np.ndarray:
    """Solve for cc zero rates at `tenors` reproducing the par/bill yields exactly."""
    tenors = np.asarray(tenors, float)
    yields = np.asarray(yields, float)
    flows = _structure(tuple(np.round(tenors, 12)))
    bill = np.array([f is None for f in flows])
    z = np.empty(len(tenors))
    # bills pin their own knot directly
    z[bill] = np.log1p(yields[bill] * tenors[bill]) / tenors[bill]
    if z_init is not None:
        z[~bill] = np.asarray(z_init)[~bill]
    else:
        z[~bill] = 2 * np.log1p(yields[~bill] / 2)
    if bill.all():
        return z
    idx = np.where(~bill)[0]
    for _ in range(max_iter):
        res = np.empty(len(idx))
        jac = np.zeros((len(idx), len(tenors)))
        for r, i in enumerate(idx):
            t, B = flows[i]
            c = np.full(len(t), yields[i] / 2.0)
            c[-1] += 1.0
            zt = B @ z
            df = np.exp(-zt * t)
            res[r] = c @ df - 1.0
            jac[r] = -(c * t * df) @ B
        if np.max(np.abs(res)) < tol:
            break
        step = np.linalg.solve(jac[:, idx], -res)
        z[idx] += step
    return z


class CurveOps:
    """Shared curve algebra. Subclasses provide z(tau) (cc zero rate, flat extrapolation) and dz(tau)."""

    def df(self, tau):
        tau = np.asarray(tau, float)
        return np.exp(-self.z(tau) * tau)

    def fwd_inst(self, s):
        """Instantaneous forward f(0,s) = d/ds [s z(s)]."""
        s = np.asarray(s, float)
        return self.z(s) + s * self.dz(s)

    def fwd(self, t, tau):
        """Forward zero rate F(t, tau) for [t, t+tau] seen from today (cc); tau -> 0: instantaneous.
        Linear in z, so fwd(nominal) − fwd(real) = fwd(breakeven) exactly."""
        t = np.asarray(t, float)
        tau = np.asarray(tau, float)
        t, tau = np.broadcast_arrays(t, tau)
        small = tau < 1e-8
        tt = np.where(small, 1.0, tau)
        out = ((t + tt) * self.z(t + tt) - t * self.z(t)) / tt
        if small.any():
            out = np.where(small, self.fwd_inst(t), out)
        return out

    def par_yield(self, tau):
        """Model par yield (semi-annual, bond-equivalent) for tenors >= 1y; simple bill yield below."""
        tau = np.atleast_1d(np.asarray(tau, float))
        out = np.empty_like(tau)
        for i, T in enumerate(tau):
            if T <= BILL_MAX:
                out[i] = (1 / self.df(T) - 1) / T
            else:
                n = int(round(T * 2))
                t = np.arange(1, n + 1) / 2.0
                d = self.df(t)
                out[i] = 2 * (1 - d[-1]) / d.sum()
        return out


class SplineCurve(CurveOps):
    """Natural cubic spline in maturity through knot values, flat beyond the first/last knot."""

    def __init__(self, knots, values, date=None, par_tenors=None, par_yields=None):
        self.knots = np.asarray(knots, float)
        self.zeros = np.asarray(values, float)
        self.date = date
        self.par_tenors = None if par_tenors is None else np.asarray(par_tenors, float)
        self.par_yields = None if par_yields is None else np.asarray(par_yields, float)
        self._cs = NaturalCubic(self.knots, self.zeros) if len(self.knots) > 1 else None

    def z(self, tau):
        tau = np.asarray(tau, float)
        if self._cs is None:
            return np.full(tau.shape, self.zeros[0])
        return self._cs(tau)

    def dz(self, tau):
        tau = np.asarray(tau, float)
        return np.zeros(tau.shape) if self._cs is None else self._cs.deriv(tau)


class ZeroCurve(SplineCurve):
    """Nominal cc zero curve."""

    @classmethod
    def from_par(cls, tenors, yields, date=None) -> "ZeroCurve":
        tenors = np.asarray(tenors, float)
        yields = np.asarray(yields, float)
        z = fit_zero_knots(tenors, yields)
        return cls(tenors, z, date, tenors, yields)


class BreakevenCurve(SplineCurve):
    """Zero-coupon breakeven inflation b(tau) = z_nominal(tau) − z_real(tau), cc.
    Knots at the TIPS tenors; held flat below the shortest TIPS tenor (flagged in the UI)."""


class RealCurve(CurveOps):
    """Real zero curve implied by nominal − breakeven."""

    def __init__(self, nominal: CurveOps, be: CurveOps):
        self.nominal, self.be = nominal, be
        self.par_tenors = getattr(be, "par_tenors", None)
        self.par_yields = getattr(be, "par_yields", None)

    def z(self, tau):
        return self.nominal.z(tau) - self.be.z(tau)

    def dz(self, tau):
        return self.nominal.dz(tau) - self.be.dz(tau)


def fit_breakeven(nominal: CurveOps, tenors, real_yields, b_init=None, tol=1e-13, max_iter=60) -> BreakevenCurve:
    """Breakeven knots at the TIPS tenors so that real par bonds (semi-annual real coupon, discounted on
    z_nominal − b) price at par exactly. Newton with an analytic Jacobian."""
    tenors = np.asarray(tenors, float)
    y = np.asarray(real_yields, float)
    flows = []
    for T in tenors:
        n = int(round(T * 2))
        t = np.arange(1, n + 1) / 2.0
        flows.append((t, spline_basis(tenors, t) if len(tenors) > 1 else np.ones((n, 1))))
    zn = [nominal.z(t) for t, _ in flows]
    b = np.asarray(b_init, float).copy() if b_init is not None else np.array(
        [float(nominal.z(T)) - 2 * np.log1p(yy / 2) for T, yy in zip(tenors, y)])
    for _ in range(max_iter):
        res = np.empty(len(tenors))
        jac = np.empty((len(tenors), len(tenors)))
        for i, (t, B) in enumerate(flows):
            c = np.full(len(t), y[i] / 2.0)
            c[-1] += 1.0
            bt = B @ b
            d = np.exp(-(zn[i] - bt) * t)
            res[i] = c @ d - 1.0
            jac[i] = (c * t * d) @ B
        if np.max(np.abs(res)) < tol:
            break
        b = b + np.linalg.solve(jac, -res)
    return BreakevenCurve(tenors, b, getattr(nominal, "date", None), tenors, y)


# ---------------------------------------------------------------------------------------
# Smoothed fit: penalised least squares on the instantaneous forward curve.
# ---------------------------------------------------------------------------------------
FIT_KNOTS = np.array([1 / 12, 0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 7.0, 10.0, 15.0, 20.0, 30.0])
FIT_LAMBDA = 2e-4        # roughness weight on ∫ f''(s)^2 ds, errors in bp (see methodology)
BILL_WEIGHT = 0.3         # bills are noisier than coupons (supply, debt-ceiling, month-end)


@lru_cache(maxsize=64)
def _smooth_structure(tenors: tuple, knots: tuple):
    kn = np.array(knots)
    ten = np.array(tenors)
    inst = []
    for tau in ten:
        if tau <= BILL_MAX:
            inst.append(("bill", np.array([tau]), spline_basis(kn, [tau])))
        else:
            n = int(round(tau * 2))
            t = np.arange(1, n + 1) / 2.0
            inst.append(("bond", t, spline_basis(kn, t)))
    # roughness: second differences of f(s) = z(s) + s z'(s) on a monthly grid
    g = np.linspace(kn[0], kn[-1], 360)
    cs = NaturalCubic(kn, np.eye(len(kn)))
    Af = cs(g) + g[:, None] * cs.deriv(g)
    h = g[1] - g[0]
    D2 = (Af[2:] - 2 * Af[1:-1] + Af[:-2]) / h**2
    R = D2 * np.sqrt(h)          # sum R^2 ≈ ∫ f''(s)^2 ds
    return inst, R


def _model_yields(inst, k):
    y = np.empty(len(inst))
    J = np.empty((len(inst), len(k)))
    for i, (kind, t, S) in enumerate(inst):
        D = np.exp(-(S @ k) * t)
        if kind == "bill":
            y[i] = (1 / D[0] - 1) / t[0]
            J[i] = S[0] / D[0]
        else:
            A = D.sum()
            y[i] = 2 * (1 - D[-1]) / A
            dD = -(t * D)[:, None] * S
            J[i] = 2 * (-dD[-1] * A - (1 - D[-1]) * dD.sum(0)) / A**2
    return y, J


def fit_smooth_knots(tenors, yields, knots=FIT_KNOTS, lam=FIT_LAMBDA, k_init=None, iters=30):
    tenors = np.asarray(tenors, float)
    yields = np.asarray(yields, float)
    kn = knots[knots <= tenors.max() + 1e-9]
    if kn[-1] < tenors.max() - 1e-9:
        kn = np.append(kn, tenors.max())
    inst, R = _smooth_structure(tuple(np.round(tenors, 12)), tuple(kn))
    w = np.where(tenors <= BILL_MAX, BILL_WEIGHT, 1.0)
    k = np.interp(kn, tenors, 2 * np.log1p(yields / 2)) if k_init is None else np.asarray(k_init, float)
    RtR = R.T @ R
    for _ in range(iters):
        y, J = _model_yields(inst, k)
        e = (y - yields) / BP_
        Jb = J / BP_
        A = Jb.T @ (w[:, None] * Jb) + lam * RtR / BP_**2 + 1e-10 * np.eye(len(k))
        b = Jb.T @ (w * e) + lam * RtR @ k / BP_**2
        step = np.linalg.solve(A, -b)
        step = step * min(1.0, 0.005 / max(np.max(np.abs(step)), 1e-16))   # cap 50bp per iteration
        k = k + step
        if np.max(np.abs(step)) < 1e-12:
            break
    return kn, k


BP_ = 1e-4


def fit_curve(tenors, yields, date=None, method: str = "smooth") -> "ZeroCurve":
    tenors = np.asarray(tenors, float)
    yields = np.asarray(yields, float)
    if method == "exact":
        return ZeroCurve.from_par(tenors, yields, date)
    kn, k = fit_smooth_knots(tenors, yields)
    return ZeroCurve(kn, k, date, tenors, yields)
