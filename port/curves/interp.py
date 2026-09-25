"""Vectorised interpolation primitives.

* PCHIP (Fritsch–Carlson, identical to scipy's PchipInterpolator) on many rows at once,
  evaluated at row-specific query points — used for deviation curves in maturity and in time.
* Natural-cubic-spline basis matrices — the zero curve is linear in its knot values.
All interpolants extrapolate flat (clamped to the end knots).
"""
from __future__ import annotations

import numpy as np


def _edge(h0, h1, m0, m1):
    d = ((2 * h0 + h1) * m0 - h0 * m1) / (h0 + h1)
    d = np.where(np.sign(d) != np.sign(m0), 0.0, d)
    big = (np.sign(m0) != np.sign(m1)) & (np.abs(d) > 3 * np.abs(m0))
    return np.where(big, 3 * m0, d)


def pchip_slopes(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Knot derivatives for PCHIP. x: (J,), y: (..., J)."""
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    h = np.diff(x)
    delta = np.diff(y, axis=-1) / h
    if len(x) == 2:
        return np.repeat(delta, 2, axis=-1)
    d = np.zeros_like(y)
    w1 = 2 * h[1:] + h[:-1]
    w2 = h[1:] + 2 * h[:-1]
    dp, dn = delta[..., :-1], delta[..., 1:]
    same = (np.sign(dp) * np.sign(dn)) > 0
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        whmean = (w1 / dp + w2 / dn) / (w1 + w2)
        d[..., 1:-1] = np.where(same, 1.0 / whmean, 0.0)
    d[..., 0] = _edge(h[0], h[1], delta[..., 0], delta[..., 1])
    d[..., -1] = _edge(h[-1], h[-2], delta[..., -1], delta[..., -2])
    return d


def hermite_eval(x, y, d, xq):
    """Evaluate cubic Hermite rows. y, d: (R, J); xq: (R, M) -> (R, M). Flat extrapolation."""
    x = np.asarray(x, float)
    y = np.atleast_2d(y)
    d = np.atleast_2d(d)
    xq = np.asarray(xq, float)
    squeeze = xq.ndim == 1
    if squeeze:
        xq = np.broadcast_to(xq, (y.shape[0], xq.shape[0]))
    xc = np.clip(xq, x[0], x[-1])
    k = np.clip(np.searchsorted(x, xc, side="right") - 1, 0, len(x) - 2)
    h = x[k + 1] - x[k]
    s = (xc - x[k]) / h
    r = np.arange(y.shape[0])[:, None]
    y0, y1, d0, d1 = y[r, k], y[r, k + 1], d[r, k], d[r, k + 1]
    s2, s3 = s * s, s * s * s
    out = (2 * s3 - 3 * s2 + 1) * y0 + (s3 - 2 * s2 + s) * h * d0 + (-2 * s3 + 3 * s2) * y1 + (s3 - s2) * h * d1
    return out


def pchip(x, y, xq):
    """Convenience: PCHIP rows y (R,J) at xq (R,M) or (M,)."""
    y = np.atleast_2d(np.asarray(y, float))
    return hermite_eval(x, y, pchip_slopes(x, y), xq)


def linear_rows(x, y, xq):
    """Linear interpolation of rows y (R,J) at xq (R,M) or (M,), flat extrapolation."""
    x = np.asarray(x, float)
    y = np.atleast_2d(np.asarray(y, float))
    xq = np.asarray(xq, float)
    if xq.ndim == 1:
        xq = np.broadcast_to(xq, (y.shape[0], xq.shape[0]))
    xc = np.clip(xq, x[0], x[-1])
    k = np.clip(np.searchsorted(x, xc, side="right") - 1, 0, len(x) - 2)
    w = (xc - x[k]) / (x[k + 1] - x[k])
    r = np.arange(y.shape[0])[:, None]
    return y[r, k] * (1 - w) + y[r, k + 1] * w


def tent_weights(knots, tau):
    """Key-rate 'tent' weights h_j(tau): linear-interpolation weights, flat beyond the ends.
    Partition of unity: sum_j h_j(tau) = 1 for every tau. Returns (*tau.shape, J)."""
    knots = np.asarray(knots, float)
    tau = np.asarray(tau, float)
    tc = np.clip(tau, knots[0], knots[-1])
    k = np.clip(np.searchsorted(knots, tc, side="right") - 1, 0, len(knots) - 2)
    w = (tc - knots[k]) / (knots[k + 1] - knots[k])
    out = np.zeros(tau.shape + (len(knots),))
    np.put_along_axis(out, k[..., None], (1 - w)[..., None], axis=-1)
    idx = (k + 1)[..., None]
    prev = np.take_along_axis(out, idx, axis=-1)
    np.put_along_axis(out, idx, prev + w[..., None], axis=-1)
    return out


class NaturalCubic:
    """Natural cubic spline (zero second derivative at both ends) through (x, y), y of shape (n, ...).
    Evaluation clamps to [x0, xn]; `deriv` returns the first derivative (0 outside the knots)."""

    def __init__(self, x, y):
        self.x = x = np.asarray(x, float)
        self.y = y = np.asarray(y, float)
        n = len(x)
        h = np.diff(x)
        M = np.zeros_like(y)
        if n > 2:
            A = np.zeros((n - 2, n - 2))
            idx = np.arange(n - 2)
            A[idx, idx] = 2 * (h[:-1] + h[1:])
            A[idx[1:], idx[:-1]] = h[1:-1]
            A[idx[:-1], idx[1:]] = h[1:-1]
            d = np.diff(y, axis=0) / h.reshape((-1,) + (1,) * (y.ndim - 1))
            rhs = 6 * (d[1:] - d[:-1])
            M[1:-1] = np.linalg.solve(A, rhs.reshape(n - 2, -1)).reshape(rhs.shape)
        self.M = M

    def _locate(self, q):
        x = self.x
        qc = np.clip(np.asarray(q, float), x[0], x[-1])
        k = np.clip(np.searchsorted(x, qc, side="right") - 1, 0, len(x) - 2)
        return qc, k, x[k + 1] - x[k]

    def __call__(self, q):
        qc, k, h = self._locate(q)
        ex = (1,) * (self.y.ndim - 1)
        a = ((self.x[k + 1] - qc) / 1.0).reshape(qc.shape + ex)
        b = ((qc - self.x[k]) / 1.0).reshape(qc.shape + ex)
        hh = h.reshape(qc.shape + ex)
        M0, M1, y0, y1 = self.M[k], self.M[k + 1], self.y[k], self.y[k + 1]
        return (M0 * a**3 + M1 * b**3) / (6 * hh) + (y0 / hh - M0 * hh / 6) * a + (y1 / hh - M1 * hh / 6) * b

    def deriv(self, q):
        q = np.asarray(q, float)
        qc, k, h = self._locate(q)
        ex = (1,) * (self.y.ndim - 1)
        a = (self.x[k + 1] - qc).reshape(qc.shape + ex)
        b = (qc - self.x[k]).reshape(qc.shape + ex)
        hh = h.reshape(qc.shape + ex)
        M0, M1, y0, y1 = self.M[k], self.M[k + 1], self.y[k], self.y[k + 1]
        d = -M0 * a**2 / (2 * hh) + M1 * b**2 / (2 * hh) + (y1 - y0) / hh - (M1 - M0) * hh / 6
        inside = ((q > self.x[0]) & (q < self.x[-1])).reshape(qc.shape + ex)
        return np.where(inside, d, 0.0)


def spline_basis(knots, q) -> np.ndarray:
    """Natural cubic spline basis: value at q = basis @ knot_values. Flat outside knots."""
    knots = np.asarray(knots, float)
    return NaturalCubic(knots, np.eye(len(knots)))(np.asarray(q, float))


def root_scalar(f, a: float, b: float, xtol: float = 1e-10, maxiter: int = 200) -> float:
    """Root of f on [a, b] with f(a)·f(b) < 0 — Illinois false position (robust, superlinear)."""
    fa, fb = f(a), f(b)
    if fa == 0:
        return a
    if fb == 0:
        return b
    if fa * fb > 0:
        raise ValueError("root not bracketed")
    side = 0
    for _ in range(maxiter):
        c = (a * fb - b * fa) / (fb - fa)
        fc = f(c)
        if fc == 0 or abs(b - a) < xtol:
            return c
        if fc * fb > 0:
            b, fb = c, fc
            if side == -1:
                fa /= 2
            side = -1
        else:
            a, fa = c, fc
            if side == 1:
                fb /= 2
            side = 1
    return c
