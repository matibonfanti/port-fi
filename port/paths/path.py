"""Expectation paths: the user's expected curve Z_u(t, tau) for every t in [0, H].

Canonical representation (every builder compiles to this):
    Z_u(t, tau) = A(t, tau) + D(t, tau)
    A(t, tau)   = z0(tau)         (anchor "today")   or   F(t, tau)  (anchor "forwards")
    D(t, .)     = PCHIP over key tenors of d(t), flat beyond the end tenors
    d_j(t)      = time interpolation (PCHIP or linear) through (0, 0), (t_1, d_j1), ..., (t_K, d_jK),
                  held constant after the last node.  D(0, .) = 0 pins the path to today.
Deviations are stored in basis points; curves are in decimals (cc zero rates).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..config import KEY_TENORS
from ..curves.interp import hermite_eval, linear_rows, pchip_slopes
from ..curves.zero_curve import ZeroCurve

KT = np.array(KEY_TENORS)
BP = 1e-4


@dataclass
class ExpectationPath:
    anchor: str = "forwards"                 # "forwards" | "today"
    node_t: np.ndarray = field(default_factory=lambda: np.zeros(0))
    node_dev: np.ndarray = field(default_factory=lambda: np.zeros((0, len(KEY_TENORS))))  # bp
    spread_dev: np.ndarray | None = None     # (K,) bp credit-spread change at nodes
    time_interp: str = "pchip"

    def __post_init__(self):
        t = np.asarray(self.node_t, float).reshape(-1)
        d = np.asarray(self.node_dev, float).reshape(len(t), len(KEY_TENORS)) if len(t) else np.zeros((0, len(KT)))
        keep = t > 1e-9
        t, d = t[keep], d[keep]
        order = np.argsort(t)
        self.node_t, self.node_dev = t[order], d[order]
        if self.spread_dev is not None and len(self.spread_dev):
            sd = np.asarray(self.spread_dev, float).reshape(-1)[keep][order]
            self.spread_dev = sd
        else:
            self.spread_dev = None

    # ------------------------------------------------------------------ time interpolation
    def _time_interp(self, values: np.ndarray, t) -> np.ndarray:
        """values: (K, M) at node times -> (len(t), M), pinned 0 at t=0, flat after last node."""
        t = np.atleast_1d(np.asarray(t, float))
        if len(self.node_t) == 0:
            return np.zeros((len(t), values.shape[1]))
        x = np.concatenate([[0.0], self.node_t])
        y = np.vstack([np.zeros((1, values.shape[1])), values]).T  # (M, K+1)
        if self.time_interp == "linear" or len(x) == 2:
            out = linear_rows(x, y, t)
        else:
            out = hermite_eval(x, y, pchip_slopes(x, y), t)
        return out.T

    def dev_knots(self, t) -> np.ndarray:
        """Deviation vs anchor at key tenors, bp: (len(t), J)."""
        return self._time_interp(self.node_dev, t)

    def spread(self, t) -> np.ndarray:
        """Credit-spread change (bp) at times t."""
        t = np.atleast_1d(np.asarray(t, float))
        if self.spread_dev is None:
            return np.zeros(len(t))
        return self._time_interp(self.spread_dev[:, None], t)[:, 0]

    # ------------------------------------------------------------------ curves
    def anchor_curve(self, z0: ZeroCurve, t, tau) -> np.ndarray:
        t = np.asarray(t, float)
        tau = np.asarray(tau, float)
        if self.anchor == "today":
            return np.broadcast_to(z0.z(tau), np.broadcast_shapes(t.shape, tau.shape)).copy()
        return z0.fwd(t, tau)

    def deviation(self, t, tau) -> np.ndarray:
        """D(t, tau) in decimals. t: (N,), tau: (N, M) row-aligned (or (M,) shared)."""
        t = np.atleast_1d(np.asarray(t, float))
        dk = self.dev_knots(t) * BP                    # (N, J)
        tau = np.asarray(tau, float)
        if tau.ndim == 1:
            tau = np.broadcast_to(tau, (len(t), len(tau)))
        return hermite_eval(KT, dk, pchip_slopes(KT, dk), tau)

    def curve(self, z0: ZeroCurve, t, tau) -> np.ndarray:
        """Z_u(t, tau). t: (N,), tau: (N, M) or (M,) -> (N, M)."""
        t = np.atleast_1d(np.asarray(t, float))
        tau = np.asarray(tau, float)
        if tau.ndim == 1:
            tau = np.broadcast_to(tau, (len(t), len(tau)))
        return self.anchor_curve(z0, t[:, None], tau) + self.deviation(t, tau)

    # ------------------------------------------------------------------ conversions
    def rebased(self, z0: ZeroCurve, anchor: str) -> "ExpectationPath":
        """Same node curves expressed vs another anchor (exact at the nodes)."""
        if anchor == self.anchor or len(self.node_t) == 0:
            return ExpectationPath(anchor, self.node_t.copy(), self.node_dev.copy(),
                                   None if self.spread_dev is None else self.spread_dev.copy(), self.time_interp)
        shift = (z0.fwd(self.node_t[:, None], KT[None, :]) - z0.z(KT)[None, :]) / BP  # F - z0 at nodes
        dev = self.node_dev + shift if self.anchor == "forwards" else self.node_dev - shift
        return ExpectationPath(anchor, self.node_t.copy(), dev,
                               None if self.spread_dev is None else self.spread_dev.copy(), self.time_interp)

    @classmethod
    def from_dict(cls, d: dict) -> "ExpectationPath":
        nodes = d.get("nodes") or []
        t = np.array([n["t"] for n in nodes], float)
        dev = np.array([n["dev"] for n in nodes], float) if nodes else np.zeros((0, len(KT)))
        sp = [n.get("spread", 0.0) for n in nodes]
        return cls(d.get("anchor", "forwards"), t, dev,
                   np.array(sp, float) if any(abs(x) > 0 for x in sp) else None,
                   d.get("time_interp", "pchip"))

    def to_nodes(self) -> list[dict]:
        out = []
        for k, t in enumerate(self.node_t):
            n = {"t": float(t), "dev": [float(x) for x in self.node_dev[k]]}
            if self.spread_dev is not None:
                n["spread"] = float(self.spread_dev[k])
            out.append(n)
        return out
