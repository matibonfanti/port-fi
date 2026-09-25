"""Independent cross-checks of pricing, yields, accrued, durations and key-rate risk against QuantLib.

QuantLib builds its own schedule, coupon amounts (ActualActual Bond), accrued interest and bond
analytics; we hand it only our discount factors (at every cash-flow date, so interpolation plays no role).
"""
import datetime as dt

import numpy as np
import pytest

ql = pytest.importorskip("QuantLib")

from port.curves.interp import tent_weights
from port.instruments.bond import Bond
from port.instruments.position import own_yield

from .conftest import ASOF

BP = 1e-4


def qd(d: dt.date):
    return ql.Date(d.day, d.month, d.year)


def ql_setup(z0, bond: Bond, extra=()):
    ql.Settings.instance().evaluationDate = qd(ASOF)
    t, c, pay = bond.cashflows(ASOF)
    grid = sorted(set([ASOF + dt.timedelta(days=int(d)) for d in range(0, 31 * 366, 30)] + pay + list(extra)))
    times = np.array([(d - ASOF).days / 365.0 for d in grid])
    dfs = np.exp(-z0.z(np.maximum(times, 1e-8)) * times)
    dfs[0] = 1.0
    curve = ql.DiscountCurve([qd(d) for d in grid], list(dfs), ql.Actual365Fixed())
    curve.enableExtrapolation()
    h = ql.RelinkableYieldTermStructureHandle(curve)
    sched = bond.schedule(ASOF)
    eom = bond.maturity.day == (bond.maturity.replace(day=28) + dt.timedelta(days=4)).replace(day=1).__sub__(dt.timedelta(days=1)).day
    schedule = ql.Schedule(qd(sched[0]), qd(bond.maturity), ql.Period(ql.Semiannual), ql.NullCalendar(),
                           ql.Unadjusted, ql.Unadjusted, ql.DateGeneration.Backward, eom)
    qb = ql.FixedRateBond(0, 100.0, schedule, [bond.coupon], ql.ActualActual(ql.ActualActual.Bond))
    qb.setPricingEngine(ql.DiscountingBondEngine(h))
    return qb, h, curve


BONDS = [Bond(dt.date(2036, 8, 15), 0.04625), Bond(dt.date(2028, 8, 31), 0.04125),
         Bond(dt.date(2056, 8, 15), 0.05125), Bond(dt.date(2031, 2, 28), 0.0), Bond(dt.date(2033, 11, 15), 0.0875),
         Bond(dt.date(2027, 3, 31), 0.02)]


@pytest.mark.parametrize("bond", BONDS, ids=lambda b: f"{b.coupon*100:g}%{b.maturity}")
def test_price_accrued_yield(z0, bond):
    qb, h, _ = ql_setup(z0, bond)
    t, c, _ = bond.cashflows(ASOF)
    dirty = float(c @ np.exp(-z0.z(t) * t)) * 100
    assert dirty == pytest.approx(qb.dirtyPrice(), abs=1e-9)
    assert bond.accrued(ASOF) * 100 == pytest.approx(qb.accruedAmount(), abs=1e-10)
    assert (dirty - bond.accrued(ASOF) * 100) == pytest.approx(qb.cleanPrice(), abs=1e-9)
    # QuantLib's coupon amounts equal c/2 per period
    by_date = {}
    for cf in qb.cashflows():
        if cf.date() > qd(ASOF):
            by_date[cf.date().serialNumber()] = by_date.get(cf.date().serialNumber(), 0.0) + cf.amount()
    amounts = np.array([by_date[k] for k in sorted(by_date)])
    assert np.allclose(amounts / 100, c, atol=1e-12)
    # own continuous yield (ACT/365F from settlement)
    y = own_yield(t, c, dirty / 100)
    qy = qb.bondYield(ql.BondPrice(qb.cleanPrice(), ql.BondPrice.Clean), ql.Actual365Fixed(), ql.Continuous,
                      ql.Annual, qd(ASOF), 1e-14, 200)
    assert y == pytest.approx(qy, abs=1e-10)
    # yield-based modified duration and convexity
    rate = ql.InterestRate(y, ql.Actual365Fixed(), ql.Continuous, ql.Annual)
    d = np.exp(-y * t)
    mydur = (c * t * d).sum() / (c @ d)
    myconv = (c * t * t * d).sum() / (c @ d)
    assert mydur == pytest.approx(ql.BondFunctions.duration(qb, rate, ql.Duration.Modified, qd(ASOF)), rel=1e-9)
    assert myconv == pytest.approx(ql.BondFunctions.convexity(qb, rate, qd(ASOF)), rel=1e-9)


@pytest.mark.parametrize("bond", BONDS[:3], ids=lambda b: f"{b.coupon*100:g}%{b.maturity}")
def test_dv01_and_key_rates(z0, bond):
    qb, h, curve = ql_setup(z0, bond)
    t, c, _ = bond.cashflows(ASOF)
    df = np.exp(-z0.z(t) * t)
    dv01 = (c * t * df).sum() * BP * 100          # per 100 face, per +1bp
    base_h = ql.YieldTermStructureHandle(curve)

    def price_with(spread_ts):
        qb.setPricingEngine(ql.DiscountingBondEngine(ql.YieldTermStructureHandle(spread_ts)))
        return qb.dirtyPrice()

    up = price_with(ql.ZeroSpreadedTermStructure(base_h, ql.QuoteHandle(ql.SimpleQuote(0.5 * BP)), ql.Continuous,
                                                 ql.Annual, ql.Actual365Fixed()))
    dn = price_with(ql.ZeroSpreadedTermStructure(base_h, ql.QuoteHandle(ql.SimpleQuote(-0.5 * BP)), ql.Continuous,
                                                 ql.Annual, ql.Actual365Fixed()))
    assert dv01 == pytest.approx(dn - up, rel=1e-6)

    # key-rate (tent) durations: QuantLib linearly-interpolated zero-spread bumps at key dates
    key_days = [30, 91, 182, 365, 730, 1095, 1826, 2557, 3652, 7305, 10957]
    key_dates = [ASOF + dt.timedelta(days=d) for d in key_days]
    knots = np.array(key_days) / 365.0
    mine = (c * t * df) @ tent_weights(knots, t) * BP * 100
    for j in range(len(key_days)):
        qs = []
        for sgn in (0.5, -0.5):
            quotes = [ql.QuoteHandle(ql.SimpleQuote(sgn * BP if i == j else 0.0)) for i in range(len(key_days))]
            ts = ql.PiecewiseZeroSpreadedTermStructure(base_h, quotes, [qd(d) for d in key_dates])
            ts.enableExtrapolation()
            qs.append(price_with(ts))
        assert mine[j] == pytest.approx(qs[1] - qs[0], abs=1e-9 + 1e-6 * abs(mine[j]))
    assert mine.sum() == pytest.approx(dv01, rel=1e-12)


def test_forward_rates_match_quantlib(z0):
    pairs = [(0.25, 1.0), (1.0, 5.0), (2.0, 10.0), (0.5, 0.25), (1.5, 28.0)]
    ds = [(ASOF + dt.timedelta(days=int(round(a * 365))), ASOF + dt.timedelta(days=int(round((a + b) * 365))))
          for a, b in pairs]
    _, _, curve = ql_setup(z0, BONDS[0], extra=[d for p in ds for d in p])
    for d1, d2 in ds:
        a, b = (d1 - ASOF).days / 365, (d2 - ASOF).days / 365
        qf = curve.forwardRate(qd(d1), qd(d2), ql.Actual365Fixed(), ql.Continuous).rate()
        assert float(z0.fwd(a, b - a)) == pytest.approx(qf, abs=1e-12)
