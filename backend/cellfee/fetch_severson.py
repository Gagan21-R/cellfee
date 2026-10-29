"""Fetch the per-cycle summaries of the Severson et al. (2019) battery dataset.

Source: MIT / Stanford / Toyota Research Institute fast-charging dataset, 124 commercial
A123 APR18650M1A LFP/graphite cells (1.1 Ah), cycled to 80% capacity at 30 °C.
  Severson, K.A., Attia, P.M., Jin, N. et al. "Data-driven prediction of battery cycle life
  before capacity degradation." Nature Energy 4, 383-391 (2019). Licence CC-BY-4.0.
Mirror read: huggingface.co/datasets/bsebench-org/severson-2019-raw (bit-exact copy of data.matr.io).

Only the small `summary` struct of each cell is read, by HTTP range requests into the original
.mat (HDF5) files, so the ~8 GB of raw time series never has to be downloaded.
Cell handling follows the authors' published loading notebook:
  * batch-1 cells that never reached 80% capacity are dropped (b1c8, b1c10, b1c12, b1c13, b1c22)
  * b2c7, b2c8, b2c9, b2c15, b2c16 are continuations of b1c0..b1c4 and are appended to them
  * noisy batch-3 channels are dropped (b3c2, b3c23, b3c32, b3c37, b3c42, b3c43)
  * cycle life = first cycle below 80% of 1.1 Ah, as published (continued cells: batch-1 + batch-2 cycles)

Run:  python -m cellfee.fetch_severson     -> data/raw/severson_summary.json
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from concurrent.futures import ProcessPoolExecutor

import numpy as np

from . import config

BASE = "https://huggingface.co/datasets/bsebench-org/severson-2019-raw/resolve/main/"
FILES = {1: "2017-05-12_batchdata_updated_struct_errorcorrect.mat",
         2: "2017-06-30_batchdata_updated_struct_errorcorrect.mat",
         3: "2018-04-12_batchdata_updated_struct_errorcorrect.mat"}
FIELDS = ["cycle", "QDischarge", "QCharge", "IR", "Tavg", "Tmin", "Tmax", "chargetime"]
DROP = {1: {8, 10, 12, 13, 22}, 3: {2, 23, 32, 37, 42, 43}}
CONTINUATIONS = {7: 0, 8: 1, 9: 2, 15: 3, 16: 4}   # batch-2 channel -> batch-1 cell it continues
ADD_LIFE = {0: 662, 1: 981, 2: 1060, 3: 208, 4: 482}  # cycles run in batch 2 (authors' notebook)
OUT = config.RAW_DIR / "severson_summary.json"


class RangeFile:
    """Read-only, block-cached file object over HTTP range requests (enough for h5py)."""

    BLOCK = 1 << 20

    def __init__(self, url: str):
        with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=60) as r:
            self.url, self.size = r.url, int(r.headers["Content-Length"])
        self.pos, self.cache = 0, {}

    def _block(self, k: int) -> bytes:
        if k not in self.cache:
            a = k * self.BLOCK
            b = min(self.size, a + self.BLOCK) - 1
            for attempt in range(5):
                try:
                    req = urllib.request.Request(self.url, headers={"Range": f"bytes={a}-{b}"})
                    with urllib.request.urlopen(req, timeout=60) as r:
                        self.cache[k] = r.read()
                    break
                except Exception:
                    if attempt == 4:
                        raise
                    time.sleep(2 * (attempt + 1))
        return self.cache[k]

    def read(self, n: int = -1) -> bytes:
        if n < 0:
            n = self.size - self.pos
        out = bytearray()
        while n > 0 and self.pos < self.size:
            k, off = divmod(self.pos, self.BLOCK)
            chunk = self._block(k)[off:off + n]
            out += chunk
            self.pos += len(chunk)
            n -= len(chunk)
        return bytes(out)

    def readinto(self, b) -> int:
        d = self.read(len(b))
        b[:len(d)] = d
        return len(d)

    def seek(self, p: int, whence: int = 0) -> int:
        self.pos = p if whence == 0 else (self.pos + p if whence == 1 else self.size + p)
        return self.pos

    def tell(self) -> int:
        return self.pos

    def seekable(self) -> bool:
        return True

    def readable(self) -> bool:
        return True


def _text(h, ref) -> str:
    return "".join(chr(int(c)) for c in np.asarray(h[ref]).ravel())


def read_batch(batch: int) -> dict[str, dict]:
    import h5py

    h = h5py.File(RangeFile(BASE + FILES[batch]), "r")
    b = h["batch"]
    cells = {}
    for ch in range(b["summary"].shape[0]):
        s = h[b["summary"][ch, 0]]
        rec = {f: np.asarray(s[f]).ravel().astype(float).tolist() for f in FIELDS}
        rec["policy"] = _text(h, b["policy_readable"][ch, 0])
        rec["cycle_life_reported"] = float(np.asarray(h[b["cycle_life"][ch, 0]]).ravel()[0])
        cells[f"b{batch}c{ch}"] = rec
        print(f"  b{batch}c{ch}: {len(rec['cycle'])} cycles  {rec['policy']}", flush=True)
    return cells


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    t0 = time.time()
    with ProcessPoolExecutor(3) as ex:
        batches = dict(zip(FILES, ex.map(read_batch, FILES)))
    cells = {}
    for batch, recs in batches.items():
        for cid, rec in recs.items():
            ch = int(cid.split("c")[1])
            if ch in DROP.get(batch, set()) or (batch == 2 and ch in CONTINUATIONS):
                continue
            cells[cid] = rec
    for ch2, ch1 in CONTINUATIONS.items():
        tail, head = batches[2][f"b2c{ch2}"], cells[f"b1c{ch1}"]
        offset = max(head["cycle"]) + 1
        for f in FIELDS:
            head[f] += [v + offset for v in tail["cycle"]] if f == "cycle" else tail[f]
        head["continued_from"] = f"b2c{ch2}"
        head["cycle_life_reported"] += ADD_LIFE[ch1]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"source": "Severson et al., Nature Energy 4, 383-391 (2019); "
                                         "data.matr.io via huggingface.co/datasets/bsebench-org/severson-2019-raw",
                               "licence": "CC-BY-4.0", "nominal_capacity_ah": 1.1, "cells": cells}))
    n = sum(len(c["cycle"]) for c in cells.values())
    print(f"wrote {OUT}: {len(cells)} cells, {n} cycle summaries in {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
