"""A minimal dated table (dates × columns) on numpy — replaces pandas in the runtime so the engine
also runs in the browser (Pyodide) with numpy only."""
from __future__ import annotations

import csv
import datetime as dt
import io
from dataclasses import dataclass
from pathlib import Path

import numpy as np


def to_day(d) -> np.datetime64:
    if isinstance(d, np.datetime64):
        return d.astype("datetime64[D]")
    if isinstance(d, (dt.date, dt.datetime)):
        return np.datetime64(d.isoformat()[:10], "D")
    return np.datetime64(str(d)[:10], "D")


def to_date(d: np.datetime64) -> dt.date:
    return dt.date.fromisoformat(str(d.astype("datetime64[D]")))


@dataclass
class Panel:
    dates: np.ndarray        # datetime64[D], strictly increasing
    cols: list               # column labels
    values: np.ndarray       # (N, C) float, NaN = missing

    def __len__(self):
        return len(self.dates)

    @property
    def first(self) -> dt.date:
        return to_date(self.dates[0])

    @property
    def last(self) -> dt.date:
        return to_date(self.dates[-1])

    def upto(self, d) -> "Panel":
        k = np.searchsorted(self.dates, to_day(d), side="right")
        return Panel(self.dates[:k], self.cols, self.values[:k])

    def between(self, a, b) -> "Panel":
        i = np.searchsorted(self.dates, to_day(a), side="right")
        j = np.searchsorted(self.dates, to_day(b), side="right")
        return Panel(self.dates[i:j], self.cols, self.values[i:j])

    def row_on_or_before(self, d):
        """(date, row) of the last observation on or before d, or (None, None)."""
        k = np.searchsorted(self.dates, to_day(d), side="right") - 1
        if k < 0:
            return None, None
        return to_date(self.dates[k]), self.values[k]

    def col(self, c) -> np.ndarray:
        return self.values[:, self.cols.index(c)]

    @staticmethod
    def concat(parts: list["Panel"], cols: list) -> "Panel":
        """Union of rows (later parts win on duplicate dates), columns aligned to `cols`."""
        rows = {}
        for p in parts:
            idx = [p.cols.index(c) if c in p.cols else None for c in cols]
            for d, v in zip(p.dates, p.values):
                rows[d] = np.array([v[i] if i is not None else np.nan for i in idx], float)
        ds = np.array(sorted(rows), dtype="datetime64[D]")
        vals = np.array([rows[d] for d in ds]) if len(ds) else np.zeros((0, len(cols)))
        return Panel(ds, list(cols), vals)

    # ------------------------------------------------------------------ csv io
    def to_csv(self, path: Path, digits: int = 7, labels=None):
        labels = labels or [str(c) for c in self.cols]
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["date"] + labels)
        for d, v in zip(self.dates, self.values):
            w.writerow([str(d)] + ["" if np.isnan(x) else f"{x:.{digits}g}" for x in v])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(buf.getvalue())

    @staticmethod
    def read_csv(path: Path, col_parser=float) -> "Panel":
        rows = list(csv.reader(io.StringIO(Path(path).read_text())))
        cols = [col_parser(c) for c in rows[0][1:]]
        ds = np.array([r[0] for r in rows[1:]], dtype="datetime64[D]")
        vals = np.array([[float(x) if x != "" else np.nan for x in r[1:]] for r in rows[1:]], float)
        if vals.size == 0:
            vals = np.zeros((0, len(cols)))
        return Panel(ds, cols, vals)
