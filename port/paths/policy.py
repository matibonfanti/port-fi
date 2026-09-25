"""Policy-rate path builder.

Market-implied path: a step function of the overnight rate between FOMC decisions whose level on
each inter-meeting interval equals the average instantaneous forward over that interval, so it
integrates exactly to today's curve.  User path: the same starting level plus the user's moves per
meeting (or a smooth path, averaged per interval).  The deviation delta(s) = r_user(s) - r_mkt(s)
is a step function; after the last explicit meeting it decays to 0 with a half-life.

Expected curve at date t (compiled to deviation-vs-forwards nodes):
    D(t, tau) = (1/tau) * [ int_t^{min(t+tau, m*)} delta  +  lambda(t) * int_{min(t+tau, m*)}^{t+tau} delta ]
                + dTP(tau) * min(1, t/H)
  m* = next decision after t (the current rate is already set), lambda(t) = min(1, t/T_conv) is the
  speed at which the market converges to your path, dTP = your term-premium change vs what is priced.
"""
from __future__ import annotations

import datetime as dt

import numpy as np

from ..config import FOMC_MEETINGS, KEY_TENORS, parse_date, year_frac
from ..curves.interp import pchip
from ..curves.zero_curve import ZeroCurve

KT = np.array(KEY_TENORS)
BP = 1e-4
TP_TENORS = [2.0, 5.0, 10.0, 30.0]


def meetings_after(asof: dt.date, max_years: float = 3.0):
    """FOMC decisions within max_years of asof. Where the calendar has no dates (historical as-of
    dates, or far future) the schedule is filled with estimated meetings every 365/8 days."""
    out = []
    for d, est in FOMC_MEETINGS:
        dd = parse_date(d)
        eff = dd + dt.timedelta(days=1)  # decision effective the next day
        t = year_frac(asof, eff)
        if 0 < t <= max_years:
            out.append({"date": dd.isoformat(), "t": t, "estimated": est})
    last = parse_date(out[-1]["date"]) if out else asof - dt.timedelta(days=7)
    step = dt.timedelta(days=365.25 / 8)
    while True:
        last = last + step
        t = year_frac(asof, last + dt.timedelta(days=1))
        if t > max_years:
            break
        if t > 0:
            out.append({"date": last.isoformat(), "t": t, "estimated": True})
    return out


def _avg_fwd(z0: ZeroCurve, a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    return (b * z0.z(b) - a * z0.z(a)) / (b - a)


class PolicyPath:
    def __init__(self, z0: ZeroCurve, asof: dt.date, params: dict, horizon: float):
        self.z0, self.asof, self.H = z0, asof, horizon
        p = params or {}
        self.params = p
        span = max(2.0, min(3.0, horizon + 1.0))
        self.meet = meetings_after(asof, span)
        tm = np.array([m["t"] for m in self.meet])
        gap = np.diff(tm).mean() if len(tm) > 1 else 0.125
        self.edges = np.concatenate([[0.0], tm, [tm[-1] + gap]])     # interval k = [e_k, e_{k+1})
        self.r_mkt = _avg_fwd(self.z0, self.edges[:-1], self.edges[1:])   # (K+1,)
        self.mu = np.diff(self.r_mkt)                                       # market moves per meeting
        K = len(tm)
        mode = p.get("mode", "meetings")
        if mode == "smooth" and p.get("smooth"):
            pts = sorted(p["smooth"], key=lambda x: x["t"])
            x = np.array([0.0] + [q["t"] for q in pts])
            y = np.array([self.r_mkt[0]] + [q["level"] / 100 for q in pts])
            fine = np.linspace(0, self.edges[-1], 2000)
            ru = pchip(x, y[None, :], fine)[0]
            self.r_user = np.array([ru[(fine >= a) & (fine < b)].mean() if ((fine >= a) & (fine < b)).any()
                                    else float(pchip(x, y[None, :], np.array([a]))[0, 0])
                                    for a, b in zip(self.edges[:-1], self.edges[1:])])
            self.r_user[0] = self.r_mkt[0]
        else:
            moves = p.get("moves")
            if moves is None:
                u = self.mu * float(p.get("moves_scale", 1.0))
            else:
                u = np.array([(moves[k] if k < len(moves) and moves[k] is not None else self.mu[k] / BP) * BP
                              for k in range(K)])
            self.r_user = self.r_mkt[0] + np.concatenate([[0.0], np.cumsum(u)])
        self.u = np.diff(self.r_user)
        self.delta = self.r_user - self.r_mkt                  # step deviations (K+1,)
        hl = p.get("half_life", 2.0)
        self.half_life = None if hl in (None, 0, "hold") else float(hl)
        self.T_conv = float(p.get("convergence_months", 3.0)) / 12.0
        tp = p.get("tp") or {}
        self.tp = np.array([float(tp.get(str(int(k)), tp.get(k, 0.0)) or 0.0) for k in TP_TENORS])
        # cumulative integral of delta at interval edges
        self.cum_edges = np.concatenate([[0.0], np.cumsum(self.delta * np.diff(self.edges))])

    # ---------------------------------------------------------------- deviation integral
    def cum(self, s):
        """int_0^s delta(u) du (decimal-years)."""
        s = np.asarray(s, float)
        e = self.edges
        end = e[-1]
        k = np.clip(np.searchsorted(e, np.minimum(s, end), side="right") - 1, 0, len(self.delta) - 1)
        inside = self.cum_edges[k] + self.delta[k] * (np.minimum(s, end) - e[k])
        if self.half_life is None:
            tail = self.delta[-1] * np.maximum(s - end, 0)
        else:
            a = np.log(2) / self.half_life
            tail = self.delta[-1] / a * (1 - np.exp(-a * np.maximum(s - end, 0)))
        return inside + tail

    def next_meeting(self, t):
        t = np.asarray(t, float)
        e = self.edges[1:-1]
        idx = np.searchsorted(e, t, side="right")
        return np.where(idx < len(e), e[np.minimum(idx, len(e) - 1)], np.inf)

    def tp_curve(self, tau):
        x = np.array([0.0] + TP_TENORS)
        y = np.concatenate([[0.0], self.tp])
        return pchip(x, y[None, :], np.asarray(tau, float))[0] * BP

    def deviation(self, t, tau) -> np.ndarray:
        """D(t, tau) vs forwards (decimal). t: (N,), tau: (J,) -> (N, J)."""
        t = np.asarray(t, float)[:, None]
        tau = np.asarray(tau, float)[None, :]
        m = self.next_meeting(t[:, 0])[:, None]
        split = np.minimum(t + tau, np.maximum(m, t))
        known = self.cum(split) - self.cum(t)
        future = self.cum(t + tau) - self.cum(split)
        lam = np.ones_like(t) if self.T_conv <= 0 else np.minimum(1.0, t / self.T_conv)
        phi = np.minimum(1.0, t / self.H) if self.H > 0 else 1.0
        return (known + lam * future) / tau + self.tp_curve(tau[0])[None, :] * phi

    def node_times(self):
        H = self.H
        months = np.arange(1, int(np.floor(H * 12 + 1e-9)) + 1) / 12.0
        mt = self.edges[1:-1][self.edges[1:-1] < H]
        pts = np.unique(np.round(np.concatenate([months, mt, [H]]), 6))
        return pts[(pts > 0) & (pts <= H + 1e-9)]

    def compile(self) -> dict:
        nt = self.node_times()
        dev = self.deviation(nt, KT) / BP
        return {"anchor": "forwards", "time_interp": "linear",
                "nodes": [{"t": float(t), "dev": [float(x) for x in d]} for t, d in zip(nt, dev)]}

    # ---------------------------------------------------------------- report for the UI
    def report(self) -> dict:
        rows = []
        for k, m in enumerate(self.meet):
            rows.append({**m, "mkt_level": self.r_mkt[k + 1] * 100, "mkt_move_bp": self.mu[k] / BP,
                         "user_level": self.r_user[k + 1] * 100, "user_move_bp": self.u[k] / BP})
        s = np.linspace(0, max(self.H, 2.0), 200)
        def level_at(r, x):
            k = np.clip(np.searchsorted(self.edges, x, side="right") - 1, 0, len(r) - 1)
            return r[k]
        cum = {}
        for lab, h in (("3m", 0.25), ("6m", 0.5), ("12m", 1.0), ("24m", 2.0)):
            cum[lab] = {"mkt_bp": float((level_at(self.r_mkt, h) - self.r_mkt[0]) / BP),
                        "user_bp": float((level_at(self.r_user, h) - self.r_user[0]) / BP)}
        return {
            "r0": self.r_mkt[0] * 100, "meetings": rows, "cumulative": cum,
            "chart": {"s": s.tolist(), "fwd": (self.z0.fwd_inst(s) * 100).tolist(),
                      "mkt": (level_at(self.r_mkt, s) * 100).tolist(),
                      "user": (level_at(self.r_user, s) * 100).tolist()},
            "tp_tenors": TP_TENORS, "tp": self.tp.tolist(),
            "half_life": self.half_life, "convergence_months": self.T_conv * 12,
        }
