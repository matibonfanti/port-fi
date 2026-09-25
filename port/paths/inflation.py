"""Inflation views: an expected breakeven path B_u(t, tau) and a realised CPI index path I_u(t).

Market-implied (the "priced" reference, not a forecast):
    breakevens at date t      Bf(t, tau) = forward breakeven = F_nominal(t, tau) − F_real(t, tau)
    index ratio accrual       I_F(t)     = exp(b0(t)·t) = DF_real(t) / DF_nominal(t)
Modes:
    priced        B_u = Bf,             I_u = I_F
    unchanged     B_u = b0 (today),     I_u = I_F
    nodes         B_u = anchor + your deviation nodes (drag / table), I_u from a flat CPI rate (or priced)
    expectations  you set average CPI inflation per bucket (year 1, year 2, years 3–5, 6–10, 11–30);
                  δ(s) = your − priced (cc, per bucket)
                  I_u(t)    = I_F(t) · exp(∫_0^t δ)                                  (realised)
                  B_u(t, τ) = Bf(t, τ) + λ(t)·(1/τ)∫_t^{t+τ} δ + ΔIRP(τ)·min(1, t/H)   (priced at t)
Your curve for real rates is R_u = Z_u (nominal path) − B_u.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..config import KEY_TENORS
from ..curves.interp import pchip
from ..curves.zero_curve import BreakevenCurve
from .path import ExpectationPath

KT = np.array(KEY_TENORS)
BP = 1e-4
BUCKETS = [(0.0, 1.0, "Year 1"), (1.0, 2.0, "Year 2"), (2.0, 5.0, "Years 3–5"), (5.0, 10.0, "Years 6–10 (5y5y)"),
           (10.0, 30.0, "Years 11–30")]
IRP_TENORS = [2.0, 5.0, 10.0, 30.0]


@dataclass
class InflationScenario:
    be0: BreakevenCurve
    be_path: ExpectationPath
    index_fn: object            # s -> I_u(s)
    mode: str
    report: dict

    def index_F(self, s):
        s = np.asarray(s, float)
        return np.exp(self.be0.z(s) * s)

    def be_curve(self, t, tau):
        return self.be_path.curve(self.be0, t, tau)


def _bucket_avg_cc(be0, a, b):
    return (b * float(be0.z(b)) - a * float(be0.z(a))) / (b - a)


def build(spec: dict | None, be0: BreakevenCurve, nominal_anchor: str, H: float) -> InflationScenario:
    spec = spec or {}
    mode = spec.get("mode", "follow")
    if mode == "follow":
        mode = "unchanged" if nominal_anchor == "today" else "priced"
    index_F = lambda s: np.exp(be0.z(np.asarray(s, float)) * np.asarray(s, float))
    mkt = [{"label": lab, "a": a, "b": b, "mkt_cc": _bucket_avg_cc(be0, a, b)} for a, b, lab in BUCKETS]
    for m in mkt:
        m["mkt_yoy"] = (np.exp(m["mkt_cc"]) - 1) * 100
    report = {"mode": mode, "buckets": mkt, "horizon_mkt_yoy": (np.exp(float(be0.z(H))) - 1) * 100}

    if mode == "priced":
        path, index = ExpectationPath("forwards"), index_F
    elif mode == "unchanged":
        path, index = ExpectationPath("today"), index_F
    elif mode == "nodes":
        path = ExpectationPath.from_dict({"anchor": spec.get("anchor", "forwards"), "nodes": spec.get("nodes") or [],
                                          "time_interp": spec.get("time_interp", "pchip")})
        cpi = spec.get("cpi_pct")
        if cpi is None:
            index = index_F
        else:
            rc = np.log1p(float(cpi) / 100)
            index = lambda s, rc=rc: np.exp(rc * np.asarray(s, float))
    elif mode == "expectations":
        user = spec.get("buckets") or [m["mkt_yoy"] for m in mkt]
        edges = np.array([m["a"] for m in mkt] + [mkt[-1]["b"]])
        delta = np.array([np.log1p(float(u) / 100) - m["mkt_cc"] for u, m in zip(user, mkt)])
        cum_edges = np.concatenate([[0.0], np.cumsum(delta * np.diff(edges))])

        def cum(s):
            s = np.asarray(s, float)
            k = np.clip(np.searchsorted(edges, s, side="right") - 1, 0, len(delta) - 1)
            return cum_edges[k] + delta[k] * (np.minimum(s, edges[-1]) - edges[k]) + delta[-1] * np.maximum(s - edges[-1], 0)

        T_conv = float(spec.get("convergence_months", 3.0)) / 12
        irp = spec.get("irp") or {}
        irp_v = np.array([float(irp.get(str(int(k)), irp.get(k, 0.0)) or 0.0) for k in IRP_TENORS])
        irp_curve = lambda tau: pchip(np.array([0.0] + IRP_TENORS), np.concatenate([[0.0], irp_v])[None, :],
                                      np.asarray(tau, float))[0] * BP
        months = np.arange(1, int(np.floor(H * 12 + 1e-9)) + 1) / 12.0
        nt = np.unique(np.round(np.concatenate([months, [H]]), 6))
        nt = nt[nt > 0]
        lam = np.ones_like(nt) if T_conv <= 0 else np.minimum(1.0, nt / T_conv)
        dev = (lam[:, None] * (cum(nt[:, None] + KT[None, :]) - cum(nt[:, None])) / KT[None, :]
               + irp_curve(KT)[None, :] * np.minimum(1.0, nt / H)[:, None]) / BP
        path = ExpectationPath("forwards", nt, dev, None, "linear")
        index = lambda s: index_F(s) * np.exp(cum(s))
        for m, u in zip(mkt, user):
            m["user_yoy"] = float(u)
        report.update({"irp": irp_v.tolist(), "irp_tenors": IRP_TENORS, "convergence_months": T_conv * 12,
                       "nodes": path.to_nodes()})
    else:
        raise ValueError(f"unknown inflation mode {mode}")
    for m in mkt:
        m.setdefault("user_yoy", m["mkt_yoy"] if mode in ("priced", "unchanged", "nodes") else m["mkt_yoy"])
    iu, iF = float(index(np.array([H]))[0]), float(index_F(np.array([H]))[0])
    report["horizon_user_yoy"] = (iu ** (1 / H) - 1) * 100 if H > 0 else None
    report["horizon_mkt_yoy"] = (iF ** (1 / H) - 1) * 100 if H > 0 else None
    return InflationScenario(be0, path, index, mode, report)


class FisherPath:
    """Your nominal path with a share w of your breakeven view passed through to nominal yields:
        Z'(t, τ) = Z_u(t, τ) + w · (B_u(t, τ) − B_base(t, τ))
    B_base is the breakeven path implied by the nominal anchor alone (today → b0, forwards → Bf).
    w = 0: nominal yields are exactly what you set, real yields absorb the breakeven change.
    w = 1: real yields are held (relative to your nominal view); nominal yields move with breakevens.
    Exposes the ExpectationPath interface used by the engine."""

    def __init__(self, path: ExpectationPath, infl: InflationScenario, w: float):
        self.path, self.infl, self.w = path, infl, float(w)
        self.anchor = path.anchor
        self.time_interp = path.time_interp
        self.node_t, self.node_dev, self.spread_dev = path.node_t, path.node_dev, path.spread_dev
        self._base = ExpectationPath(path.anchor)

    def passthrough(self, t, tau):
        t = np.atleast_1d(np.asarray(t, float))
        tau = np.asarray(tau, float)
        if tau.ndim == 1:
            tau = np.broadcast_to(tau, (len(t), len(tau)))
        be0 = self.infl.be0
        return self.w * (self.infl.be_curve(t, tau) - self._base.curve(be0, t, tau))

    def curve(self, z0, t, tau):
        return self.path.curve(z0, t, tau) + self.passthrough(t, tau)

    def spread(self, t):
        return self.path.spread(t)

    def dev_knots(self, t):
        """Deviation vs the nominal anchor at key tenors (bp), including the pass-through."""
        return self.path.dev_knots(t) + self.passthrough(t, KT) / BP

    def anchor_curve(self, z0, t, tau):
        return self.path.anchor_curve(z0, t, tau)
