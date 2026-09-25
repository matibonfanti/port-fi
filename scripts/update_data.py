"""Rebuild the committed market-data snapshot (data/snapshot/).

    uv run python scripts/update_data.py

Fetches US Treasury nominal and real par curves (treasury.gov), SOFR/EFFR (NY Fed) and on-the-run
issues (TreasuryDirect); fits the nominal zero and breakeven histories; writes CSV/JSON files that the
browser build loads. Run daily (see .github/workflows/data.yml).
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from port.config import SNAPSHOT_DIR  # noqa: E402
from port.curves import history  # noqa: E402
from port.data import market, treasury  # noqa: E402


def main():
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    nom = treasury.history("nominal")
    real = treasury.history("real")
    for kind, p in (("nominal", nom), ("real", real)):
        st = treasury.STATUS.get(kind, {})
        if st.get("errors"):
            print(f"WARNING {kind}: fetch errors {st['errors']}", file=sys.stderr)
    nom.to_csv(SNAPSHOT_DIR / "ust_par.csv", digits=6)
    real.to_csv(SNAPSHOT_DIR / "ust_real.csv", digits=6)
    history._fitted.cache_clear()
    history.write_snapshot_fits()
    latest = nom.last
    refs = {}
    try:
        refs["rates"] = market.fetch_reference_rates()
    except Exception as e:
        print(f"WARNING rates: {e}", file=sys.stderr)
    try:
        refs.update(market.fetch_securities(latest))
    except Exception as e:
        print(f"WARNING securities: {e}", file=sys.stderr)
    old = market.snapshot_market()
    out = {**old, **refs, "built": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
           "nominal_last": nom.last.isoformat(), "real_last": real.last.isoformat()}
    (SNAPSHOT_DIR / "market.json").write_text(json.dumps(out, indent=1))
    print(f"snapshot: nominal {nom.first}..{nom.last} ({len(nom)}), real {real.first}..{real.last} ({len(real)})")


if __name__ == "__main__":
    main()
