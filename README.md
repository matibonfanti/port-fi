# PORT·FI — fixed-income scenario & return attribution

**Position + time + view → return.** State a view on the US Treasury curve (and on inflation): drag points on
the curve, set a policy-rate path, or use presets and historical analogues. See what the position earns over
time, **when** and **why**: carry, roll-down, curve change by key rate or factor, real yields vs breakevens,
convexity, and the split into *priced-in + view vs forwards*. Then reverse it: **what has to happen** to break
even, beat cash or hit a target return. Everything reconciles exactly and is solved on full cash-flow repricing.

Data: treasury.gov nominal and TIPS par curves (1990 / 2003 →), NY Fed SOFR/EFFR, TreasuryDirect on-the-runs.

## Run locally

```bash
uv sync                      # install (Python 3.12+, uv)
uv run pytest                # 100+ tests: identities, properties, QuantLib cross-checks, inverse roots, runtime guard
uv run port                  # http://127.0.0.1:8765  (local server; refreshes recent data live)
```

## Static build (the published version)

The engine is numpy-only, so the site runs **the same Python in the visitor's browser** (Pyodide in a Web
Worker) on a committed data snapshot. No server, nothing to keep running, each visitor's saved views stay in
their own browser.

```bash
uv run python scripts/update_data.py   # refresh data/snapshot (the CI does this every business day)
python3 scripts/build_static.py        # → dist/  (stdlib only)
```
Test it locally at http://127.0.0.1:8765/dist/ while `uv run port` is running.

### Deploy

* **Vercel:** import the GitHub repo; `vercel.json` sets the build (`python3 scripts/build_static.py`) and
  output (`dist`). Every push, including the daily data commit, redeploys.
* **GitHub Pages:** enable Pages → "GitHub Actions"; `.github/workflows/pages.yml` tests, builds and publishes.
* **Data:** `.github/workflows/data.yml` refreshes the snapshot on weekdays at 22:30 UTC and commits it.

### Embed in a website

```html
<iframe src="https://YOUR-DEPLOYMENT/" style="width:100%;height:1600px;border:0" title="PORT·FI"></iframe>
```
or link to it. First visit downloads ~10 MB (Python runtime + numpy, then cached by the browser).

## Layout

* `port/` — engine: `curves/` (fits, breakevens, factors), `paths/` (views, policy, inflation), `instruments/`,
  `analytics/` (attribution, inverse, break-evens, risk, timing, summary), `bridge.py` (the single JSON entry
  point), `api/server.py` (local FastAPI)
* `web/` — UI (Preact + htm + D3, vendored, no build step); `web/js/worker.js` runs the engine in-browser
* `data/snapshot/` — committed market data and fitted histories
* `docs/METHODOLOGY.md` — every formula, convention, simplification and data rule (also in the app)
* `docs/DESIGN.md` — architecture · `AGENTS.md` — guardrails for anyone changing the engine
