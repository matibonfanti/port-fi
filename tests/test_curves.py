import numpy as np
from scipy.interpolate import PchipInterpolator

from port.curves.interp import pchip, tent_weights
from port.curves.zero_curve import ZeroCurve, fit_curve

from .conftest import ASOF, INVERTED, PAR, TENORS


def test_exact_fit_reprices_inputs():
    for y in (PAR, INVERTED):
        c = ZeroCurve.from_par(TENORS, y, ASOF)
        assert np.max(np.abs(c.par_yield(TENORS) - y)) < 1e-12


def test_smooth_fit_is_close_and_smooth():
    for y in (PAR, INVERTED):
        c = fit_curve(TENORS, y, ASOF)
        err = (c.par_yield(TENORS) - y) * 1e4
        coupons = TENORS >= 1
        assert np.max(np.abs(err[coupons])) < 3.0          # coupon benchmarks within 3bp
        assert np.max(np.abs(err[~coupons])) < 15.0        # bills within 15bp
        s = np.linspace(0.1, 29, 600)
        f = c.fwd_inst(s)
        e = ZeroCurve.from_par(TENORS, y, ASOF).fwd_inst(s)
        rough = lambda v: np.sum(np.diff(v, 2) ** 2)
        assert rough(f) < rough(e)                          # smoother forwards than the exact fit


def test_forward_identity(z0):
    t = np.array([0.0, 0.25, 0.5, 1.0, 2.0])[:, None]
    tau = np.array([1 / 12, 0.5, 2.0, 10.0, 28.0])[None, :]
    F = z0.fwd(t, tau)
    assert np.allclose(np.exp(-F * tau), z0.df(t + tau) / z0.df(t), rtol=0, atol=1e-14)
    # instantaneous forward is the tau->0 limit
    assert np.allclose(z0.fwd(np.array([1.0]), np.array([1e-10])), z0.fwd_inst(np.array([1.0])), atol=1e-12)
    assert np.allclose(z0.fwd(np.array([1.0]), np.array([1e-5])), z0.fwd_inst(np.array([1.0])), atol=1e-7)


def test_pchip_matches_scipy():
    rng = np.random.default_rng(1)
    x = np.array([0.0, 0.3, 1.0, 2.0, 5.0, 10.0, 30.0])
    Y = rng.standard_normal((5, len(x)))
    q = rng.uniform(-1, 35, (5, 40))
    ref = np.array([PchipInterpolator(x, Y[i])(np.clip(q[i], x[0], x[-1])) for i in range(5)])
    assert np.max(np.abs(pchip(x, Y, q) - ref)) < 1e-12


def test_tents_partition_of_unity():
    kt = np.array([0.25, 1, 2, 5, 10, 30])
    tau = np.linspace(0, 40, 333)
    h = tent_weights(kt, tau)
    assert np.allclose(h.sum(-1), 1.0)
    assert np.all(h >= 0)
    # linear reproduction inside the knot range
    inside = (tau >= kt[0]) & (tau <= kt[-1])
    assert np.allclose(h[inside] @ kt, tau[inside])
