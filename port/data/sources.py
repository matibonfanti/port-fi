"""Curve sources. The engine consumes zero curves plus histories of key-tenor zeros; another market
(e.g. EUR via the ECB AAA Svensson curve) only needs to implement this interface."""
from __future__ import annotations

from typing import Protocol

from . import treasury
from .panel import Panel


class CurveSource(Protocol):
    currency: str
    label: str

    def par_curve(self, asof, kind: str = "nominal"):
        """(curve date, tenors, par yields as decimals, missing tenors) on or before asof."""

    def history(self, kind: str = "nominal") -> Panel:
        """Daily par yields (percent), columns = tenors in years."""


class USTreasury:
    currency = "USD"
    label = "US Treasury par curves (treasury.gov CMT; TIPS real yields)"

    def par_curve(self, asof=None, kind="nominal"):
        return treasury.par_curve(asof, kind)

    def history(self, kind="nominal"):
        return treasury.history(kind)


SOURCES: dict[str, CurveSource] = {"USD": USTreasury()}


def get(currency: str = "USD") -> CurveSource:
    return SOURCES[currency]
