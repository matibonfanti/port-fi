# PORT-FI — System design

A fixed-income scenario and return-attribution workstation. The engine is Python with numpy as its only
runtime dependency (cross-checked against QuantLib in tests); the UI is a no-build ES-module web app
(Preact + htm + D3, vendored). Two transports reach the same entry point (`port/bridge.py`):
* local: FastAPI (`uv run port`), which can refresh recent market data live;
* published: a static site where the engine runs in the visitor's browser (Pyodide in a Web Worker) on a
  committed data snapshot rebuilt every business day. Saved views/positions live in the browser.

## 1. Modules

```
port/
  config.py              key tenors, FOMC calendar, defaults, episode list
  data/treasury.py       UST par-yield history (treasury.gov CSV, cached per year)
  data/market.py         SOFR / EFFR / target range (NY Fed), on-the-run list (TreasuryDirect)
  data/sources.py        CurveSource interface  (USD Treasury now; EUR = ECB AAA Svensson later)
  curves/interp.py       vectorised PCHIP / Hermite, natural-spline basis matrices
  curves/zero_curve.py   ZeroCurve: exact bootstrap of par yields -> cc zero knots, z/df/fwd
  curves/history.py      fitted zero history at key tenors (cached), factor bases, PCA, covariances
  paths/path.py          ExpectationPath: anchor + deviation nodes -> Z_u(t, tau)
  paths/policy.py        market-implied policy path, user policy path -> compiled nodes
  paths/builders.py      presets, historical analogues
  instruments/bond.py    fixed-coupon bond schedule / cash flows / accrued
  instruments/position.py items (bond, steepener, flattener, butterfly) -> weighted lines, financing
  analytics/attribution.py  the decomposition engine (vs today, and priced-in + edge)
  analytics/breakeven.py    break-evens, Δlevel×Δslope heatmap, time-to-cover
  analytics/timing.py       same end-state reached early vs late
  analytics/risk.py         factor vols, ±1σ, return/vol, Monte-Carlo distribution
  analytics/summary.py      plain-English narrative
  api/server.py             FastAPI endpoints;  api/store.py SQLite for views & positions
web/                        UI (see §5)
tests/                      identities, property tests, QuantLib cross-checks
docs/METHODOLOGY.md         every formula and convention
```

## 2. Data flow

```
treasury.gov par yields ──fit──► z0(τ) (today)  ──► F(t,τ) forwards (exact, analytic)
            │                                  └──► Z_u(t,τ) = anchor(t,τ) + D(t,τ)   (user path)
            └──history──► zero knots per day ──► PCA / factor vols / covariance / analogues
position items ──► weighted bond lines (DV01- or PCA-neutral) ──► cash flows (T_i, c_i)

(z0, F, Z_u, lines, financing) ──► attribution engine on a t-grid [0,H]
      ──► returns over time, waterfalls, break-evens, heatmap, timing, risk, summary ──► JSON ──► UI
```
One POST `/api/analyze` returns everything the workspace needs, including the three curves on a
(t × τ) display grid, so the time slider animates client-side with no round trips.
During a drag the UI calls `analyze` with `fast=true` (skips Monte-Carlo, heatmap, timing).

## 3. How an expectation path is represented

Canonical form — every builder compiles to this:

```
view = { anchor: "forwards" | "today",
         nodes:  [ {t: 0.25, dev: [bp at each key tenor]}, ... ],   # deviation vs anchor
         spread_nodes: [bp, ...]          # optional credit-spread change per node
         time_interp: "pchip" | "linear",
         builder: {type: "nodes" | "policy" | "analogue", params: {...}} }   # provenance

Z_u(t, τ) = A(t, τ) + D(t, τ)
  A = z0(τ)             if anchor = today
  A = F(t, τ)           if anchor = forwards
  D(t, ·) = PCHIP_τ( d(t) )                     over key tenors, flat beyond ends
  d_j(t)  = PCHIP_t( (0,0), (t_1, d_j1), ... )  pinned D(0,·)=0, held after last node
```
Why deviations-vs-anchor: "market is right" and "curve unchanged" are both the zero deviation
(different anchors), a view stated vs forwards stays vs forwards between nodes, and the edge
(Z_u − F) is explicit. Conversion between "vs today" and "vs forwards" at a node is exact
(add F(t_k, τ_j) − z0(τ_j)), so all input modes edit the same nodes:

* Nodes / drag / typed key rates      → set d_j(t_k) (UI converts from level, vs-today, vs-fwd)
* Factor inputs (ΔL, ΔS, ΔC)         → d(t_k) += Δβ · B (B = loadings at key tenors, exact)
* Presets (parallel, bull/bear steepener/flattener, twist) → nodes = m · shape · ramp(t_k)
* Historical analogue                 → nodes (monthly) = z_hist(d0 + t_k) − z_hist(d0), anchor today
* Policy-path builder                 → nodes (monthly) vs forwards: avg deviation of your short-rate
  path from the priced path over [t, t+τ] (+ term-premium change), with a market-convergence speed.

Inflation adds a second layer with the same representation on the breakeven curve (anchor today / forward
breakevens + nodes, or compiled from CPI expectations), a realised CPI index path, and a pass-through share
that decides whether breakeven changes move nominal or real yields (`paths/inflation.py`).

## 4. Engine (all exact identities)

Per line, per t: V_y (own constant yield), V_R (today's curve, rolled), V_F (forwards),
V_U (user path), Cash(t) (financing account incl. coupons). Then

```
carry = V_y + Cash          roll = V_R − V_y          curve = V_U − V_R = Σ buckets|factors + convexity + residual
priced-in = V_F + Cash      edge = V_U − V_F = Σ buckets|factors + convexity + residual
total = V_U + Cash = carry + roll + curve = priced-in + edge
```
Bucket split uses cash-flow mapping onto key-rate tents (partition of unity ⇒ exact);
factor split projects the key-rate change onto the basis and books the orthogonal part as
"other shape" (exact). Convexity is the exact 2nd-order term; residual is what is left.

## 5. UI structure

```
┌ top bar: as-of date · units (% | bp | $) · factor basis (Parametric | PCA) · theme                           ┐
├ steps: ① position ② horizon & return ③ rates view ④ inflation view ⑤ target → result · data flags           ┤
├ left rail ─────────────┬ Curves (today / fwd@t / yours@t, positions rolling) ┬ Expectations builder ────┤
│ Position editor        │   time slider ▶ 0 … H                              │ Nodes | Relative | Policy│
│ Financing              │                                                   │ | Presets & analogues    │
│ Views (save/dup/cmp)   │                                                   │ live readout vs priced-in│
│ Summary (plain English)├ Return over time (hero, stacked) [vs today | priced-in + edge] ┬ Waterfall ───┤
│ Key metrics            ├ Break-even heatmap ΔL×ΔS ┬ Timing: early vs late ┬ Risk: ±1σ, distribution ┤
└────────────────────────┴───────────────────────────────────────────────────────────────────────────────┘
Tabs: Workspace · Compare (two views or two positions) · Methodology
```
