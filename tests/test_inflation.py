"""TIPS, breakevens and inflation views: pricing identities and exactness."""
import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from port.analytics.attribution import BP, KT, Book
from port.curves.zero_curve import RealCurve, fit_breakeven
from port.instruments.position import Financing, build_lines
from port.paths import inflation
from port.paths.path import ExpectationPath

from .conftest import ASOF, REAL, REAL_TENORS, ctx

TIPS = {"kind": "tips", "bond": {"tenor": 10}, "face_mm": 1}
BE_TRADE = {"kind": "breakeven", "legs": [{"tenor": 10}, {"tenor": 10}], "weighting": "dv01", "size_mm": 1}


def book(curves, stats, items, fin=None, H=1.0):
    z0, be0, r0 = curves
    return Book(z0, build_lines(items, ctx(z0, r0), stats.pca), fin or Financing("implied", 0.0), H, be0, r0)


def test_breakeven_fit_reprices_tips(curves):
    z0, be0, r0 = curves
    assert np.max(np.abs(r0.par_yield(REAL_TENORS) - REAL)) < 1e-12
    # forward breakeven equals nominal minus real forwards exactly
    assert np.allclose(be0.fwd(2.0, KT), z0.fwd(2.0, KT) - r0.fwd(2.0, KT), atol=1e-15)
    # held flat below the first TIPS tenor
    assert np.allclose(be0.z(np.array([0.25, 1, 3])), be0.z(5.0))


@pytest.mark.parametrize("items", [[TIPS], [BE_TRADE], [TIPS, {"kind": "bond", "bond": {"tenor": 5}, "face_mm": -1}]])
def test_priced_inflation_and_forwards_earn_risk_free(curves, stats, items):
    """Forwards realised, CPI as priced, implied financing => TIPS earn exactly the nominal risk-free rate."""
    z0, be0, _ = curves
    b = book(curves, stats, items)
    infl = inflation.build({"mode": "priced"}, be0, "forwards", 1.0)
    a = b.attribute(ExpectationPath("forwards"), np.linspace(0, 1, 53), stats.parametric, infl)
    tol = 1e-9 * b.gross_mv
    assert np.max(np.abs(a.total)) < tol and np.max(np.abs(a.priced_in)) < tol
    assert np.max(np.abs(a.edge_total)) < tol and np.max(np.abs(a.inflation)) < tol


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(mode=st.sampled_from(["priced", "unchanged", "nodes", "expectations"]),
       cpi=st.one_of(st.none(), st.floats(-2, 10)), w=st.sampled_from([0.0, 0.5, 1.0]),
       buckets=st.lists(st.floats(-1, 8), min_size=5, max_size=5),
       dev=st.lists(st.floats(-80, 80), min_size=len(KT), max_size=len(KT)),
       basis=st.sampled_from(["excess", "total"]))
def test_inflation_identities(curves, stats, mode, cpi, w, buckets, dev, basis):
    z0, be0, _ = curves
    spec = {"mode": mode, "cpi_pct": cpi, "buckets": buckets, "nodes": [{"t": 0.5, "dev": dev}], "irp": {"10": 10}}
    infl = inflation.build(spec, be0, "forwards", 1.0)
    nom = ExpectationPath("today", np.array([0.75]), np.array([dev]) * 0.5)
    path = inflation.FisherPath(nom, infl, w) if mode in ("nodes", "expectations") else nom
    b = book(curves, stats, [TIPS, BE_TRADE, {"kind": "bond", "bond": {"tenor": 7}, "face_mm": 1}],
             Financing("flat", 4.2, basis=basis))
    a = b.attribute(path, np.linspace(0, 1, 27), stats.pca, infl)
    tol = 1e-9 * b.gross_mv
    c = a.curve
    assert np.max(np.abs(a.carry + a.roll + c.total + a.spread + a.inflation - a.total)) < tol
    assert np.max(np.abs(a.priced_in + a.edge.total + a.spread + a.inflation - a.total)) < tol
    assert np.max(np.abs(c.fo_real + c.fo_be - c.fo)) < tol
    assert np.max(np.abs(c.factors.sum(1) + c.other - c.fo)) < tol


def test_fisher_passthrough(curves):
    """w = 1 holds real yields: the real curve under the view equals the nominal view minus base breakevens."""
    z0, be0, _ = curves
    infl = inflation.build({"mode": "nodes", "anchor": "forwards", "nodes": [{"t": 1.0, "dev": [40.0] * len(KT)}]},
                           be0, "forwards", 1.0)
    nom = ExpectationPath("forwards", np.array([1.0]), np.array([[10.0] * len(KT)]))
    t = np.array([0.5, 1.0])
    f1 = inflation.FisherPath(nom, infl, 1.0)
    real_w1 = f1.curve(z0, t, KT) - infl.be_curve(t, KT)
    real_base = nom.curve(z0, t, KT) - be0.fwd(t[:, None], KT[None, :])
    assert np.allclose(real_w1, real_base, atol=1e-14)
    f0 = inflation.FisherPath(nom, infl, 0.0)
    assert np.allclose(f0.curve(z0, t, KT), nom.curve(z0, t, KT), atol=1e-15)
    assert np.allclose((f1.curve(z0, t, KT) - nom.curve(z0, t, KT))[-1], 40 * BP, atol=1e-12)


def test_cpi_surprise_accrual(curves, stats):
    """With rates and breakevens as priced, realised CPI 1% (cc) above priced scales the horizon value by e^0.01:
    the surprise is ≈ (e^0.01 − 1) × horizon value, and the horizon value ≈ P0 / DF_nominal(1y)."""
    z0, be0, _ = curves
    b = book(curves, stats, [TIPS])
    priced = inflation.build({"mode": "priced"}, be0, "forwards", 1.0)
    iF1 = float(priced.index_F(np.array([1.0]))[0])
    cpi = (iF1 * np.e ** 0.01 - 1) * 100             # 1% cc above priced
    infl = inflation.build({"mode": "nodes", "cpi_pct": cpi, "nodes": []}, be0, "forwards", 1.0)
    a = b.attribute(ExpectationPath("forwards"), np.linspace(0, 1, 53), stats.parametric, infl)
    # independent evaluation of the documented formula
    r0 = curves[2]
    l = b.lines[0]
    alive = l.t > 1.0
    tau = l.t[alive] - 1.0
    IF = lambda s: np.exp(be0.z(s) * s)
    IU = lambda s: (1 + cpi / 100) ** np.asarray(s)
    VU = IF(1.0) * float(l.c[alive] @ np.exp(-r0.fwd(1.0, tau) * tau))
    G = lambda s: 1 / z0.df(s)
    recv = ~alive
    expected = VU * (IU(1.0) / IF(1.0) - 1) + float(np.sum(l.c[recv] * (IU(l.t[recv]) - IF(l.t[recv])) * G(1.0) / G(l.t[recv])))
    assert a.inflation[-1] == pytest.approx(expected * 1e6 * l.face, rel=1e-10)
    # and it is ≈ (e^0.01 − 1) of the horizon value, the half-year coupon carrying half the surprise
    assert a.inflation[-1] / b.gross_mv == pytest.approx(np.expm1(0.01) / float(z0.df(1.0)), rel=0.01)


def test_expectations_equal_to_priced_reproduce_priced(curves, stats):
    z0, be0, _ = curves
    mk = inflation.build({"mode": "priced"}, be0, "forwards", 1.0)
    user = [m["mkt_yoy"] for m in mk.report["buckets"]]
    ex = inflation.build({"mode": "expectations", "buckets": user}, be0, "forwards", 1.0)
    t = np.linspace(0.05, 1, 12)
    assert np.allclose(ex.be_curve(t, KT), be0.fwd(t[:, None], KT[None, :]), atol=1e-12)
    assert np.allclose(ex.index_fn(t), mk.index_fn(t), atol=1e-12)


def test_tips_need_real_curve(curves, stats):
    z0 = curves[0]
    with pytest.raises(ValueError, match="2003"):
        build_lines([TIPS], ctx(z0, None), stats.pca)
