"""Return decomposition engine.

For every line (unit face) and every t in the grid, with tau_i = T_i − t for cash flows still alive.
Nominal lines discount on the nominal curves with index I ≡ 1. TIPS lines discount real cash flows on
the real curves and scale by the index ratio: priced I_F(t) = exp(b0(t)·t), yours I_u(t).
    V_y(t)  = I_F(t) Σ c_i exp(−y0 τ_i)                      own constant yield (y0 reprices P0 today)
    V_R(t)  = I_F(t) Σ c_i exp(−(z0(τ_i) + s0) τ_i)          today's unchanged curve, rolled down
    V_F(t)  = I_F(t) Σ c_i exp(−(F(t,τ_i) + s0) τ_i)         forwards realised
    V_U0(t) = I_F(t) Σ c_i exp(−(Z_u(t,τ_i) + s0) τ_i)       your curve path, spread unchanged
    V_U(t)  = I_F(t) Σ c_i exp(−(Z_u(t,τ_i) + s(t)) τ_i)     … incl. your spread path
    Cash_X(t) = G(t)·( −P0·[excess basis] + Σ_{T_i ≤ t} c_i I_X(T_i) / G(T_i) ),  X ∈ {F, u}
Components (exact telescoping):
    carry = V_y + Cash_F,  roll = V_R − V_y,  curve = V_U0 − V_R,  spread = V_U − V_U0,
    inflation = V_U·(I_u/I_F − 1) + Cash_u − Cash_F        (TIPS only: realised vs priced CPI)
    total = V_U·I_u/I_F + Cash_u = carry + roll + curve + spread + inflation
    priced_in = V_F + Cash_F = carry + roll + priced_move;   edge = total − priced_in
Each curve term X = V_b − V_a is split at its base a with Δ_i = Z_b(τ_i) − Z_a(τ_i):
    FO_i = −c_i τ_i DF_a,i Δ_i;  buckets_j = Σ_i h_j(τ_i) FO_i;  factors_k = β_k Σ_i (−c_i τ_i DF_a,i) L_k(τ_i)
    other = Σ FO − Σ factors;  convexity = ½ Σ c_i τ_i² DF_a,i Δ_i²;  residual = X − Σ FO − convexity
    real/breakeven: nominal lines FO_be = Σ_i FO_i·Δb_i/Δ_i (Δn = Δr + Δb), FO_real = FO − FO_be; TIPS: all real.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..config import BE_TENORS, KEY_TENORS
from ..curves.history import FactorBasis
from ..curves.interp import tent_weights
from ..instruments.position import Financing, Line, own_yield, price
from ..paths.path import ExpectationPath

KT = np.array(KEY_TENORS)
BT = np.array(BE_TENORS)
BP = 1e-4
MM = 1e6
EPS = 1e-9


@dataclass
class Split:
    """First-order split of one curve term (all arrays in $, shape (N, ...))."""
    total: np.ndarray
    fo: np.ndarray
    buckets: np.ndarray
    factors: np.ndarray
    other: np.ndarray
    convexity: np.ndarray
    residual: np.ndarray
    fo_real: np.ndarray
    fo_be: np.ndarray
    beta: np.ndarray          # (N, 3) factor moves (bp) of the nominal curve change at key tenors
    delta_knots: np.ndarray   # (N, J) nominal curve change at key tenors (bp)

    _SUM = ("total", "fo", "buckets", "factors", "other", "convexity", "residual", "fo_real", "fo_be")
    # note: for TIPS lines the factor split projects the real-curve change; `beta` reports nominal moves

    def __add__(self, o):
        return Split(**{k: getattr(self, k) + getattr(o, k) for k in self._SUM}, beta=self.beta, delta_knots=self.delta_knots)

    def scaled(self, k):
        return Split(**{n: getattr(self, n) * k for n in self._SUM}, beta=self.beta, delta_knots=self.delta_knots)


@dataclass
class Attribution:
    t: np.ndarray
    carry: np.ndarray
    roll: np.ndarray
    spread: np.ndarray
    inflation: np.ndarray
    total: np.ndarray
    priced_in: np.ndarray
    curve: Split
    edge: Split
    priced: Split
    per_line_total: np.ndarray
    gross_mv: float

    @property
    def edge_total(self):
        return self.edge.total + self.spread + self.inflation


class Book:
    """A position: lines with cash flows, today's prices/yields, financing and the curves."""

    def __init__(self, z0, lines: list[Line], fin: Financing, horizon: float, be0=None, r0=None):
        self.z0, self.lines, self.fin, self.horizon = z0, lines, fin, horizon
        self.be0, self.r0 = be0, r0
        self.P0 = np.array([price(l.t, l.c, self.curve_of(l), l.spread) for l in lines])
        self.y0 = np.array([own_yield(l.t, l.c, p) for l, p in zip(lines, self.P0)])
        self.face = np.array([l.face for l in lines])
        self.gross_mv = float(np.sum(np.abs(self.face * MM * self.P0)))
        self.has_real = any(l.real for l in lines)

    def curve_of(self, l: Line):
        return self.r0 if l.real else self.z0

    def index_F(self, s):
        s = np.asarray(s, float)
        return np.exp(self.be0.z(s) * s) if self.be0 is not None else np.ones_like(s)

    # ------------------------------------------------------------------ cash account
    def cash(self, i: int, t, idx_T=None) -> np.ndarray:
        """Cash account per unit face on the date grid t (N,). idx_T: index ratios at the coupon dates (M,)."""
        l = self.lines[i]
        t = np.atleast_1d(np.asarray(t, float))
        G_t = self.fin.growth(self.z0, t, self.horizon)
        G_T = self.fin.growth(self.z0, l.t, self.horizon)
        cT = l.c / G_T if idx_T is None else l.c * idx_T / G_T
        recv = l.t[None, :] <= t[:, None] + EPS
        base = -self.P0[i] if self.fin.basis == "excess" else -self.P0[i] / G_t
        return G_t * (base + (recv * cT[None, :]).sum(1))

    def cash_at(self, i: int, t: float, idx_T=None):
        """Cash account per unit face at one date t, for scenario index paths idx_T ((M,) or (S, M))."""
        l = self.lines[i]
        G_t = float(self.fin.growth(self.z0, np.array([t]), self.horizon)[0])
        G_T = self.fin.growth(self.z0, l.t, self.horizon)
        cT = l.c / G_T if idx_T is None else l.c * np.asarray(idx_T) / G_T
        recv = l.t <= t + EPS
        base = -self.P0[i] if self.fin.basis == "excess" else -self.P0[i] / G_t
        return G_t * (base + (cT * recv).sum(-1))

    @staticmethod
    def _split(ca, tau, df_a, delta, dbe, Va, Vb, H, L, beta, delta_knots) -> Split:
        g = -ca * tau * df_a
        fo_cf = g * delta
        fo = fo_cf.sum(1)
        buckets = np.einsum("nm,nmj->nj", fo_cf, H)
        expo = np.einsum("nm,nmk->nk", g, L)
        factors = beta * expo
        conv = 0.5 * (ca * tau**2 * df_a * delta**2).sum(1)
        fo_be = (g * dbe).sum(1)
        total = Vb - Va
        return Split(total, fo, buckets, factors, fo - factors.sum(1), conv, total - fo - conv, fo - fo_be, fo_be,
                     beta / BP, delta_knots / BP)

    # ------------------------------------------------------------------ main
    def attribute(self, path: ExpectationPath, t: np.ndarray, basis: FactorBasis, infl=None) -> Attribution:
        z0 = self.z0
        t = np.asarray(t, float)
        P = basis.projector
        zk0 = z0.z(KT)
        Fk = z0.fwd(t[:, None], KT[None, :])
        Uk = path.curve(z0, t, KT)
        beta_c, beta_e, beta_p = (Uk - zk0) @ P.T, (Uk - Fk) @ P.T, (Fk - zk0) @ P.T
        dsp = path.spread(t) * BP
        be0 = self.be0
        if self.has_real and infl is not None:   # factor moves of the REAL curve for TIPS lines
            r0 = self.r0
            rk0, RFk = r0.z(KT), r0.fwd(t[:, None], KT[None, :])
            RUk = Uk - infl.be_curve(t, KT)
            rbeta_c, rbeta_e, rbeta_p = (RUk - rk0) @ P.T, (RUk - RFk) @ P.T, (RFk - rk0) @ P.T
        acc = None
        per_line = []
        for i, l in enumerate(self.lines):
            tau = l.t[None, :] - t[:, None]
            alive = tau > EPS
            ta = np.where(alive, tau, 1.0)
            ca = l.c[None, :] * alive
            tt = np.broadcast_to(t[:, None], ta.shape)
            Zu_nom = path.curve(z0, t, ta)
            if be0 is not None and infl is not None:
                B0, BF, BU = be0.z(ta), be0.fwd(tt, ta), infl.be_curve(t, ta)
            else:
                B0 = BF = BU = np.zeros_like(ta)
            if l.real:
                base = self.r0
                Zu = Zu_nom - BU
                IF_t, IF_T = self.index_F(t), self.index_F(l.t)
                IU_t, IU_T = infl.index_fn(t), infl.index_fn(l.t)
                dbe_c = dbe_e = dbe_p = np.zeros_like(ta)
            else:
                base = z0
                Zu = Zu_nom
                IF_t = IU_t = np.ones(len(t))
                IF_T = IU_T = None
                dbe_c, dbe_e, dbe_p = BU - B0, BU - BF, BF - B0
            Z0 = base.z(ta)
            F = base.fwd(tt, ta)
            s0 = l.spread
            ds = dsp[:, None] if l.credit else 0.0
            caF = ca * IF_t[:, None]
            dfy = np.exp(-self.y0[i] * ta)
            dfR = np.exp(-(Z0 + s0) * ta)
            dfF = np.exp(-(F + s0) * ta)
            dfU0 = np.exp(-(Zu + s0) * ta)
            dfU = np.exp(-(Zu + s0 + ds) * ta)
            Vy, VR, VF, VU0, VU = [(caF * d).sum(1) for d in (dfy, dfR, dfF, dfU0, dfU)]
            cashF = self.cash(i, t, IF_T)
            cashU = self.cash(i, t, IU_T) if l.real else cashF
            ratio = IU_t / IF_t
            H = tent_weights(KT, ta)
            Lf = basis.loadings(ta)
            k = l.face * MM
            bc, be_, bp_ = (rbeta_c, rbeta_e, rbeta_p) if l.real else (beta_c, beta_e, beta_p)
            curve = self._split(caF, ta, dfR, Zu - Z0, dbe_c, VR, VU0, H, Lf, bc, Uk - zk0).scaled(k)
            edge = self._split(caF, ta, dfF, Zu - F, dbe_e, VF, VU0, H, Lf, be_, Uk - Fk).scaled(k)
            priced = self._split(caF, ta, dfR, F - Z0, dbe_p, VR, VF, H, Lf, bp_, Fk - zk0).scaled(k)
            if l.real:   # report nominal factor moves in the aggregate (beta is informational)
                curve.beta, edge.beta, priced.beta = beta_c / BP, beta_e / BP, beta_p / BP
            parts = dict(carry=(Vy + cashF) * k, roll=(VR - Vy) * k, spread=(VU - VU0) * k,
                         inflation=(VU * (ratio - 1) + cashU - cashF) * k,
                         total=(VU * ratio + cashU) * k, priced_in=(VF + cashF) * k)
            per_line.append(parts["total"])
            if acc is None:
                acc = dict(parts, curve=curve, edge=edge, priced=priced)
            else:
                for key in parts:
                    acc[key] = acc[key] + parts[key]
                acc["curve"] = acc["curve"] + curve
                acc["edge"] = acc["edge"] + edge
                acc["priced"] = acc["priced"] + priced
        return Attribution(t=t, per_line_total=np.array(per_line), gross_mv=self.gross_mv, **acc)

    # ------------------------------------------------------------------ scenario repricing
    def pnl_at(self, t: float, curve_fn, spread_change=0.0, be_fn=None, index_fn=None) -> np.ndarray:
        """Total P&L ($) at date t for S scenarios.
        curve_fn(tau) -> nominal zero rates (S, M). For TIPS lines: be_fn(tau) -> breakevens (S, M) or (M,)
        (default today's), index_fn(s) -> index ratio(s) at dates s, shape (M,) or (S, M) (default priced)."""
        out = 0.0
        for i, l in enumerate(self.lines):
            alive = l.t > t + EPS
            tau = l.t[alive] - t
            if l.real:
                idx = index_fn if index_fn is not None else self.index_F
                I_T = np.asarray(idx(l.t))
                I_t = np.asarray(idx(np.array([t])))
                I_t = I_t[..., 0] if I_t.ndim > 0 else I_t
            else:
                I_T, I_t = None, 1.0
            cash = self.cash_at(i, t, I_T)
            if len(tau) == 0:
                out = out + l.face * MM * cash
                continue
            Z = np.atleast_2d(curve_fn(tau))
            if l.real:
                B = np.atleast_2d(be_fn(tau) if be_fn is not None else self.be0.z(tau))
                Z = Z - B
            s = l.spread + (spread_change if l.credit else 0.0)
            V = np.exp(-(Z + s) * tau[None, :]) @ l.c[alive]
            out = out + l.face * MM * (V * I_t + cash)
        return np.atleast_1d(out)

    def exposures_at(self, t: float, curve_fn, basis: FactorBasis | None = None, spread_change=0.0,
                     be_fn=None, index_t=None):
        """Dollar sensitivities at date t (per +1bp): parallel nominal DV01, nominal key-rate tents, nominal
        factor exposures, and breakeven key-rate tents (on BE_TENORS; TIPS lines only)."""
        krd = np.zeros(len(KT))
        bkrd = np.zeros(len(BT))
        fx = np.zeros(3)
        dv01 = 0.0
        for l in self.lines:
            alive = l.t > t + EPS
            tau = l.t[alive] - t
            if len(tau) == 0:
                continue
            Z = np.atleast_2d(curve_fn(tau))[0]
            I = 1.0
            if l.real:
                Z = Z - (np.atleast_2d(be_fn(tau))[0] if be_fn is not None else self.be0.z(tau))
                I = float(index_t) if index_t is not None else float(self.index_F(np.array([t]))[0])
            s = l.spread + (spread_change if l.credit else 0.0)
            g = -l.c[alive] * tau * np.exp(-(Z + s) * tau) * BP * l.face * MM * I
            krd += g @ tent_weights(KT, tau)
            dv01 += g.sum()
            if basis is not None:
                fx += g @ basis.loadings(tau)
            if l.real:
                bkrd -= g @ tent_weights(BT, tau)
        return dv01, krd, fx, bkrd
