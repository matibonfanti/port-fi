# Guardrails for changing PORT·FI

Methodology is documented in `docs/METHODOLOGY.md`. Change it deliberately, update that document in the same
change, and never alter financial methodology just to make a test pass.

## Financial rules
1. **Full repricing is the valuation.** Duration, convexity and DV01s are explanatory; scenario P&L always comes
   from discounting cash flows.
2. **Every attribution reconciles exactly** (to ~1e-9 of gross MV): carry + roll + curve + spread + inflation =
   total; priced-in + view vs forwards = total; buckets / factors + other + convexity + residual = curve term;
   real + breakeven = first order. Convexity is part of the split of the full repricing, never an add-on.
3. **Bonds age.** Remaining maturity at t is T − t; coupons at or before t are cash, not value.
4. **Par yields are not zero rates.** Curves are fitted (bills BEY, coupons par) into cc zero rates before discounting.
5. **Forwards are a pricing reference, not a forecast.** "Priced-in" reads them as expectations by convention;
   say so wherever it matters (term premium, inflation-risk premium).
6. **A terminal curve does not define a path.** Paths are explicit (nodes, policy, analogue, timing profiles).
7. **Never substitute missing data silently.** Fall back only with a data flag (`service.flag`), or raise.
8. **Inverse answers are roots of the full engine**, substituted back with the residual reported; when none
   exists, say "always met" / "not reachable".

## Engineering rules
* Financial logic lives only in Python (`port/`). The UI converts between display bases (level ↔ change) and
  formats; it does not price.
* The runtime depends on **numpy only** (it also runs under Pyodide). scipy/pandas/QuantLib are test-only;
  `tests/test_runtime.py` enforces this.
* Units: internal rates are decimals (cc); `BP = 1e-4`; node deviations are stored in bp; the API sends
  levels in % and P&L in $. Name conversions explicitly.
* Bump `FIT_VERSION` in `port/curves/history.py` when curve fitting changes (invalidates the fitted history),
  then rebuild the snapshot with `scripts/update_data.py`.
* Tests: `uv run pytest` must pass before any commit; add an identity or cross-check test with new analytics.
