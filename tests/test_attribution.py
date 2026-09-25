"""Decomposition identities across random positions and random expectation paths."""
import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from port.analytics.attribution import BP, KT, Book
from port.instruments.position import Financing, build_lines
from port.paths.path import ExpectationPath

from .conftest import ASOF, ctx

MAT = st.sampled_from([0.6, 1, 1.7, 2, 3, 4.2, 5, 7, 9.5, 10, 15, 20, 25, 30])


def random_items(draw):
    n = draw(st.integers(1, 4))
    items = []
    for _ in range(n):
        kind = draw(st.sampled_from(["bond", "bond", "steepener", "flattener", "butterfly"]))
        cpn = draw(st.one_of(st.none(), st.floats(0.0, 9.0)))
        spread = draw(st.sampled_from([0.0, 0.0, 85.0, 240.0]))
        if kind == "bond":
            items.append({"kind": "bond", "bond": {"tenor": draw(MAT), "coupon": cpn},
                          "face_mm": draw(st.floats(-5, 5).filter(lambda x: abs(x) > 0.05)), "spread_bp": spread})
        elif kind in ("steepener", "flattener"):
            a, b = sorted(draw(st.lists(MAT, min_size=2, max_size=2, unique=True)))
            items.append({"kind": kind, "legs": [{"tenor": a}, {"tenor": b, "coupon": cpn}],
                          "weighting": draw(st.sampled_from(["dv01", "pca"])), "size_mm": 1.0})
        else:
            a, b, c = sorted(draw(st.lists(MAT, min_size=3, max_size=3, unique=True)))
            items.append({"kind": "butterfly", "legs": [{"tenor": a}, {"tenor": b}, {"tenor": c}],
                          "weighting": draw(st.sampled_from(["dv01", "pca"])), "size_mm": 1.0,
                          "direction": draw(st.sampled_from(["short_belly", "long_belly"]))})
    return items


def random_path(draw):
    k = draw(st.integers(0, 4))
    t = sorted(draw(st.lists(st.floats(0.02, 2.5), min_size=k, max_size=k, unique=True)))
    dev = np.array(draw(st.lists(st.lists(st.floats(-150, 150), min_size=len(KT), max_size=len(KT)),
                                 min_size=k, max_size=k))).reshape(k, len(KT))
    sp = np.array(draw(st.lists(st.floats(-80, 80), min_size=k, max_size=k))) if draw(st.booleans()) else None
    return ExpectationPath(draw(st.sampled_from(["forwards", "today"])), np.array(t), dev, sp,
                           draw(st.sampled_from(["pchip", "linear"])))


@st.composite
def scenario(draw):
    fin = draw(st.sampled_from([Financing("flat", 3.9), Financing("flat", 5.5), Financing("implied", 0.0),
                                Financing("implied", 15.0)]))
    return random_items(draw), random_path(draw), fin, draw(st.sampled_from([0.25, 0.5, 1.0, 2.0])), \
        draw(st.sampled_from(["parametric", "pca"]))


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(sc=scenario())
def test_components_sum_exactly(z0_up, stats, sc):
    items, path, fin, H, bk = sc
    basis = stats.basis(bk)
    lines = build_lines(items, ctx(z0_up), stats.pca)
    book = Book(z0_up, lines, fin, H)
    t = np.linspace(0, H, 37)
    a = book.attribute(path, t, basis)
    tol = 1e-9 * max(book.gross_mv, 1.0)
    c, e, p = a.curve, a.edge, a.priced
    # vs today
    assert np.max(np.abs(a.carry + a.roll + c.total + a.spread - a.total)) < tol
    # market-relative
    assert np.max(np.abs(a.priced_in + e.total + a.spread - a.total)) < tol
    assert np.max(np.abs(a.carry + a.roll + p.total - a.priced_in)) < tol
    for s in (c, e, p):
        assert np.max(np.abs(s.buckets.sum(1) - s.fo)) < tol
        assert np.max(np.abs(s.factors.sum(1) + s.other - s.fo)) < tol
        assert np.max(np.abs(s.fo + s.convexity + s.residual - s.total)) < tol
    # everything starts at zero (pinned to today)
    for arr in (a.total, a.carry, a.roll, c.total, e.total, a.priced_in):
        assert abs(arr[0]) < tol
    # the residual is genuinely third-order small relative to the curve move
    assert np.max(np.abs(c.residual)) <= 0.05 * np.max(np.abs(c.total)) + 1e-6 * book.gross_mv


def _book(z0, stats, items, fin, H):
    return Book(z0, build_lines(items, ctx(z0), stats.pca), fin, H)


PORTFOLIO = [{"kind": "bond", "bond": {"tenor": 10}, "face_mm": 1},
             {"kind": "bond", "bond": {"tenor": 2, "coupon": 1.5}, "face_mm": -2},
             {"kind": "bond", "bond": {"tenor": 30, "coupon": 6.0}, "face_mm": 0.7, "spread_bp": 120}]


@pytest.mark.parametrize("H", [0.25, 1.0, 2.0])
def test_forwards_path_has_zero_edge_and_risk_free_return(z0, stats, H):
    book = _book(z0, stats, PORTFOLIO[:2], Financing("implied", 0.0), H)
    t = np.linspace(0, H, 41)
    a = book.attribute(ExpectationPath("forwards"), t, stats.parametric)
    tol = 1e-9 * book.gross_mv
    assert np.max(np.abs(a.edge.total)) < tol and np.max(np.abs(a.edge.buckets)) < tol
    # financing at the implied short rate: excess return is zero at every date
    assert np.max(np.abs(a.priced_in)) < tol
    assert np.max(np.abs(a.total)) < tol


def test_credit_line_earns_spread_carry_when_forwards_realised(z0, stats):
    """With a constant Z-spread s and implied financing, priced-in = P0 (e^{st}-1)-style spread carry > 0."""
    H = 1.0
    book = _book(z0, stats, PORTFOLIO[2:], Financing("implied", 0.0), H)
    a = book.attribute(ExpectationPath("forwards"), np.linspace(0, H, 53), stats.parametric)
    assert np.max(np.abs(a.edge.total)) < 1e-9 * book.gross_mv
    carry_bp = a.priced_in[-1] / book.gross_mv * 1e4
    assert 100 < carry_bp < 140     # ≈ 120bp spread over one year


def test_flat_financing_at_implied_term_rate(z0, stats):
    H = 1.0
    r_mm = Financing.mm_from_cc(float(z0.z(H)), H)
    book = _book(z0, stats, PORTFOLIO[:2], Financing("flat", r_mm), H)
    a = book.attribute(ExpectationPath("forwards"), np.linspace(0, H, 53), stats.parametric)
    # at the horizon only coupon reinvestment (flat vs forward rates) separates it from zero
    assert abs(a.total[-1]) / book.gross_mv * 1e4 < 0.5
    assert np.max(np.abs(a.edge.total)) < 1e-9 * book.gross_mv


def test_unchanged_curve_has_zero_curve_component(z0, stats):
    book = _book(z0, stats, PORTFOLIO, Financing("flat", 4.0), 1.0)
    a = book.attribute(ExpectationPath("today"), np.linspace(0, 1, 53), stats.pca)
    tol = 1e-9 * book.gross_mv
    assert np.max(np.abs(a.curve.total)) < tol
    assert np.max(np.abs(a.curve.buckets)) < tol and np.max(np.abs(a.curve.factors)) < tol
    assert np.allclose(a.total, a.carry + a.roll, atol=tol)


def test_rebase_preserves_node_curves(z0):
    rng = np.random.default_rng(3)
    p = ExpectationPath("forwards", np.array([0.25, 0.5, 1.0]), rng.normal(0, 30, (3, len(KT))))
    q = p.rebased(z0, "today")
    assert np.allclose(p.curve(z0, p.node_t, KT), q.curve(z0, q.node_t, KT), atol=1e-14)
    assert np.allclose(p.curve(z0, np.array([0.0]), KT), z0.z(KT)[None, :], atol=1e-15)


def test_factor_edit_is_exact(z0, stats):
    """Adding Δβ·B to a node changes that node's factor projection by exactly Δβ."""
    basis = stats.pca
    p = ExpectationPath("today", np.array([0.5]), np.random.default_rng(1).normal(0, 20, (1, len(KT))))
    b0 = basis.project((p.curve(z0, np.array([0.5]), KT)[0] - z0.z(KT)) / BP)
    db = np.array([10.0, -5.0, 3.0])
    q = ExpectationPath("today", p.node_t, p.node_dev + (basis.B @ db)[None, :])
    b1 = basis.project((q.curve(z0, np.array([0.5]), KT)[0] - z0.z(KT)) / BP)
    assert np.allclose(b1 - b0, db, atol=1e-10)
