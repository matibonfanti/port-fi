"""Fixed-coupon (Treasury-style) bonds: schedule, cash flows, accrued interest.

Conventions: semi-annual coupons of exactly c/2 per period (ACT/ACT ICMA), schedule rolled
backward from maturity with the end-of-month rule, settlement = as-of date, cash-flow times
ACT/365F from settlement. No business-day adjustment of payment dates (documented).
"""
from __future__ import annotations

import calendar
import datetime as dt
from dataclasses import dataclass

import numpy as np

from ..config import year_frac


def add_months(d: dt.date, months: int, eom: bool) -> dt.date:
    y, m = divmod(d.month - 1 + months, 12)
    y += d.year
    m += 1
    last = calendar.monthrange(y, m)[1]
    day = last if eom else min(d.day, last)
    return dt.date(y, m, day)


@dataclass
class Bond:
    maturity: dt.date
    coupon: float              # annual coupon rate, decimal
    freq: int = 2
    label: str = ""

    def schedule(self, settle: dt.date) -> list[dt.date]:
        """Coupon dates strictly after settle, plus the previous coupon date first."""
        eom = self.maturity.day == calendar.monthrange(self.maturity.year, self.maturity.month)[1]
        step = 12 // self.freq
        dates = [self.maturity]
        k = 1
        while dates[-1] > settle:
            dates.append(add_months(self.maturity, -step * k, eom))
            k += 1
        return dates[::-1]  # [prev_coupon <= settle, next, ..., maturity]

    def cashflows(self, settle: dt.date):
        """(times in years from settle, amounts per 1 face, payment dates)."""
        sched = self.schedule(settle)
        pay = sched[1:]
        t = np.array([year_frac(settle, d) for d in pay])
        c = np.full(len(pay), self.coupon / self.freq)
        c[-1] += 1.0
        return t, c, pay

    def accrued(self, settle: dt.date) -> float:
        sched = self.schedule(settle)
        prev, nxt = sched[0], sched[1]
        return self.coupon / self.freq * (settle - prev).days / (nxt - prev).days


def generic_bond(settle: dt.date, tenor_years: float, coupon: float, label: str = "") -> Bond:
    months = int(round(tenor_years * 12))
    mat = add_months(settle, months, eom=False)
    return Bond(mat, coupon, label=label or f"{tenor_years:g}y")
