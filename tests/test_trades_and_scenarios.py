import numpy as np
import pytest

from port.analytics import breakeven, timing
from port.analytics.attribution import BP, KT, Book
from port.config import KEY_TENORS
from port.instruments.position import Financing, build_lines
from port.paths import builders
from port.paths.path import ExpectationPath
from port.paths.policy import PolicyPath

from .conftest import ASOF, ctx


def book(z0, stats, items, H=1.0, fin=None):
    return Book(z0, build_lines(items, ctx(z0), stats.pca), fin or Financing("flat", 4.0), H)


STEEP = {"kind": "steepener", "legs": [{"tenor": 2}, {"tenor": 10}], "weighting": "dv01", "size_mm": 10}
FLY = {"kind": "butterfly", "legs": [{"tenor": 2}, {"tenor": 5}, {"tenor": 10}], "weighting": "dv01", "size_mm": 10}


@pytest.mark.parametrize("item", [STEEP, {**STEEP, "kind": "flattener"}, FLY, {**FLY, "direction": "long_belly"}])
def test_dv01_neutral_trades_flat_to_small_parallel_moves(z0, stats, item):
    b = book(z0, stats, [item])
    leg_dv01 = abs(b.lines[-1].face) * 1e6 * float((b.lines[-1].c * b.lines[-1].t *
                                                     np.exp(-z0.z(b.lines[-1].t) * b.lines[-1].t)).sum()) * BP
    base = b.pnl_at(0.0, lambda tau: z0.z(tau)[None, :])[0]
    for s in (-5, -1, 1, 5):
        pnl = b.pnl_at(0.0, lambda tau: z0.z(tau)[None, :] + s * BP)[0] - base
        # first order is exactly zero; what remains is convexity (~ s^2), under 1% of the leg DV01 per bp^2
        assert abs(pnl) < 0.01 * leg_dv01 * s * s
    dv01, _, _, _ = b.exposures_at(0.0, lambda tau: z0.z(tau)[None, :])
    assert abs(dv01) < 1e-9 * leg_dv01


def test_pca_neutral_trades_have_no_level_exposure(z0, stats):
    for item in ({**STEEP, "weighting": "pca"}, {**FLY, "weighting": "pca"}):
        b = book(z0, stats, [item])
        _, _, fx, _ = b.exposures_at(0.0, lambda tau: z0.z(tau)[None, :], stats.pca)
        scale = np.abs(b.face).max() * 1e6 * 1e-3
        assert abs(fx[0]) < 1e-9 * scale
        if item["kind"] == "butterfly":
            assert abs(fx[1]) < 1e-9 * scale


def test_steepener_direction(z0, stats):
    b = book(z0, stats, [STEEP])
    steep = lambda tau: z0.z(tau)[None, :] + 10 * BP * np.interp(tau, [2, 10], [-0.5, 0.5])
    assert b.pnl_at(0.0, steep)[0] > b.pnl_at(0.0, lambda tau: z0.z(tau)[None, :])[0]


def test_policy_market_moves_reproduce_forwards(z0_up):
    pp = PolicyPath(z0_up, ASOF, {}, 1.0)
    c = pp.compile()
    assert np.max(np.abs(np.array([n["dev"] for n in c["nodes"]]))) < 1e-9
    # step path integrates exactly to today's curve over each inter-meeting interval
    e = pp.edges
    avg = [(b * z0_up.z(b) - a * z0_up.z(a)) / (b - a) for a, b in zip(e[:-1], e[1:])]
    assert np.allclose(pp.r_mkt, avg)


def test_policy_extra_hike_held(z0_up):
    base = PolicyPath(z0_up, ASOF, {}, 1.0)
    moves = (base.mu / BP).tolist()
    moves[0] += 25.0
    pp = PolicyPath(z0_up, ASOF, {"moves": moves, "half_life": "hold", "convergence_months": 0}, 1.0)
    t1 = pp.edges[1]
    D = pp.deviation(np.array([t1 + 0.05]), KT) / BP
    assert np.allclose(D, 25.0, atol=1e-9)           # +25bp across the whole curve after the meeting
    D0 = pp.deviation(np.array([t1 / 2]), np.array([t1 / 4])) / BP
    assert abs(D0[0, 0]) < 1e-9                      # before the meeting the short rate is unchanged


def test_policy_term_premium_phases_in(z0_up):
    pp = PolicyPath(z0_up, ASOF, {"tp": {"10": 20}}, 1.0)
    i10 = KEY_TENORS.index(10.0)
    assert pp.deviation(np.array([1.0]), KT)[0, i10] / BP == pytest.approx(20.0)
    assert pp.deviation(np.array([0.5]), KT)[0, i10] / BP == pytest.approx(10.0)


def test_timing_horizon_pnl_path_independent(z0, stats):
    b = book(z0, stats, [{"kind": "bond", "bond": {"tenor": 10}, "face_mm": 1}, STEEP])
    p = ExpectationPath("forwards", np.array([0.5, 1.0]), np.outer([0.4, 1.0], np.linspace(-30, 20, len(KT))))
    t = np.linspace(0, 1, 53)
    res = timing.timing(b, p, t, stats.parametric)
    pnl = [r["pnl_H"] for r in res["profiles"]]
    assert np.allclose(pnl, pnl[0], atol=1e-8 * b.gross_mv)
    paths = np.array([r["total"] for r in res["profiles"]])
    assert np.ptp(paths[:, len(t) // 2]) > 0            # but the paths differ in between


def test_breakevens_zero_the_pnl(z0, stats):
    H = 1.0
    b = book(z0, stats, [{"kind": "bond", "bond": {"tenor": 10}, "face_mm": 1}])
    be = breakeven.breakevens(b, H, stats.parametric)
    for base, fn in (("today", lambda tau: z0.z(tau)), ("forwards", lambda tau: z0.fwd(H, tau))):
        x = be[base]["parallel"]
        assert x is not None
        assert abs(b.pnl_at(H, lambda tau: fn(tau)[None, :] + x * BP)[0]) < 1e-3
        s = be[base]["slope"]
        if s is not None:
            L = stats.parametric.loadings
            assert abs(b.pnl_at(H, lambda tau: fn(tau)[None, :] + s * BP * L(tau)[None, :, 1])[0]) < 1e-3


def test_heatmap_origin_and_markers(z0, stats):
    H = 1.0
    b = book(z0, stats, [{"kind": "bond", "bond": {"tenor": 5}, "face_mm": 1}])
    p = ExpectationPath("today")
    hm = breakeven.heatmap(b, H, stats.parametric, p, "today", n=41)
    mid = 20
    assert hm["level"][mid] == pytest.approx(0) and hm["slope"][mid] == pytest.approx(0)
    assert hm["pnl"][mid][mid] == pytest.approx(b.pnl_at(H, lambda tau: z0.z(tau)[None, :])[0])
    assert hm["markers"]["view"] == pytest.approx([0, 0], abs=1e-9)
    # P&L falls as level rises for a long bond
    assert hm["pnl"][mid][0] > hm["pnl"][mid][-1]


def test_presets_shapes():
    kt = np.array(KEY_TENORS)
    i2, i10 = KEY_TENORS.index(2.0), KEY_TENORS.index(10.0)
    for kind, sign in (("bull_steepener", 1), ("bear_steepener", 1), ("bull_flattener", -1),
                       ("bear_flattener", -1), ("twist", 1)):
        v = builders.preset(kind, 20.0, 1.0)
        d = np.array(v["nodes"][-1]["dev"])
        assert (d[i10] - d[i2]) == pytest.approx(sign * 20.0)
    v = builders.preset("parallel", 25, 1.0, reach_years=0.5)
    p = ExpectationPath.from_dict(v)
    assert np.allclose(p.dev_knots(np.array([0.5, 0.75, 1.0])), 25.0)


def test_analogue_reproduces_history():
    from port.data.panel import Panel
    idx = np.arange(np.datetime64("2022-01-03"), np.datetime64("2023-06-01"))
    rng = np.random.default_rng(0)
    vals = 0.02 + np.cumsum(rng.normal(0, 5e-4, (len(idx), len(KT))), axis=0)
    zh = Panel(idx, list(KT), vals)
    v = builders.analogue(zh, "2022-01-03", 1.0)
    _, row = zh.row_on_or_before(np.datetime64("2023-01-03"))
    assert np.allclose(v["nodes"][-1]["dev"], (row - vals[0]) * 1e4)
    with pytest.raises(ValueError):          # never silently truncate an episode
        builders.analogue(zh, "2023-01-02", 1.0)
