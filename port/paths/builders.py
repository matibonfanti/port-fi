"""Presets and historical analogues, compiled to canonical view nodes."""
from __future__ import annotations

import datetime as dt

import numpy as np

from ..config import ANALOGUES, KEY_TENORS

KT = np.array(KEY_TENORS)


def psi(tau):
    """Long-end weight: 0 at <= 2y, 1 at >= 10y, smoothstep in log-maturity."""
    x = np.clip((np.log(np.asarray(tau, float)) - np.log(2)) / (np.log(10) - np.log(2)), 0, 1)
    return x * x * (3 - 2 * x)


def belly(tau):
    """Hump centred on 5y in log-maturity: 1 at 5y, ~0.5 at 2y/10y, ~0 at 3m and 30y."""
    x = (np.log(np.asarray(tau, float)) - np.log(5.0)) / 0.78
    return np.exp(-0.5 * x * x)


SHAPES = {
    "parallel": lambda t: np.ones_like(t),
    "bull_steepener": lambda t: -(1 - psi(t)),   # front-led rally; 2s10s steepens by m
    "bear_steepener": lambda t: psi(t),          # long-end-led selloff
    "bull_flattener": lambda t: -psi(t),         # long-end-led rally
    "bear_flattener": lambda t: 1 - psi(t),      # front-led selloff
    "twist": lambda t: psi(t) - 0.5,             # pivot ~5y; 2s10s steepens by m
    "belly_rally": lambda t: -belly(t),          # 5y falls by m, wings (<=1y, >=20y) ~unchanged
    "belly_selloff": lambda t: belly(t),
}
PRESET_LABELS = {
    "unchanged": "Curve unchanged", "forwards": "Forwards realised",
    "parallel": "Parallel", "bull_steepener": "Bull steepener", "bear_steepener": "Bear steepener",
    "bull_flattener": "Bull flattener", "bear_flattener": "Bear flattener", "twist": "Twist (pivot 5y)",
    "belly_rally": "Belly rally", "belly_selloff": "Belly selloff",
}


def preset(kind: str, magnitude_bp: float, horizon: float, anchor: str = "today", reach_years=None) -> dict:
    if kind == "unchanged":
        return {"anchor": "today", "nodes": [], "time_interp": "pchip"}
    if kind == "forwards":
        return {"anchor": "forwards", "nodes": [], "time_interp": "pchip"}
    shape = SHAPES[kind](KT) * magnitude_bp
    T = horizon if reach_years is None else max(float(reach_years), 1 / 52)
    times = sorted(set([min(T, horizon), horizon] + ([T / 2] if T > 0.1 else [])))
    nodes = [{"t": float(t), "dev": (shape * min(1.0, t / T)).tolist()} for t in times if t > 0]
    return {"anchor": anchor, "nodes": nodes, "time_interp": "linear"}


def analogue(zhist, start: str, horizon: float, scale: float = 1.0) -> dict:
    """Apply the zero-curve changes observed from `start` over the same elapsed time.
    zhist: Panel of key-tenor zeros. Raises if the episode runs past the available history."""
    h = zhist
    d0, base = h.row_on_or_before(start)
    if d0 is None:
        raise ValueError(f"analogue start {start} is before the history ({h.first})")
    end = d0 + dt.timedelta(days=int(round(horizon * 365)))
    if end > h.last:
        raise ValueError(f"analogue from {d0} needs data to {end}, history ends {h.last}; shorten the horizon or pick an earlier start")
    months = np.arange(1, int(np.ceil(horizon * 12 - 1e-9)) + 1) / 12.0
    times = np.unique(np.concatenate([np.minimum(months, horizon), [horizon]]))
    nodes = []
    for t in times:
        _, row = h.row_on_or_before(d0 + dt.timedelta(days=int(round(t * 365))))
        dev = (row - base) * 1e4 * scale
        if not np.all(np.isfinite(dev)):
            raise ValueError(f"analogue has missing key tenors around {d0 + dt.timedelta(days=int(round(t * 365)))}")
        nodes.append({"t": float(t), "dev": dev.tolist()})
    return {"anchor": "today", "nodes": nodes, "time_interp": "pchip", "meta": {"from": str(d0), "to": str(end)}}


def analogue_list():
    return [{"key": k, "label": l, "start": s, "desc": d} for k, l, s, d in ANALOGUES]
