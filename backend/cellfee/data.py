"""Severson et al. (2019) LFP cycling data -> second-life screening snapshots.

Screening question (binary, what a second-life buyer needs to know):
    "Does this used battery still have at least LONG_LIFE_CYCLES full cycles left
     before it falls to 80% of its rated capacity?"   label 1 = yes (fit for second life)

A snapshot is one battery at one moment of its life, described only by what a screener sees in
its recent test log (the last <= HISTORY cycles), never by its future:
    soh              discharge capacity now / 1.1 Ah rating (median of last 5 cycles)
    fade_100         capacity lost per 100 cycles, as a fraction of rating (slope over history)
    ir_mohm          internal resistance now, milliohm (median of last 5 cycles)
    ir_rise_100      internal-resistance rise per 100 cycles, milliohm (slope over history)
    temp_max_c       peak cell temperature per cycle, °C (median of last 5 cycles)
    charge_time_min  charge time per cycle, minutes (median of last 5 cycles)
    cycles           cycles done so far

The same feature code runs on uploaded test logs (api.py), so training and live use match.

Validation rules (applied per cycle before features are computed):
    0.5 < capacity < 1.3 Ah,  5 < IR < 50 mΩ,  20 < Tmax < 60 °C,  5 < charge time < 120 min
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass

import numpy as np

from . import config

RAW_JSON = config.RAW_DIR / "severson_summary.json"

FEATURES = ["soh", "fade_100", "ir_mohm", "ir_rise_100", "temp_max_c", "charge_time_min", "cycles"]
FEATURE_LABELS = {
    "soh": "Health now (capacity / rating)",
    "fade_100": "Capacity lost per 100 cycles",
    "ir_mohm": "Internal resistance (mΩ)",
    "ir_rise_100": "Resistance rise per 100 cycles (mΩ)",
    "temp_max_c": "Peak temperature per cycle (°C)",
    "charge_time_min": "Charge time per cycle (min)",
    "cycles": "Cycles done so far",
}
HISTORY = 100          # cycles of recent history a screener looks at
MIN_HISTORY = 20       # fewer valid cycles than this -> not enough to screen
STEP = 10              # one training snapshot every STEP cycles
FIRST_SNAPSHOT = 100   # first snapshot needs a full history window


def valid_mask(q, ir, tmax, ct, nominal_ah: float = config.NOMINAL_CAPACITY_AH) -> np.ndarray:
    q, ir, tmax, ct = (np.asarray(v, float) for v in (q, ir, tmax, ct))
    q = q * (config.NOMINAL_CAPACITY_AH / nominal_ah)   # validity window is defined for a 1.1 Ah cell
    return ((q > 0.5) & (q < 1.3) & (ir > 0.005) & (ir < 0.05) & (tmax > 20) & (tmax < 60)
            & (ct > 5) & (ct < 120))


def features_from_history(cycle, q, ir, tmax, ct, nominal_ah: float = config.NOMINAL_CAPACITY_AH) -> dict | None:
    """Screening features from a test log (arrays per cycle). None if too little valid history."""
    cycle, q, ir, tmax, ct = (np.asarray(v, float) for v in (cycle, q, ir, tmax, ct))
    ok = valid_mask(q, ir, tmax, ct, nominal_ah)
    cycle, q, ir, tmax, ct = cycle[ok], q[ok], ir[ok], tmax[ok], ct[ok]
    if len(cycle) < MIN_HISTORY:
        return None
    order = np.argsort(cycle)
    cycle, q, ir, tmax, ct = cycle[order], q[order], ir[order], tmax[order], ct[order]
    w = cycle >= cycle[-1] - HISTORY
    if w.sum() < MIN_HISTORY:
        w = np.zeros(len(cycle), bool)
        w[-MIN_HISTORY:] = True
    last = slice(-5, None)
    fade = -np.polyfit(cycle[w], q[w], 1)[0] * 100 / nominal_ah
    rise = np.polyfit(cycle[w], ir[w], 1)[0] * 100 * 1000
    return {
        "soh": float(np.median(q[last]) / nominal_ah),
        "fade_100": float(fade),
        "ir_mohm": float(np.median(ir[last]) * 1000),
        "ir_rise_100": float(rise),
        "temp_max_c": float(np.median(tmax[last])),
        "charge_time_min": float(np.median(ct[last])),
        "cycles": float(cycle[-1]),
        "history_cycles": int(w.sum()),
    }


@dataclass
class Dataset:
    X: np.ndarray            # (N, F) features
    y: np.ndarray            # (N,) 1 = fit for second life (>= LONG_LIFE_CYCLES left)
    rul: np.ndarray          # (N,) true cycles left before 80% capacity
    cell: np.ndarray         # (N,) cell id
    cycle: np.ndarray        # (N,) cycle of the snapshot
    policy: np.ndarray       # (N,) fast-charge protocol of the cell
    life: np.ndarray         # (N,) total cycle life of the cell
    excluded: dict

    def records(self) -> list[dict]:
        return [{"cell": str(c), "cycle": int(k), "label_fit": int(t), "cycles_left": int(r), "policy": str(p),
                 **{f: round(float(v), 5) for f, v in zip(FEATURES, row)}}
                for row, t, r, c, k, p in zip(self.X, self.y, self.rul, self.cell, self.cycle, self.policy)]


def load_cells() -> dict:
    return json.loads(RAW_JSON.read_text())["cells"]


def load_snapshots() -> Dataset:
    cells = load_cells()
    X, y, rul, cid, cyc, pol, life_ = [], [], [], [], [], [], []
    excluded = {"invalid_cycle_records": 0, "snapshots_without_enough_history": 0}
    for name in sorted(cells):
        c = cells[name]
        cycle, q, ir, tmax, ct = (np.asarray(c[k], float) for k in ("cycle", "QDischarge", "IR", "Tmax", "chargetime"))
        excluded["invalid_cycle_records"] += int((~valid_mask(q, ir, tmax, ct)).sum())
        life = float(c["cycle_life_reported"])
        for at in range(FIRST_SNAPSHOT, int(life), STEP):
            upto = cycle <= at
            f = features_from_history(cycle[upto], q[upto], ir[upto], tmax[upto], ct[upto])
            if f is None:
                excluded["snapshots_without_enough_history"] += 1
                continue
            left = life - f["cycles"]
            X.append([f[k] for k in FEATURES]); rul.append(left); y.append(int(left >= config.LONG_LIFE_CYCLES))
            cid.append(name); cyc.append(int(f["cycles"])); pol.append(c["policy"]); life_.append(life)
    return Dataset(np.array(X, float), np.array(y, int), np.array(rul, float), np.array(cid), np.array(cyc),
                   np.array(pol), np.array(life_), excluded)


def write_processed(ds: Dataset) -> None:
    config.PROCESSED_CSV.parent.mkdir(parents=True, exist_ok=True)
    recs = ds.records()
    with config.PROCESSED_CSV.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(recs[0]))
        w.writeheader()
        w.writerows(recs)


def cycles_to_80(X: np.ndarray) -> np.ndarray:
    """Engineered input for AQSVC: cycles until health reaches 80% if the recent fade rate continues,
    (soh - 0.80) / fade_100 * 100. Computed from two of the 7 screening features, so it needs no extra measurement."""
    soh, fade = X[:, FEATURES.index("soh")], X[:, FEATURES.index("fade_100")]
    return np.clip((soh - config.FIRST_LIFE_EOL_SOH) / np.maximum(fade, 1e-3) * 100, -200, 3000)


def quantum_inputs(X: np.ndarray, n: int) -> np.ndarray:
    """AQSVC inputs: the 7 screening features, plus cycles_to_80 when n == 8."""
    return np.column_stack([X, cycles_to_80(X)]) if n == 8 else X


class RankScaler:
    """Rank (quantile) encoding to qubit angles in [0, pi], fitted on training data only: each feature's training
    distribution is spread evenly over the rotation range, so heavy-tailed features use the whole Bloch circle."""

    def fit(self, X: np.ndarray, n_quantiles: int = 200) -> "RankScaler":
        self.q = np.percentile(X, np.linspace(0, 100, n_quantiles), axis=0).T   # (features, quantiles)
        return self

    def transform(self, X: np.ndarray) -> np.ndarray:
        ref = np.linspace(0, 1, self.q.shape[1])
        out = np.empty_like(X, dtype=float)
        for j, qs in enumerate(self.q):
            qs, idx = np.unique(qs, return_index=True)          # ties (repeated quantiles) collapse to one point
            out[:, j] = np.interp(X[:, j], qs, ref[idx]) if len(qs) > 1 else 0.5
        return out * np.pi


class AngleScaler:
    """Robust min-max scaling to qubit rotation angles in [0, pi], fitted on training data only."""

    def fit(self, X: np.ndarray) -> "AngleScaler":
        self.lo = np.percentile(X, 2, axis=0)
        self.hi = np.percentile(X, 98, axis=0)
        self.hi = np.where(self.hi - self.lo < 1e-9, self.lo + 1.0, self.hi)
        return self

    def transform(self, X: np.ndarray) -> np.ndarray:
        return np.clip((X - self.lo) / (self.hi - self.lo), 0.0, 1.0) * np.pi
