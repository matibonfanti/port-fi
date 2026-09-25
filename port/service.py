"""Orchestration: market context per as-of date, data-quality flags, and the full analysis payload."""
from __future__ import annotations

import datetime as dt
import math
import time
from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np

from .analytics import breakeven, inverse, risk, summary, timing
from .analytics.attribution import BP, KT, MM, Book
from .config import BE_TENORS, FOMC_MEETINGS, KEY_LABELS, KEY_TENORS, RUNTIME, parse_date
from .curves import history
from .curves.interp import tent_weights
from .curves.zero_curve import RealCurve, fit_breakeven, fit_curve
from .data import market, sources, treasury
from .data.panel import to_day
from .instruments.position import Context, Financing, build_lines, factor_expo_unit
from .paths import builders, inflation
from .paths.path import ExpectationPath
from .paths.policy import PolicyPath

DISPLAY_TAU = np.unique(np.concatenate([[1 / 12, 2 / 12, 0.25, 0.5, 0.75], np.arange(1, 5.01, 0.25),
                                         np.arange(5.5, 10.01, 0.5), np.arange(11, 30.01, 1.0)]))
STD_TENORS = {1 / 12: "1M", 0.25: "3M", 0.5: "6M", 1.0: "1Y", 2.0: "2Y", 3.0: "3Y", 5.0: "5Y", 7.0: "7Y",
              10.0: "10Y", 20.0: "20Y", 30.0: "30Y"}


def flag(level, code, msg):
    return {"level": level, "code": code, "msg": msg}


@dataclass
class Market:
    asof: dt.date
    requested: str | None
    z0: object
    be0: object | None
    r0: object | None
    refs: dict
    flags: list = field(default_factory=list)

    def stats(self, window: float = 5.0) -> history.HistoryStats:
        return history.history_stats(self.asof, float(window))


def _data_flags(src_status: dict, latest: dt.date) -> list:
    out = []
    for kind, lab in (("nominal", "Treasury par curve"), ("real", "TIPS real curve")):
        st = src_status.get(kind, {})
        if RUNTIME == "browser":
            out.append(flag("info", f"{kind}_snapshot", f"{lab}: data snapshot through {st.get('last')}."))
        elif st.get("errors"):
            out.append(flag("warn", f"{kind}_fetch", f"{lab}: live refresh failed for {', '.join(st['errors'])}; "
                                                     f"using data through {st.get('last')}."))
    stale = (dt.date.today() - latest).days
    if stale > 5:
        out.append(flag("warn", "stale", f"Latest Treasury curve is {latest} ({stale} days old)."))
    return out


@lru_cache(maxsize=8)
def _market(asof_key: str, stamp: int) -> Market:
    src = sources.get("USD")
    req = None if asof_key == "latest" else asof_key
    d, ten, y, missing = src.par_curve(parse_date(req) if req else None)
    z0 = fit_curve(ten, y, d)
    latest = src.history("nominal").last
    flags = _data_flags(treasury.STATUS, latest)
    if req and parse_date(req) != d:
        flags.append(flag("info", "asof_moved", f"No Treasury curve published on {req}; using {d}, the previous business day."))
    std_missing = [STD_TENORS[c] for c in missing if c in STD_TENORS]
    if std_missing:
        flags.append(flag("warn", "tenors_missing", f"Tenors not published on {d}: {', '.join(std_missing)}. "
                          f"The zero curve is held flat beyond {max(ten):g}Y and below {min(ten)*12:g}M; key rates there are extrapolated."))
    fit_bp = (z0.par_yield(ten) - y) / BP
    worst = float(np.max(np.abs(fit_bp[ten >= 1]))) if (ten >= 1).any() else 0.0
    if worst > 5:
        flags.append(flag("warn", "fit", f"Smoothed curve misses a coupon benchmark by {worst:.1f}bp on {d}."))
    be0 = r0 = None
    try:
        dr, tr, yr, mr = src.par_curve(d, "real")
        if (d - dr).days > 7:
            raise ValueError("no recent real curve")
        be0 = fit_breakeven(z0, tr, yr)
        r0 = RealCurve(z0, be0)
        flags.append(flag("info", "be_short", f"Breakevens below {min(tr):g}Y are held at the {min(tr):g}Y level "
                          f"(Treasury publishes no TIPS real yields below {min(tr):g}Y)."))
        if dr != d:
            flags.append(flag("info", "real_date", f"TIPS real curve from {dr} (nominal {d})."))
    except Exception:
        flags.append(flag("info", "no_real", f"No TIPS real curve for {d} (published from 2003-01-02): "
                                             "inflation views and TIPS positions are unavailable."))
    refs = market.market_refs(d, latest)
    ms = market.STATUS
    if not ms.get("historical"):
        for k, lab in (("rates", "SOFR/EFFR"), ("securities", "On-the-run issues")):
            v = ms.get(k, "")
            if v.startswith("snapshot"):
                flags.append(flag("info", f"{k}_snap", f"{lab} from the data snapshot ({ms.get(k + '_asof')})."))
            elif v == "unavailable":
                flags.append(flag("warn", f"{k}_na", f"{lab} unavailable."))
    else:
        flags.append(flag("info", "historical", f"Historical as-of date: SOFR/EFFR and on-the-run issues are not "
                                                f"available for {d}; generic bonds are used and flagged per line."))
    return Market(d, req, z0, be0, r0, refs, flags)


def get_market(asof: str | None = None) -> Market:
    return _market(asof or "latest", int(time.time() // 3600))


def _clean(x):
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if isinstance(x, np.ndarray):
        return _clean(x.tolist())
    if isinstance(x, (np.floating, float)):
        f = float(x)
        return None if (math.isnan(f) or math.isinf(f)) else round(f, 10)
    if isinstance(x, (np.integer, np.bool_)):
        return x.item()
    return x


def market_info(asof: str | None = None) -> dict:
    m = get_market(asof)
    z0 = m.z0
    fit = z0.par_yield(z0.par_tenors)
    hist = sources.get("USD").history("nominal")
    pp = PolicyPath(z0, m.asof, {}, 1.0)
    out = {
        "asof": m.asof.isoformat(), "first_date": hist.first.isoformat(), "last_date": hist.last.isoformat(),
        "runtime": RUNTIME,
        "par": {"tenors": z0.par_tenors, "yields": z0.par_yields * 100, "fit_bp": (fit - z0.par_yields) / BP},
        "key_tenors": KEY_TENORS, "key_labels": KEY_LABELS, "be_tenors": BE_TENORS,
        "today_keys": z0.z(KT) * 100, "otr": m.refs.get("otr", []), "otr_tips": m.refs.get("otr_tips", []),
        "rates": m.refs.get("rates", {}), "implied_short": float(pp.r_mkt[0] * 100),
        "analogues": builders.analogue_list(), "presets": builders.PRESET_LABELS,
        "shapes": {k: f(KT) for k, f in builders.SHAPES.items()}, "flags": m.flags,
        "has_real": m.be0 is not None,
        "inflation_buckets": [{"label": l, "a": a, "b": b} for a, b, l in inflation.BUCKETS],
    }
    if m.be0 is not None:
        out["real"] = {"tenors": m.be0.par_tenors, "yields": m.be0.par_yields * 100,
                       "be_knots": m.be0.zeros * 100}
    from .api.seeds import default_docs
    out["defaults"] = default_docs((m.refs.get("rates") or {}).get("sofr", {}).get("rate"), m.be0 is not None)
    return _clean(out)


def t_grid(H: float) -> np.ndarray:
    n = int(np.clip(round(H * 52) + 1, 27, 157))
    return np.linspace(0.0, H, n)


def compile_view(view: dict, m: Market, H: float) -> tuple[dict, dict | None]:
    b = (view.get("builder") or {})
    if b.get("type") == "policy":
        pp = PolicyPath(m.z0, m.asof, b.get("params") or {}, H)
        v = {**view, **pp.compile()}
        v["spread_nodes"] = view.get("spread_nodes")
        return v, pp.report()
    return view, None


def _node_info(nodes, path, curve, P, own=None):
    """Per node: curves at key tenors and factor projections. `own` = the path the node devs belong to;
    `pt` = what other views add on top (inflation pass-through), so the UI can place handles exactly."""
    out = []
    for n in nodes or []:
        tk = float(n["t"])
        fk = curve.fwd(tk, KT)
        uk = path.curve(curve, np.array([tk]), KT)[0]
        pt = (uk - own.curve(curve, np.array([tk]), KT)[0]) / BP if own is not None else np.zeros(len(KT))
        out.append({"t": tk, "dev": n["dev"], "pt": pt, "today": curve.z(KT) * 100, "fwd": fk * 100, "user": uk * 100,
                    "beta_today": (uk - curve.z(KT)) @ P.T / BP, "beta_fwd": (uk - fk) @ P.T / BP,
                    "curve_fwd": curve.fwd(tk, DISPLAY_TAU) * 100,
                    "curve_user": path.curve(curve, np.array([tk]), DISPLAY_TAU)[0] * 100})
    return out


def analyze(req: dict) -> dict:
    t0 = time.time()
    m = get_market(req.get("asof"))
    z0 = m.z0
    flags = list(m.flags)
    H = float(req.get("horizon", 1.0))
    if not (1 / 24 <= H <= 3.0):
        raise ValueError("horizon must be between 2 weeks and 3 years")
    fast = bool(req.get("fast", False))
    window = float(req.get("pca_window", 5.0))
    stats = m.stats(window)
    if stats.truncated:
        flags.append(flag("warn", "window", f"Only {stats.window[0]} → {stats.window[1]} of history exists for the "
                                            f"{window:g}y risk/PCA window."))
    basis_kind = req.get("basis", "parametric")
    basis = stats.basis(basis_kind)
    view_in = req.get("view") or {"anchor": "forwards", "nodes": []}
    view, policy_report = compile_view(view_in, m, H)
    policy_active = policy_report is not None
    if policy_report is None:
        policy_report = PolicyPath(z0, m.asof, {}, H).report()
    est = [x["date"] for x in policy_report["meetings"] if x["estimated"] and x["t"] <= H]
    if policy_active and est:
        flags.append(flag("info", "fomc_est", f"FOMC dates within the horizon are estimated: {', '.join(est[:4])}{'…' if len(est) > 4 else ''}."))
    path = ExpectationPath.from_dict(view)
    infl = inflation.build(view.get("inflation"), m.be0, view.get("anchor", "forwards"), H) if m.be0 is not None else None
    nominal_path = path
    w_pt = float(((view.get("inflation") or {}).get("passthrough", 1.0)))
    if infl is not None and infl.mode in ("expectations", "nodes") and w_pt > 0:
        path = inflation.FisherPath(nominal_path, infl, w_pt)
    pos = req.get("position") or {}
    fin = Financing.from_dict(pos.get("financing"))
    ctx = Context(m.asof, z0, m.r0, m.refs.get("otr", []), m.refs.get("otr_tips", []), [])
    lines = build_lines(pos.get("items") or [], ctx, stats.pca)
    flags += ctx.flags
    if not lines:
        raise ValueError("position has no lines")
    if fin.basis == "total" and any(l.face < 0 for l in lines):
        flags.append(flag("info", "total_short", "Holding-period (unfunded) return with short lines: short sale "
                                                 "proceeds earn nothing; excess-over-financing is usually the right basis for trades."))
    book = Book(z0, lines, fin, H, m.be0, m.r0)
    t = t_grid(H)
    att = book.attribute(path, t, basis, infl)
    P = basis.projector

    # ----------------------------------------------------------- curves for display
    curves = {"tau": DISPLAY_TAU, "today": z0.z(DISPLAY_TAU) * 100,
              "fwd": z0.fwd(t[:, None], DISPLAY_TAU[None, :]) * 100, "user": path.curve(z0, t, DISPLAY_TAU) * 100}
    keys = {"today": z0.z(KT) * 100, "fwd": z0.fwd(t[:, None], KT[None, :]) * 100, "user": path.curve(z0, t, KT) * 100,
            "pt": (path.curve(z0, t, KT) - nominal_path.curve(z0, t, KT)) / BP}
    infl_out = None
    if infl is not None:
        be0, r0 = m.be0, m.r0
        BU = infl.be_curve(t, DISPLAY_TAU)
        infl_out = {
            **infl.report, "spec": view.get("inflation") or {"mode": "follow"},
            "passthrough": w_pt if infl.mode in ("expectations", "nodes") else 0.0,
            "passthrough_H_bp": ((path.curve(z0, np.array([H]), KT)[0] - nominal_path.curve(z0, np.array([H]), KT)[0]) / BP),
            "curves": {"be_today": be0.z(DISPLAY_TAU) * 100, "be_fwd": be0.fwd(t[:, None], DISPLAY_TAU[None, :]) * 100,
                       "be_user": BU * 100, "real_today": r0.z(DISPLAY_TAU) * 100,
                       "real_fwd": r0.fwd(t[:, None], DISPLAY_TAU[None, :]) * 100,
                       "real_user": (path.curve(z0, t, DISPLAY_TAU) - BU) * 100},
            "keys": {"today": be0.z(KT) * 100, "fwd": be0.fwd(t[:, None], KT[None, :]) * 100,
                     "user": infl.be_curve(t, KT) * 100},
            "index": {"priced": book.index_F(t), "user": np.asarray(infl.index_fn(t))},
            "nodes": _node_info(infl.be_path.to_nodes() if (view.get("inflation") or {}).get("mode") == "nodes" else [],
                                infl.be_path, be0, P),
        }

    # ----------------------------------------------------------- position details
    line_info = []
    for i, l in enumerate(lines):
        crv = book.curve_of(l)
        df = np.exp(-(crv.z(l.t) + l.spread) * l.t)
        g = l.c * l.t * df
        acc = l.bond.accrued(m.asof)
        y_sa = 2 * (np.exp(book.y0[i] / 2) - 1)
        mat_t = float(l.t[-1])
        taus = np.maximum(mat_t - t, 0)
        line_info.append({
            "label": l.label, "role": l.role, "item": l.item, "face_mm": l.face, "coupon": l.bond.coupon * 100,
            "maturity": l.bond.maturity.isoformat(), "mat_t": mat_t, "dirty": book.P0[i] * 100, "real": l.real,
            "accrued": acc * 100, "clean": (book.P0[i] - acc) * 100, "yield_sa": y_sa * 100,
            "yield_cc": book.y0[i] * 100, "spread_bp": l.spread / BP, "credit": l.credit,
            "dv01": -g.sum() * BP * MM * l.face, "mod_dur": g.sum() / book.P0[i],
            "convexity": (l.c * l.t**2 * df).sum() / book.P0[i],
            "krd": -(g @ tent_weights(KT, l.t)) * BP * MM * l.face,
            "factor_expo": -factor_expo_unit(l, crv, basis) * MM * l.face,
            "mv": book.P0[i] * MM * l.face, "roll": {"tau": taus.tolist()}, "total": att.per_line_total[i],
        })
    dv01_tot = sum(li["dv01"] for li in line_info)
    krd_tot = np.sum([li["krd"] for li in line_info], axis=0)
    fx_tot = np.sum([li["factor_expo"] for li in line_info], axis=0)

    # ----------------------------------------------------------- attribution payload
    def sp(s):
        return {"total": s.total, "fo": s.fo, "convexity": s.convexity, "residual": s.residual, "buckets": s.buckets,
                "factors": s.factors, "other": s.other, "beta": s.beta, "fo_real": s.fo_real, "fo_be": s.fo_be}

    c, e = att.curve, att.edge
    attr = {"carry": att.carry, "roll": att.roll, "spread": att.spread, "inflation": att.inflation, "total": att.total,
            "priced_in": att.priced_in, "curve": sp(c), "edge": sp(e), "priced": sp(att.priced)}
    identity = {
        "vs_today": float(np.max(np.abs(att.carry + att.roll + c.total + att.spread + att.inflation - att.total))),
        "market": float(np.max(np.abs(att.priced_in + e.total + att.spread + att.inflation - att.total))),
        "buckets": float(np.max(np.abs(c.buckets.sum(1) + c.convexity + c.residual - c.total))),
        "factors": float(np.max(np.abs(c.factors.sum(1) + c.other + c.convexity + c.residual - c.total))),
        "real_be": float(np.max(np.abs(c.fo_real + c.fo_be - c.fo))),
    }
    target_pct = req.get("target_pct")
    target_pct = None if target_pct in (None, "") else float(target_pct)
    inv = inverse.solve_all(book, path, infl, H, basis, target_pct)
    out = {
        "asof": m.asof.isoformat(), "horizon": H, "basis": basis_kind, "return_basis": fin.basis,
        "t": t, "dates": [(m.asof + dt.timedelta(days=int(round(x * 365)))).isoformat() for x in t],
        "curves": curves, "keys": keys, "inflation": infl_out,
        "view": {**view, "nodes": view.get("nodes") or []}, "nodes": _node_info(view.get("nodes"), path, z0, P, nominal_path),
        "policy": policy_report, "policy_active": policy_active,
        "factor": {"labels": basis.labels, "B": basis.B, "vols_ann_bp": basis.vols / BP,
                   "explained": stats.pca.explained, "window": list(stats.window),
                   "loadings_display": basis.loadings(DISPLAY_TAU)},
        "position": {"lines": line_info, "gross_mv": book.gross_mv, "dv01": dv01_tot, "krd": krd_tot,
                     "factor_expo": fx_tot, "has_real": book.has_real,
                     "financing": {"mode": fin.mode, "basis": fin.basis, "rate_pct": fin.rate_pct,
                                   "spread_bp": fin.spread_bp, "cc_rate": fin.cc_rate(H) * 100,
                                   "implied_mm_pct": Financing.mm_from_cc(float(z0.z(H)), H)}},
        "attribution": attr, "identity": identity, "inverse": inv,
    }
    out["breakevens"] = breakeven.breakevens(book, H, basis, path, infl)
    out["cover"] = breakeven.time_to_cover(book, att, basis, float(req.get("cover_move_bp", 25.0)))
    out["risk"] = risk.horizon_risk(book, path, H, stats, basis_kind, float(att.total[-1]), infl, do_mc=not fast)
    if not fast:
        out["heatmap"] = breakeven.heatmap(book, H, basis, path, infl, req.get("heat_base", "today"),
                                           levels=inverse.targets(book, H, target_pct))
        out["timing"] = timing.timing(book, path, t, basis, infl)
    out["summary"] = summary.narrative(out, att, book, basis, H)
    out["flags"] = flags
    out["elapsed_ms"] = (time.time() - t0) * 1000
    return _clean(out)


def compile_analogue(req: dict) -> dict:
    m = get_market(req.get("asof"))
    zh = history.zero_history().upto(m.asof)
    return _clean(builders.analogue(zh, req["start"], float(req.get("horizon", 1.0)), float(req.get("scale", 1.0))))


def compile_preset(req: dict) -> dict:
    return _clean(builders.preset(req["kind"], float(req.get("magnitude_bp", 25)), float(req.get("horizon", 1.0)),
                                  req.get("anchor", "today"), req.get("reach_years")))
