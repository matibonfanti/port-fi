"""Historical zero curves at key tenors, factor bases (parametric / PCA) and covariances."""
from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np

from ..config import BE_TENORS, CACHE_DIR, KEY_TENORS, RUNTIME, SNAPSHOT_DIR
from ..data import treasury
from ..data.panel import Panel, to_day
from .interp import NaturalCubic, pchip
from .zero_curve import SplineCurve, fit_breakeven, fit_smooth_knots

log = logging.getLogger(__name__)
KT = np.array(KEY_TENORS)
BT = np.array(BE_TENORS)
FIT_VERSION = "v3"          # bump when the fitting methodology changes (invalidates caches)


def _fit_nominal_rows(par: Panel, prev_state=None):
    """Fit every date: returns (key-tenor zeros (N, J), fitted knots per date {date: (knots, zeros)})."""
    out = np.full((len(par), len(KT)), np.nan)
    curves = {}
    prev = prev_state or {}
    tenor_of = np.array(par.cols)
    vals = par.values / 100.0
    for r in range(len(par)):
        ok = ~np.isnan(vals[r])
        if ok.sum() < 4:
            continue
        ten, y = tenor_of[ok], vals[r][ok]
        key = tuple(ten)
        try:
            kn, z = fit_smooth_knots(ten, y, k_init=prev.get(key), iters=30 if key not in prev else 6)
        except np.linalg.LinAlgError:
            continue
        if not np.all(np.isfinite(z)):
            continue
        prev[key] = z
        curves[par.dates[r]] = (kn, z)
        out[r] = NaturalCubic(kn, z)(KT)
    return out, curves


def _fit_be_rows(real: Panel, nominal_curves: dict) -> np.ndarray:
    """Breakeven zero rates at BE_TENORS per real-curve date (NaN where the tenor was not published)."""
    out = np.full((len(real), len(BT)), np.nan)
    prev = {}
    vals = real.values / 100.0
    ten_all = np.array(real.cols)
    for r in range(len(real)):
        nc = nominal_curves.get(real.dates[r])
        ok = ~np.isnan(vals[r])
        if nc is None or ok.sum() < 1:
            continue
        ten = ten_all[ok]
        key = tuple(ten)
        try:
            be = fit_breakeven(SplineCurve(*nc), ten, vals[r][ok], b_init=prev.get(key))
        except np.linalg.LinAlgError:
            continue
        if not np.all(np.isfinite(be.zeros)):
            continue
        prev[key] = be.zeros
        for j, T in enumerate(BT):
            if T in key:
                out[r, j] = be.zeros[key.index(T)]
    return out


def _cache_paths():
    base = SNAPSHOT_DIR if RUNTIME == "browser" else CACHE_DIR
    return SNAPSHOT_DIR / "zero_keys.csv", SNAPSHOT_DIR / "be_keys.csv", base


@lru_cache(maxsize=2)
def _fitted(nom_last, n_nom, real_last, n_real):
    """Key-tenor zero history and breakeven history, reusing the snapshot fits and fitting only the
    dates not already covered (plus the last 5 snapshot dates, as Treasury occasionally revises)."""
    par = treasury.history("nominal")
    real = treasury.history("real")
    zfile, bfile, _ = _cache_paths()
    zsnap = Panel.read_csv(zfile) if zfile.exists() else None
    bsnap = Panel.read_csv(bfile) if bfile.exists() else None
    ver_ok = (SNAPSHOT_DIR / "VERSION").exists() and (SNAPSHOT_DIR / "VERSION").read_text().strip() == FIT_VERSION
    if not ver_ok:
        zsnap = bsnap = None
    cutoff = zsnap.dates[-5] if zsnap is not None and len(zsnap) > 5 else np.datetime64("1900-01-01")
    todo_nom = par.between(cutoff, par.dates[-1]) if zsnap is not None else par
    zk, curves = _fit_nominal_rows(todo_nom)
    parts = [zsnap.upto(cutoff)] if zsnap is not None else []
    zero = Panel.concat(parts + [Panel(todo_nom.dates, list(KT), zk)], list(KT))
    bcut = bsnap.dates[-5] if bsnap is not None and len(bsnap) > 5 else np.datetime64("1900-01-01")
    todo_real = real.between(max(bcut, cutoff), real.dates[-1]) if bsnap is not None else real
    if bsnap is None and zsnap is not None:
        # need nominal fits for every real date
        _, curves = _fit_nominal_rows(par.between(real.dates[0] - 1, par.dates[-1]))
    bk = _fit_be_rows(todo_real, curves)
    bparts = [bsnap.upto(max(bcut, cutoff))] if bsnap is not None else []
    be = Panel.concat(bparts + [Panel(todo_real.dates, list(BT), bk)], list(BT))
    return zero, be


def zero_history() -> Panel:
    """Daily cc zero rates (decimal) at KEY_TENORS for every date in the par history."""
    p, r = treasury.history("nominal"), treasury.history("real")
    return _fitted(p.last, len(p), r.last, len(r))[0]


def be_history() -> Panel:
    """Daily cc breakeven zero rates (decimal) at BE_TENORS (TIPS dates only)."""
    p, r = treasury.history("nominal"), treasury.history("real")
    return _fitted(p.last, len(p), r.last, len(r))[1]


def write_snapshot_fits():
    zero, be = zero_history(), be_history()
    zero.to_csv(SNAPSHOT_DIR / "zero_keys.csv", digits=8)
    be.to_csv(SNAPSHOT_DIR / "be_keys.csv", digits=8)
    (SNAPSHOT_DIR / "VERSION").write_text(FIT_VERSION)


# ---------------------------------------------------------------------------------------
# Factor bases
# ---------------------------------------------------------------------------------------
NS_LAMBDA = 2.5  # years; Nelson–Siegel curvature hump peaks near 1.79*lambda ≈ 4.5y
FACTOR_LABELS = ["Level", "Slope", "Curvature"]
# Projection weights per key tenor: bills (1m, 3m) carry idiosyncratic supply/debt-ceiling
# noise, so they are down-weighted when a curve change is expressed in factor terms.
PROJ_W = np.array([0.25, 0.5] + [1.0] * (len(KEY_TENORS) - 2))
I2, I5, I10 = KEY_TENORS.index(2.0), KEY_TENORS.index(5.0), KEY_TENORS.index(10.0)


def _ns(tau):
    x = np.maximum(np.asarray(tau, float), 1e-8) / NS_LAMBDA
    g1 = (1 - np.exp(-x)) / x
    g2 = g1 - np.exp(-x)
    return g1, g2


def _normalize(B: np.ndarray) -> np.ndarray:
    """Scale loadings to trader units: level = weighted-average shift of 1,
    slope: 10y−2y = 1 (steepening > 0), curvature: 2s5s10s fly (2·5y−2y−10y) = 1 (belly cheapens > 0)."""
    B = B.copy()
    B[:, 0] /= (PROJ_W @ B[:, 0]) / PROJ_W.sum()
    B[:, 1] /= B[I10, 1] - B[I2, 1]
    B[:, 2] /= 2 * B[I5, 2] - B[I2, 2] - B[I10, 2]
    return B


def _param_raw(tau):
    tau = np.asarray(tau, float)
    g1, g2 = _ns(tau)
    return np.stack([np.ones_like(tau), -g1, g2], axis=-1)


def _param_transform():
    """Linear map T (3x3) with loadings(tau) = raw(tau) @ T: Gram–Schmidt of the NS loadings
    under the projection weights (level ⟂ slope ⟂ curvature at the key tenors), then scaling."""
    R = _param_raw(KT)
    W = np.diag(PROJ_W)
    T = np.eye(3)
    Q = R.copy()
    for k in range(1, 3):
        for j in range(k):
            c = (Q[:, j] @ W @ Q[:, k]) / (Q[:, j] @ W @ Q[:, j])
            Q[:, k] -= c * Q[:, j]
            T[:, k] -= c * T[:, j]
    N = _normalize(Q)
    scale = N[0] / np.where(Q[0] == 0, 1, Q[0])
    return T * scale[None, :]


_PT = _param_transform()


def parametric_loadings(tau) -> np.ndarray:
    """Nelson–Siegel level/slope/curvature, orthogonalised under the key-tenor weights and
    scaled to trader units (see _normalize)."""
    return _param_raw(tau) @ _PT


@dataclass
class FactorBasis:
    kind: str                 # "parametric" | "pca"
    B: np.ndarray             # (J, 3) loadings at key tenors
    cov: np.ndarray           # (3, 3) factor covariance, (decimal)^2 per year
    explained: list | None = None
    window: tuple | None = None

    labels = FACTOR_LABELS

    def loadings(self, tau) -> np.ndarray:
        tau = np.asarray(tau, float)
        if self.kind == "parametric":
            return parametric_loadings(tau)
        flat = tau.reshape(-1)
        L = pchip(KT, self.B.T, flat)  # (3, M)
        return L.T.reshape(tau.shape + (3,))

    @property
    def projector(self) -> np.ndarray:
        """P (3, J): beta = P @ delta_knots  (weighted least squares onto B; P @ B = I)."""
        W = np.diag(PROJ_W)
        return np.linalg.solve(self.B.T @ W @ self.B, self.B.T @ W)

    def project(self, delta_knots) -> np.ndarray:
        return np.asarray(delta_knots) @ self.projector.T

    @property
    def vols(self) -> np.ndarray:
        return np.sqrt(np.diag(self.cov))


@dataclass
class HistoryStats:
    asof: object
    window_years: float
    knot_cov: np.ndarray      # (J, J) annualised covariance of daily nominal zero changes
    parametric: FactorBasis
    pca: FactorBasis
    n_obs: int
    window: tuple = ("", "")
    truncated: bool = False
    joint_cov: np.ndarray | None = None   # (J+B, J+B) nominal key zeros + breakevens (TIPS era)
    joint_n: int = 0

    def basis(self, kind: str) -> FactorBasis:
        return self.pca if kind == "pca" else self.parametric


@lru_cache(maxsize=16)
def history_stats(asof, window_years: float = 5.0) -> HistoryStats:
    asof = to_day(asof)
    start = asof - np.timedelta64(int(window_years * 365.25), "D")
    h = zero_history().between(start, asof)
    X = np.diff(h.values, axis=0)
    X = X[np.all(np.isfinite(X), axis=1) & np.all(np.abs(np.nan_to_num(X)) < 0.01, axis=1)]
    first = str(h.dates[0]) if len(h) else ""
    st = stats_from_changes(X, asof, window_years, (first, str(asof)))
    st.truncated = bool(len(h) and (h.dates[0] - start) > np.timedelta64(30, "D"))
    # joint nominal + breakeven covariance for inflation-linked books
    b = be_history().between(start, asof)
    if len(b) > 60:
        zi = np.searchsorted(h.dates, b.dates)
        ok = (zi < len(h)) & (h.dates[np.minimum(zi, len(h) - 1)] == b.dates)
        J = np.hstack([h.values[zi[ok]], b.values[ok]])
        dJ = np.diff(J, axis=0)
        dJ = dJ[np.all(np.isfinite(dJ), axis=1) & np.all(np.abs(np.nan_to_num(dJ)) < 0.01, axis=1)]
        if len(dJ) > 60:
            st.joint_cov = np.cov(dJ, rowvar=False) * 252.0
            st.joint_n = len(dJ)
    return st


def stats_from_changes(X: np.ndarray, asof=None, window_years=0.0, window=("", "")) -> HistoryStats:
    """Covariances, PCA and factor covariances from daily zero-rate changes X (T, J) in decimals."""
    ann = 252.0
    C = np.cov(X, rowvar=False) * ann
    # PCA on the coupon curve (>= 1y); bill tenors get loadings by regressing their daily
    # changes on the PC scores (bills are too noisy to define the factors themselves).
    long = KT >= 1.0
    Cl = np.cov(X[:, long], rowvar=False)
    w, V = np.linalg.eigh(Cl)
    order = np.argsort(w)[::-1]
    w, V = w[order], V[:, order]
    V3 = V[:, :3]
    if V3[:, 0].sum() < 0:
        V3[:, 0] *= -1
    scores = (X[:, long] - X[:, long].mean(0)) @ V3
    Xc = X - X.mean(0)
    Bp = np.linalg.lstsq(scores, Xc, rcond=None)[0].T  # (J, 3); equals V3 on long knots
    Bp = _normalize(Bp)
    explained = (w[:3] / w.sum()).tolist()
    Bpar = parametric_loadings(KT)

    def fcov(B):
        W = np.diag(PROJ_W)
        P = np.linalg.solve(B.T @ W @ B, B.T @ W)
        f = X @ P.T
        return np.cov(f, rowvar=False) * ann

    return HistoryStats(
        asof=asof, window_years=window_years, knot_cov=C, window=window,
        parametric=FactorBasis("parametric", Bpar, fcov(Bpar)),
        pca=FactorBasis("pca", Bp, fcov(Bp), explained, window),
        n_obs=len(X),
    )
