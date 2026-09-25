import datetime as dt

import numpy as np
import pytest

from port.config import KEY_TENORS
from port.curves.history import stats_from_changes
from port.curves.zero_curve import RealCurve, fit_breakeven, fit_curve
from port.instruments.position import Context

ASOF = dt.date(2026, 9, 24)
TENORS = np.array([1 / 12, 1.5 / 12, 2 / 12, 0.25, 1 / 3, 0.5, 1, 2, 3, 5, 7, 10, 20, 30])
PAR = np.array([4.01, 4.10, 4.18, 4.24, 4.33, 4.34, 4.51, 4.87, 4.99, 5.03, 5.10, 5.18, 5.53, 5.47]) / 100
REAL_TENORS = np.array([5.0, 7.0, 10.0, 20.0, 30.0])
REAL = np.array([2.70, 2.77, 2.85, 3.08, 3.21]) / 100
INVERTED = np.array([5.50, 5.49, 5.48, 5.45, 5.42, 5.35, 5.10, 4.70, 4.45, 4.20, 4.15, 4.10, 4.40, 4.25]) / 100


def synthetic_stats(seed=0):
    """Factor stats from simulated daily changes with a realistic level/slope/curvature structure."""
    rng = np.random.default_rng(seed)
    kt = np.array(KEY_TENORS)
    lvl = np.ones_like(kt)
    slope = np.tanh((np.log(kt) - np.log(3)) / 1.2)
    curv = np.exp(-((np.log(kt) - np.log(5)) ** 2) / 1.0) - 0.4
    f = rng.standard_normal((2500, 3)) * np.array([6e-4, 3e-4, 1.2e-4])
    X = f @ np.vstack([lvl, slope, curv]) + rng.standard_normal((2500, len(kt))) * 3e-5
    return stats_from_changes(X, None, 10.0, ("sim", "sim"))


@pytest.fixture(scope="session")
def stats():
    return synthetic_stats()


@pytest.fixture(scope="session", params=["upward", "inverted"])
def z0(request):
    y = PAR if request.param == "upward" else INVERTED
    return fit_curve(TENORS, y, ASOF)


@pytest.fixture(scope="session")
def z0_up():
    return fit_curve(TENORS, PAR, ASOF)


@pytest.fixture(scope="session")
def curves():
    """(nominal, breakeven, real) on the upward curve with realistic TIPS yields."""
    z0 = fit_curve(TENORS, PAR, ASOF)
    be0 = fit_breakeven(z0, REAL_TENORS, REAL)
    return z0, be0, RealCurve(z0, be0)


def ctx(z0, r0=None, flags=None):
    return Context(ASOF, z0, r0, [], [], flags if flags is not None else [])
