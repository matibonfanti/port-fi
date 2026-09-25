"""Inverse engine (roots substituted back), return bases, and no-silent-substitution rules."""
import numpy as np
import pytest

from port.analytics import inverse
from port.analytics.attribution import BP, KT, Book
from port.analytics.scenario import context, pnl
from port.instruments.position import Financing, build_lines
from port.paths import inflation
from port.paths.path import ExpectationPath

from .conftest import ASOF, ctx

BOND = [{"kind": "bond", "bond": {"tenor": 7, "coupon": 4.0}, "face_mm": 1}]


def mkbook(z0, stats, items, fin, H=0.5, curves=None):
    if curves:
        z0, be0, r0 = curves
        return Book(z0, build_lines(items, ctx(z0, r0), stats.pca), fin, H, be0, r0)
    return Book(z0, build_lines(items, ctx(z0), stats.pca), fin, H)


@pytest.mark.parametrize("basis", ["excess", "total"])
def test_inverse_roots_substitute_back(z0, stats, basis):
    H = 0.5
    b = mkbook(z0, stats, BOND, Financing("flat", 4.0, basis=basis), H)
    path = ExpectationPath("today", np.array([H]), np.array([[-75, -75, -75, -75, -75, -65, -50, -40, -25, -10, 0.0]]))
    res = inverse.solve_all(b, path, None, H, stats.parametric, target_pct=5.0)
    tol = 1e-6 * b.gross_mv
    for row in res["targets"]:
        for key, r in row["moves"].items():
            if r["ok"]:
                assert abs(r["residual"]) < tol, (row["key"], key)
    # independent re-check of the parallel move vs today
    c = context(b, path, None, H, "today")
    for row in res["targets"]:
        r = row["moves"]["parallel_today"]
        if r["ok"]:
            v = pnl(b, H, c, nominal_fn=lambda tau: c.nominal(tau)[None, :] + r["x"] * BP)[0]
            assert v == pytest.approx(row["value"], abs=tol)
    # view fraction: k = 1 reproduces the view's P&L exactly; latest realisation = H / k
    vf = res["targets"][0]["moves"]["view_fraction"]
    if vf["ok"] and vf["x"] > 0:
        assert vf["latest_t"] == pytest.approx(H / vf["x"])


def test_no_solution_is_reported_not_invented(z0, stats):
    """A DV01-neutral steepener: no parallel move produces a 50%/yr return; reason must be 'never'."""
    b = mkbook(z0, stats, [{"kind": "steepener", "legs": [{"tenor": 2}, {"tenor": 10}], "weighting": "dv01", "size_mm": 1}],
               Financing("flat", 4.0), 1.0)
    res = inverse.solve_all(b, ExpectationPath("forwards"), None, 1.0, stats.parametric, target_pct=50.0)
    r = res["targets"][-1]["moves"]["parallel_today"]
    assert not r["ok"] and r["reason"] == "never"


def test_total_vs_excess_basis_relation(z0, stats):
    """Holding-period (unfunded) P&L − excess P&L = P0·(G(t) − 1) per line exactly (same rate G)."""
    H = 1.0
    t = np.linspace(0, H, 53)
    items = BOND + [{"kind": "bond", "bond": {"tenor": 2}, "face_mm": -0.5}]
    ex = mkbook(z0, stats, items, Financing("flat", 4.5, basis="excess"), H)
    to = mkbook(z0, stats, items, Financing("flat", 4.5, basis="total"), H)
    p = ExpectationPath("today", np.array([0.5]), np.full((1, len(KT)), -20.0))
    a1, a2 = ex.attribute(p, t, stats.parametric), to.attribute(p, t, stats.parametric)
    G = ex.fin.growth(z0, t, H)
    expected = sum(l.face * 1e6 * P0 * (G - 1) for l, P0 in zip(ex.lines, ex.P0))
    assert np.allclose(a2.total - a1.total, expected, atol=1e-8 * ex.gross_mv)
    assert np.allclose(a2.carry - a1.carry, expected, atol=1e-8 * ex.gross_mv)   # difference sits in carry only
    assert np.allclose(a2.curve.total, a1.curve.total) and np.allclose(a2.roll, a1.roll)


def test_holding_period_return_formula(z0, stats):
    """Total basis at H = (V_H + coupons (reinvested at the cash rate) − P0) / P0 under the unchanged curve."""
    H = 1.0
    b = mkbook(z0, stats, BOND, Financing("flat", 0.0, basis="total"), H)
    a = b.attribute(ExpectationPath("today"), np.array([0.0, H]), stats.parametric)
    l = b.lines[0]
    alive = l.t > H
    VH = float(l.c[alive] @ np.exp(-z0.z(l.t[alive] - H) * (l.t[alive] - H)))
    cpn = float(l.c[~alive].sum())
    R = (VH + cpn - b.P0[0]) / b.P0[0]
    assert a.total[-1] / (b.P0[0] * 1e6) == pytest.approx(R, abs=1e-12)


def test_otr_substitution_is_flagged(z0, stats):
    flags = []
    lines = build_lines([{"kind": "bond", "bond": {"otr": 10}, "face_mm": 1}], ctx(z0, None, flags), stats.pca)
    assert lines and any(f["code"] == "otr_missing" for f in flags)


def test_inverse_cpi_for_tips(curves, stats):
    z0, be0, r0 = curves
    b = mkbook(z0, stats, [{"kind": "tips", "bond": {"tenor": 10}, "face_mm": 1}], Financing("flat", 4.0), 1.0, curves)
    infl = inflation.build({"mode": "priced"}, be0, "forwards", 1.0)
    res = inverse.solve_all(b, ExpectationPath("forwards"), infl, 1.0, stats.parametric, target_pct=3.0)
    for row in res["targets"]:
        r = row["moves"]["cpi"]
        assert r["ok"] and abs(r["residual"]) < 1e-6 * b.gross_mv
