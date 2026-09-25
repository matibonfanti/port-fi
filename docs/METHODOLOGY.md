# PORT·FI methodology

This document covers every formula and convention the engine uses, and every simplification it
makes. Notation: t is the scenario date (years from the as-of date, t ∈ [0, H]), τ is time to
maturity *at that date*, T is a calendar cash-flow time measured from today. Rates are decimals
internally; bp = 1e-4.

---

## 1. Conventions

| Item | Convention |
|---|---|
| Valuation / settlement | the curve as-of date (no T+1 lag) |
| Time measure | ACT/365F from settlement: `T = days / 365` |
| Zero rates | continuously compounded, `DF(T) = exp(−z(T)·T)` |
| Displayed bond yields | semi-annual bond-equivalent, `y_sa = 2(e^{y_cc/2} − 1)` |
| Coupons | semi-annual, exactly c/2 per period (ACT/ACT ICMA regular periods), schedule rolled back from maturity, end-of-month rule, no business-day adjustment |
| Accrued | `c/2 · (settle − prev coupon)/(next − prev)` (actual days) |
| Prices | per 1 face internally; shown per 100; P&L in $ for the position as sized (faces in $mm), "$/1mm" when the reference leg is 1mm |
| % / bp returns | P&L ÷ gross market value (Σ |face·dirty price|) × 100 / × 1e4; rate levels shown to 2 decimals |
| Return basis | holding-period return (unfunded) or excess over financing — §5.1 |
| Repo / cash quote | money-market ACT/360 simple rate for the horizon term |

Pricing, accrued, coupon amounts, yield, duration, convexity, DV01, key-rate DV01s and forward
rates are cross-checked against QuantLib 1.43 in `tests/test_quantlib_crosscheck.py` (agreement
to 1e-9 in price; QuantLib builds its own schedule and coupons).

---

## 2. Today's curve z₀(τ)

**Data.** US Treasury par yield curve (CMT, treasury.gov), daily since 1990. Tenors: 1, 1.5, 2, 3,
4, 6 months; 1, 2, 3, 5, 7, 10, 20, 30 years (whatever is published on the day).

**Instruments.**
* Bills (τ ≤ 6m): bond-equivalent simple yield, `DF(τ) = 1 / (1 + y·τ)`.
* Coupon tenors (τ ≥ 1y): par bonds with semi-annual coupon y/2 at times k/2:
  `1 = (y/2) Σ_{k=1}^{2τ} DF(k/2) + DF(τ)`.

**Representation.** Zero rates z_k at knots {1m, 3m, 6m, 1y, 2y, 3y, 5y, 7y, 10y, 15y, 20y, 30y},
natural cubic spline in maturity, flat beyond the first/last knot. The spline is linear in the knot
values, `z(τ) = S(τ)·z_knots`.

**Smoothed fit (default).** Minimise

    Σ_i w_i (ŷ_i(z) − y_i)²  +  λ ∫ f''(s)² ds ,   f(s) = z(s) + s z'(s)  (instantaneous forward)

with errors in bp, `w = 0.3` for bills and 1 for coupons, `λ = 2e-4` (f in bp, s in years), solved by
Gauss–Newton with analytic Jacobians (`∂DF/∂z_k = −T·DF·S_k`). Why smooth: bill yields carry
supply/debt-ceiling noise; an exact fit turns that noise into oscillating forwards, which would
contaminate "what is priced in" (the policy path, the forward curve, roll-down). Typical residuals:
coupons < 1bp, bills a few bp. Residuals are shown in the Market data card. An exact-fit mode
(`fit_curve(..., method="exact")`, Newton on knots at the instrument tenors) is available and tested
to reprice every input to 1e-12.

**Simplification.** Bonds are priced off this fitted curve (plus an optional constant Z-spread), not
at their quoted market prices. Rich/cheap to the curve is ignored.

---

## 3. The three curves over time

1. **Today (unchanged):** `z₀(τ)` held fixed in maturity for every t.
2. **Market-implied (forwards):** the curve at date t priced in by today's curve,

       F(t, τ) = [ (t+τ) z₀(t+τ) − t z₀(t) ] / τ ,     exp(−F τ) = DF₀(t+τ)/DF₀(t)

   and `F(t, 0⁺) = f(t)`, the instantaneous forward.
3. **Your expected path:** `Z_u(t, τ)`, see §4.

---

## 4. Expectation paths

### 4.1 Canonical representation

    Z_u(t, τ) = A(t, τ) + D(t, τ)
    A(t, τ)   = z₀(τ)        (anchor "today")      or      F(t, τ)   (anchor "forwards")
    D(t, ·)   = PCHIP over the key tenors of d(t)                        (flat beyond 1m / 30y)
    d_j(t)    = interpolation in t through (0, 0), (t₁, d_j1), …, (t_K, d_jK); held after t_K

Key tenors (knots of every deviation, and the key-rate buckets):
1M 3M 6M 1Y 2Y 3Y 5Y 7Y 10Y 20Y 30Y. Time interpolation is PCHIP (monotone, no overshoot) or
linear. `D(0, ·) = 0` pins the path to today.

Why deviations against an anchor: "market is right" is the forwards anchor with no nodes; "curve
unchanged" is the today anchor with no nodes; a view stated relative to the forwards stays relative
to them between nodes, and the edge `Z_u − F` is explicit.

**Rebasing** a node between anchors is exact: `d_today = d_fwd + (F(t_k, τ_j) − z₀(τ_j))`. Only the
between-node interpolation depends on the anchor.

### 4.2 Input modes (all compile to nodes)

* **Nodes / drag / typed levels.** Set `d_j(t_k)` from a level (`level − A`), a change vs today
  (`z₀ + Δ − A`) or a change vs forwards (`F + Δ − A`) at node dates.
* **Factor terms.** Adding `Δβ·B_k` (loadings at the key tenors) to a node changes its factor
  projection by exactly `Δβ` (the projector satisfies `P·B = I`), leaving the other factors and the
  non-factor shape untouched. Optionally applied to all nodes scaled by `t_q / t_k`.
* **Relative views.** "10Y +25bp vs today (or vs forwards) at this node / all nodes ∝ time".
* **Presets.** shape(τ) × magnitude × ramp(t). With `ψ(τ)` a smoothstep in log-maturity from 0 (≤2y)
  to 1 (≥10y):
  parallel `1`; bull steepener `−(1−ψ)`; bear steepener `ψ`; bull flattener `−ψ`;
  bear flattener `1−ψ`; twist `ψ − ½`. For the curve shapes the magnitude is the 2s10s change.
  Ramp: reached gradually by the horizon, by 3 months, or immediately; relative to today or to the
  forwards; replace the path or add to it.
* **Historical analogues.** `d(t_k) = z_hist(d₀ + t_k) − z_hist(d₀)` at monthly nodes, anchor today,
  optionally scaled. Uses the fitted zero history (same smoothed fit), only data up to the as-of date.
* **Policy-rate path builder** — §4.3.

### 4.3 Policy-rate path builder

*Market-implied path.* FOMC decisions take effect the day after the meeting (2026–27 dates from the
Fed; 2028 estimated and flagged). The overnight rate is a step function whose level on each
inter-meeting interval `[e_k, e_{k+1})` equals the average instantaneous forward over it:

    r_mkt,k = [ e_{k+1} z₀(e_{k+1}) − e_k z₀(e_k) ] / (e_{k+1} − e_k)

so the steps integrate exactly to today's curve. Priced moves are `μ_k = r_mkt,k − r_mkt,k−1`.
Convention: forwards are read as expectations (zero term premium in the forwards). This is the
standard "what is priced" reading; it attributes any term premium in the front end to expectations.

*Your path.* Same starting level; your move per meeting `u_k` (or a smooth path of levels at chosen
dates, averaged per interval). Deviation `δ_k = r_user,k − r_mkt,k`. After the last explicit meeting δ
decays to zero with a half-life h (or is held).

*Expected curve at date t* (compiled to deviation-vs-forwards nodes, monthly + meeting dates):

    D(t, τ) = (1/τ) [ ∫_t^{min(t+τ, m*)} δ  +  λ(t) ∫_{min(t+τ, m*)}^{t+τ} δ ]  +  ΔTP(τ) · min(1, t/H)

* `m*` is the next decision after t: the rate until then is already set, so that part is known;
* `λ(t) = min(1, t / T_conv)` is how fast the market converges to your path for future meetings;
* `ΔTP(τ)` is your term-premium change vs what is priced, set at 2/5/10/30y and PCHIP-interpolated
  (0 at τ = 0), phased in linearly to the horizon.

Hence *expected curve = forwards + average (your − priced) short rate over [t, t+τ] + term premium
change*, i.e. expected average short rate plus term premium. With your moves equal to the priced
moves and ΔTP = 0 the path is exactly the forwards (tested).

### 4.4 Credit spread path

A line may carry a constant Z-spread `s₀` over the Treasury curve. A view may carry a spread change
per node (bp), interpolated in time like the rate deviations and applied flat across maturities to
credit lines only. The "priced-in" spread path is unchanged spreads.

### 4.5 Inflation: breakevens, real yields and CPI

*Data.* Treasury real (TIPS) par yields at 5/7/10/20/30y (published since 2003-01-02).

*Breakeven curve.* b(τ) is a natural cubic spline through knots at the TIPS tenors, held flat below the
shortest and above the longest. It solves, exactly (Newton, analytic Jacobian), that real par bonds
(semi-annual real coupon y/2) discounted on the real curve `r(τ) = z(τ) − b(τ)` price at par. Below 5y
there is no TIPS data, so b is held at the 5y level — this is flagged in the UI on every analysis.

*Market-implied ("priced") inflation.* By the same zero-premium convention as for rates: forward
breakevens `Bf(t, τ) = F_nominal(t, τ) − F_real(t, τ)` (exact, since forwards are linear in z), and CPI index
accretion `I_F(t) = exp(b(t)·t) = DF_real(t)/DF_nominal(t)`. Breakevens contain inflation-risk and liquidity
premia; they are a pricing reference, not a forecast.

*Your inflation view* (per view, one of):
* **follow** the rates view (unchanged if the nominal anchor is today, priced if it is forwards);
* **priced**: `B_u = Bf`, `I_u = I_F`;  **unchanged**: `B_u = b0`, `I_u = I_F`;
* **CPI expectations**: average CPI inflation (% a year) for year 1, year 2, years 3–5, 6–10, 11–30.
  With δ(s) the difference between your and the priced rate (continuously compounded) per bucket:
  `I_u(t) = I_F(t)·exp(∫₀ᵗ δ)` (realised) and
  `B_u(t, τ) = Bf(t, τ) + λ(t)·(1/τ)∫ₜ^{t+τ} δ + ΔIRP(τ)·min(1, t/H)` (priced at t),
  λ the convergence speed, ΔIRP your inflation-risk-premium change at 2/5/10/30y;
* **breakeven curve**: anchor (today / forwards) + deviation nodes at the key tenors (drag or type), like
  the rates view, plus a flat realised CPI rate (or priced).

*Pass-through.* Whether a breakeven change moves nominal or real yields is a modelling choice, so it is an
input w ∈ [0, 1]: `Z'(t, τ) = Z_u(t, τ) + w·(B_u(t, τ) − B_base(t, τ))`, B_base the breakeven path implied
by the nominal anchor alone. w = 1 (default for inflation views) holds real yields — the Fisher reading;
w = 0 keeps nominal yields exactly as you set them and real yields absorb the change. The real path is
`R_u = Z' − B_u`.

---

## 5. Positions

* **Bond:** face (signed, $mm), optional Z-spread.
* **Steepener / flattener:** front and back legs. Size = back-leg face. Steepener = long front,
  short back. DV01-neutral: `N_front = N_back · DV01_back / DV01_front`. PCA-neutral: the same with
  exposures to PC1 (level) instead of parallel DV01.
* **Butterfly:** wing/belly/wing, size = belly face, sell-belly or buy-belly. DV01-neutral: each wing
  carries half of the belly DV01. PCA-neutral: wings solve exposure to PC1 and PC2 = 0.
* **TIPS:** real coupon, principal indexed to CPI. The index ratio is normalised to 1.00 at the valuation
  date (face = inflation-adjusted principal today); cash flows are real, valued on the real curve and scaled
  by the index ratio path. Deflation floor, the 3-month indexation lag and CPI seasonality are ignored.
* **Breakeven trade:** long TIPS / short nominal (or the reverse). Size = TIPS face. Weighted DV01-neutral
  (TIPS real DV01 = nominal DV01) or market-value neutral.
* **Portfolio:** any list of the above.

Weights are set at inception on today's curve; they are not rebalanced (a DV01-neutral trade drifts
as its legs age — visible in the break-evens and risk at the horizon).

**Sensitivities.** Parallel DV01 per unit face `= Σ c_i T_i DF_i · 1bp`. Key-rate DV01 with linear
tents `h_j(T)` on the key tenors (partition of unity): `KRD_j = Σ c_i T_i DF_i h_j(T_i) · 1bp`, so
Σ_j KRD_j = DV01 exactly. Factor exposure `= Σ c_i T_i DF_i L_k(T_i) · 1bp`.

### 5.1 Return basis and financing

* **Holding-period return (unfunded):** `R(H) = (V_H + coupons received, reinvested at the cash rate − P0) / P0`.
  No financing of the principal. For shorts the sale proceeds earn nothing (flagged): use excess for trades.
* **Excess over financing (funded):** you borrow the dirty price at the repo rate; coupons reduce the loan.
  `excess = holding-period P&L − P0·(G(H) − 1)` exactly (tested), so "beat cash" in the unfunded basis and
  "break even" in the funded basis coincide when the cash and repo rates are the same.

**Financing / cash rate.** One assumption per position:
* *Flat repo:* money-market rate r_mm (ACT/360) for the horizon term, converted to a continuous rate
  `r = ln(1 + r_mm·H·365/360)/H`; cash-account growth `G(t) = e^{rt}`.
* *Implied short rate (+ spread s):* funding accrues along the forward short-rate path,
  `G(t) = e^{st} / DF₀(t)`.

Longs borrow the dirty price, shorts lend it (excess basis). Coupons are credited to the same cash account
(they reduce the loan and earn the rate) in both bases. No transaction costs, no haircuts, no specials.
Default: SOFR (latest); if SOFR is unavailable the default is explicitly the implied short rate.

---

## 6. Return decomposition (exact)

For each line (unit face), with `τ_i = T_i − t` for cash flows still alive at t:

    V_y(t)  = Σ c_i exp(−y₀ τ_i)                     own constant yield (y₀ reprices P₀ today)
    V_R(t)  = Σ c_i exp(−(z₀(τ_i) + s₀) τ_i)          today's unchanged curve, rolled down
    V_F(t)  = Σ c_i exp(−(F(t, τ_i) + s₀) τ_i)        forwards realised
    V_U0(t) = Σ c_i exp(−(Z_u(t, τ_i) + s₀) τ_i)      your path, spread unchanged
    V_U(t)  = Σ c_i exp(−(Z_u(t, τ_i) + s(t)) τ_i)     your path incl. spread path
    Cash(t) = G(t) · ( −P₀ + Σ_{T_i ≤ t} c_i / G(T_i) )

For TIPS lines every value above is computed on the real curves (r0, F_real, R_u) and multiplied by the
priced index `I_F(t)`; coupon cash is `c_i·I(T_i)`. Your CPI path enters only through one extra component:

    inflation = V_U·(I_u(t)/I_F(t) − 1) + Cash_u(t) − Cash_F(t)        (0 for nominal lines)

and `total = V_U·I_u/I_F + Cash_u`. With forwards realised, CPI as priced and implied financing, a TIPS earns
exactly the nominal risk-free rate (tested).

**Versus today:**

    carry  = V_y + Cash               coupon income + pull-to-par at own yield, minus financing
    roll   = V_R − V_y                moving down today's unchanged curve
    curve  = V_U0 − V_R               your path vs today's curve at the same date
    spread = V_U − V_U0
    total  = carry + roll + curve + spread + inflation

**Market-relative:**

    priced-in   = V_F + Cash = carry + roll + priced move,   priced move = V_F − V_R
    view vs forwards = total − priced-in = view (curve) + spread + inflation
    total       = priced-in + view vs forwards

"View vs forwards" is what the UI calls the market-relative component (formerly "edge"). The forwards embed
term premium, so a positive number can be compensation for bearing duration risk rather than forecasting skill.

**Splitting a curve term** `X = V_b − V_a` (curve: a = R, b = U0; edge: a = F, b = U0; priced
move: a = R, b = F) at its base a, with `Δ_i = Z_b(τ_i) − Z_a(τ_i)`:

    FO_i        = −c_i τ_i DF_a,i Δ_i                              first-order, per cash flow
    bucket_j    = Σ_i h_j(τ_i) FO_i                                 key-rate buckets; Σ_j = Σ_i FO_i
    factor_k    = β_k · Σ_i (−c_i τ_i DF_a,i) L_k(τ_i)              β = P · Δ(key tenors)
    other shape = Σ_i FO_i − Σ_k factor_k
    convexity   = ½ Σ_i c_i τ_i² DF_a,i Δ_i²
    residual    = X − Σ_i FO_i − convexity                          (third order and above)
    real / BE   nominal lines: Δ = Δr + Δb, FO_be = Σ_i FO_i·Δb_i/Δ_i, FO_real = FO − FO_be;
                TIPS lines: all first-order P&L is real-rate (their factor split projects the real-curve change)

Every identity holds to machine precision; the UI shows the worst identity error. The bucket split
is `KRD_j × Δ̄_j` where `Δ̄_j` is the KRD-weighted average move in bucket j (it equals the key-rate
move when Δ is linear between key tenors). Tests (`tests/test_attribution.py`) check all identities
over random positions (bonds, trades, credit), random paths (anchors, nodes, spreads), both
financing modes, horizons and factor bases.

**Properties (tested):**
* Path = forwards ⇒ edge ≡ 0 at every t (buckets and factors too).
* Path = forwards and implied-short-rate financing ⇒ priced-in ≡ total ≡ 0 at every t
  (the bond earns exactly the risk-free rate). With flat financing at the implied horizon term rate,
  total at H ≈ 0 (only coupon reinvestment at flat vs forward rates remains, < 0.5bp).
* Path = today ⇒ curve component ≡ 0.
* DV01-neutral trades: zero first-order P&L for small parallel moves (convexity only).
* Credit line with forwards realised: priced-in ≈ spread carry.

---

## 7. Factors

**Parametric (default).** Nelson–Siegel loadings with λ = 2.5y: `1`, `−g₁(τ)`, `g₂(τ)`, where
`g₁ = (1 − e^{−x})/x`, `g₂ = g₁ − e^{−x}`, `x = τ/λ`, Gram–Schmidt orthogonalised at the key tenors
under the projection weights, then scaled to trader units:
* Level: weighted-average shift = 1 (parallel);
* Slope: 10y − 2y = 1 (+ = steepening);
* Curvature: 2s5s10s fly `2·5y − 2y − 10y` = 1 (+ = belly cheapens).

**PCA (from history).** Eigen-decomposition of the covariance of daily zero-rate changes at the
key tenors ≥ 1y over the chosen window (1/3/5/10y). Bill tenors (1m–6m) get loadings by regressing
their daily changes on the PC scores (bills are too noisy to define the factors). The same trader
scaling is applied. Typical 5y window: 84% / 12% / 2% of variance.

**Projection.** A curve change at the key tenors is expressed as `β = P·Δ`,
`P = (BᵀWB)⁻¹BᵀW` with weights W = 0.25 (1m), 0.5 (3m), 1 elsewhere. `P·B = I`.

---

## 8. Break-evens and heatmap

* **Parallel break-even** vs today: the b with `P&L_H(z₀ + b) = 0`; vs forwards: `P&L_H(F(H,·) + b)
  = 0`. Slope break-even: the same with `b · L_slope(τ)`. Root closest to zero on ±500bp (scan +
  Brent). Credit spreads unchanged. Reported as "none" when no root exists (e.g. level-neutral).
* **Heatmap:** horizon P&L on a 41 × 41 grid of Δlevel × Δslope (factor loadings) applied to
  today's curve (or to the forwards) at H; black line = zero contour; markers at the projections of
  the forwards and of your view onto (level, slope). The markers are projections: shape outside
  level/slope is not in the map.
* **Time to cover:** the first t at which `carry(t) + roll(t) + [V_R,shocked(t) − V_R(t)] ≥ 0`, the
  shock being a parallel move of m bp in the losing direction applied at t (slope move if the
  position is near level-neutral). The cushion `(carry + roll)/|DV01(t)|` is the yield move absorbed.

### 8.1 Inverse engine — "What has to happen?"

Targets on the active basis: **break even** (P&L = 0), **beat cash** (unfunded basis: P&L = Σ face·P0·(G(H) − 1)),
**target return** X % a year on gross MV (unfunded: gross·((1+X)^H − 1); funded: gross·X·H). For each target
the engine solves, with everything else held at its context (today / forwards / your view):

| Move | Scenario at H |
|---|---|
| parallel vs today | `z0 + x` (breakevens at today's, CPI as priced) |
| parallel vs forwards | `F(H) + x` |
| room vs your view | `Z_u(H) + x` (your breakevens and CPI) |
| slope vs today | `z0 + x·L_slope` |
| share of your view k | `z0 + k·(Z_u − z0)`, breakevens `b0 + k·(B_u − b0)`, CPI `I_F·(I_u/I_F)^k`; latest realisation `H/k` (linear arrival) |
| CPI needed (TIPS books) | rates and breakevens per your view, index `(1 + π)^s` |
| breakevens vs your view (TIPS books) | `B_u(H) + x` |

Root finding: a grid scan for sign changes (±600bp, k ∈ [−4, 6], π ∈ [−10%, 25%]), then Illinois
false-position refinement to 1e-9; the root closest to the base is reported. Every root is substituted back
into the pricing engine and the residual shown (tests assert it is ~0). If no root exists the answer is
"always met" or "not reachable" — never an extrapolated number. Required levels at 2/5/10/30y are shown for
the parallel solutions. The heatmap draws the break-even, beat-cash and target contours.

---

## 9. Timing

The end-state deviation `d(H)` is reached along different profiles w(t/H) (immediate, by H/4,
linear, over the last quarter) with the same anchor. **For buy-and-hold with deterministic
financing, horizon P&L depends only on the curve at the horizon** (tested), so the profiles differ in
the P&L path, the drawdown, and the return if you exit the moment the view is realised (annualised).

---

## 10. Risk

* Key-rate covariance Σ from daily zero changes over the window (days with any |Δ| > 100bp dropped),
  annualised ×252; horizon scaling √H (random walk). Books with TIPS use the joint covariance of the
  11 nominal key zeros and the 5 breakeven knots (TIPS era only); a ±1σ parallel breakeven row is added.
* Horizon σ: `sqrt(gᵀ Σ g · H)` with g the key-rate DV01s at the horizon on your curve.
* ±1σ per factor: full revaluation at `Z_u(H) ± σ_k√H · L_k(τ)`.
* Expected return per unit of vol = E[P&L_H] / σ_H (and annualised).
* Distribution: 4,000 Gaussian draws of key-rate shocks N(0, ΣH) mapped to maturities with the
  tents, full revaluation; mean, percentiles, P(loss), 5% expected shortfall.

---

## 11. Simplifications (explicit)

1. No transaction costs, bid/offer, haircuts or repo specials.
2. Bonds are priced off the fitted (smoothed) curve plus a constant Z-spread; market rich/cheap and
   bill/coupon basis are ignored.
3. Flat financing / cash rate per position (one rate for the horizon), or the implied short-rate path.
4. Forwards (and forward breakevens) read as expectations: no term-premium or inflation-risk-premium model
   inside "priced-in".
5. Buy-and-hold: no rebalancing of hedge ratios; coupons reinvested at the financing / cash rate.
6. No business-day adjustment of cash-flow dates; settlement on the as-of date.
7. Historical risk is Gaussian and stationary over the window; the Monte-Carlo is around your path.
8. Credit: a single flat spread per line; no default, recovery or spread term structure.
9. TIPS: index ratio normalised to 1 at valuation; no deflation floor, indexation lag or CPI seasonality;
   breakevens below 5y held at the 5y level.
10. USD Treasuries only for now (§12).

## 11.1 Data integrity: nothing is substituted silently

Every analysis returns data flags shown above the workspace: the data source (live, cache, snapshot and its
date) and any refresh failure; the curve date actually used when the requested as-of date had none; tenors
not published on the date (and that the curve is held flat beyond them); coupon benchmarks the smoothed fit
misses by more than 5bp; the breakeven extrapolation below 5y; a risk window shorter than requested;
estimated FOMC dates; an on-the-run issue replaced by a generic par bond (per line). Inputs that cannot be
honoured raise an error instead: a TIPS position before 2003, an analogue whose window runs past the
available history, a maturity before the valuation date.

## 11.2 Runtime

The engine is one Python package with numpy as its only runtime dependency. Locally it runs behind FastAPI;
in the published site it runs in the visitor's browser (Pyodide, in a Web Worker) on a committed data
snapshot refreshed every business day. Both call the same entry point (`port.bridge`), so the numbers are
identical; no financial logic exists in JavaScript beyond converting between display bases (level ↔ change).

## 12. Extending to EUR

Add a curve source returning par (or zero) curves per date, e.g. the ECB AAA euro-area Svensson
curve (published parameters give zero rates directly), plus the ECB meeting calendar and €STR for
the policy builder. Everything downstream consumes a `ZeroCurve` and a history of key-tenor zeros,
so no engine change is required.
