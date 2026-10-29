"""Read a user's battery test results (CSV or JSON) into screening features.

Two layouts are accepted, with flexible column names (case, spaces and units in brackets are ignored):

1. Cycle log, one row per cycle (what a battery cycler exports), optionally several batteries:
       battery_id, cycle, discharge_capacity_ah, internal_resistance_ohm, temperature_max_c, charge_time_min
   The last <= 100 cycles are turned into features exactly as for the training data (data.py).
2. Screening summary, one row per battery, with the features already worked out:
       battery_id, soh (or capacity_ah), fade_100, ir_mohm, ir_rise_100, temp_max_c, charge_time_min, cycles

Units are recognised from the values: capacity > 50 is read as mAh, resistance > 1 as milliohm,
charge time > 300 as seconds. An optional rated_capacity_ah column sets the battery's rating (default 1.1 Ah).
"""

from __future__ import annotations

import csv
import io
import json
import re

import numpy as np

from . import config
from . import report_extract
from .data import FEATURES, MIN_HISTORY, features_from_history

MAX_BATTERIES = 50
ALIASES = {
    "battery_id": ["battery_id", "battery", "cell", "cell_id", "id", "serial", "barcode", "name"],
    "cycle": ["cycle", "cycle_index", "cycle_number", "cycle_no", "cyc"],
    "capacity": ["discharge_capacity", "discharge_capacity_ah", "qdischarge", "qd", "capacity", "capacity_ah",
                 "dchg_capacity"],
    "ir": ["internal_resistance", "internal_resistance_ohm", "internal_resistance_mohm", "ir", "ir_ohm", "ir_mohm",
           "resistance", "dcir"],
    "tmax": ["temperature_max", "temperature_max_c", "temp_max", "temp_max_c", "tmax", "max_temperature",
             "peak_temperature", "temperature", "temp"],
    "charge_time": ["charge_time", "charge_time_min", "chargetime", "charging_time", "charge_duration"],
    "rated": ["rated_capacity_ah", "rated_capacity", "nominal_capacity", "nominal_capacity_ah"],
    "chemistry": ["chemistry", "cell_chemistry", "cathode"],
    "soh": ["soh", "state_of_health", "health"],
    "capacity_now": ["capacity_now_ah"],
    "fade_100": ["fade_100", "fade_per_100_cycles", "capacity_fade_per_100"],
    "ir_mohm": ["ir_now_mohm"],
    "ir_rise_100": ["ir_rise_100", "resistance_rise_per_100_cycles"],
    "temp_max_c": ["temp_max_c_now"],
    "charge_time_min": ["charge_time_min_now"],
    "cycles": ["cycles", "cycle_count", "cycles_done", "total_cycles"],
}


def _norm(name: str) -> str:
    name = re.sub(r"\(.*?\)|\[.*?\]", "", str(name)).strip().lower()
    return re.sub(r"[^a-z0-9]+", "_", name).strip("_")


def _rows(filename: str, content: str) -> list[dict]:
    text = content.lstrip("﻿")
    if filename.lower().endswith(".json") or text.lstrip()[:1] in "[{":
        data = json.loads(text)
        if isinstance(data, dict):
            data = data.get("batteries") or data.get("cycles") or data.get("rows") or [data]
        out = []
        for item in data:   # nested {"battery_id": .., "cycles": [..]} is flattened
            if isinstance(item, dict) and isinstance(item.get("screening_inputs"), dict):
                # a CELLFEE report downloaded earlier (passport / assessment / screening JSON): re-screen its inputs
                out.append({"battery_id": item.get("battery_id") or "battery-1", **item["screening_inputs"]})
            elif isinstance(item, dict) and isinstance(item.get("cycles"), list):
                out += [{"battery_id": item.get("battery_id", item.get("id")), **c} for c in item["cycles"]]
            elif isinstance(item, dict):
                out.append(item)
        return out
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    return list(csv.DictReader(io.StringIO(text), dialect=dialect))


def _column_map(keys: list[str]) -> dict[str, str]:
    normed = {_norm(k): k for k in keys}
    found = {}
    for target, names in ALIASES.items():
        for n in names:
            if n in normed and normed[n] not in found.values():
                found[target] = normed[n]
                break
    return found


def _num(v) -> float:
    try:
        return float(str(v).strip().replace(",", "."))
    except (TypeError, ValueError):
        return float("nan")


def parse(filename: str, content: str, max_gaps: int = 2) -> dict:
    """-> {"layout", "batteries": [{"battery_id", "features" | None, "notes", "error"}], "warnings"}"""
    rows = _rows(filename, content)
    if not rows:
        raise ValueError("the file has no rows")
    cmap = _column_map(list(rows[0].keys()))
    warnings: list[str] = []
    get = lambda r, k: _num(r.get(cmap[k])) if k in cmap else float("nan")
    bid = lambda r, i: str(r.get(cmap["battery_id"], "")).strip() or "battery-1" if "battery_id" in cmap else "battery-1"

    groups: dict[str, list[dict]] = {}
    for i, r in enumerate(rows):
        groups.setdefault(bid(r, i), []).append(r)
    if len(groups) > MAX_BATTERIES:
        warnings.append(f"only the first {MAX_BATTERIES} batteries were screened")
        groups = dict(list(groups.items())[:MAX_BATTERIES])

    is_log = all(k in cmap for k in ("cycle", "capacity")) and len(rows) > len(groups)
    batteries = []
    for name, rs in groups.items():
        rated = get(rs[0], "rated")
        rated = rated if np.isfinite(rated) and 0.05 < rated < 1000 else config.NOMINAL_CAPACITY_AH
        notes = []
        chem = str(rs[0].get(cmap["chemistry"], "LFP")).strip().upper() if "chemistry" in cmap else "LFP"
        extra = {"chemistry": chem or "LFP", "rated_ah": rated}
        if abs(rated - config.NOMINAL_CAPACITY_AH) > 1e-6:
            notes.append(f"rated capacity {rated:g} Ah taken from the file")
        if is_log:
            cyc = np.array([get(r, "cycle") for r in rs])
            cap = np.array([get(r, "capacity") for r in rs])
            ir = np.array([get(r, "ir") for r in rs])
            tmx = np.array([get(r, "tmax") for r in rs])
            ct = np.array([get(r, "charge_time") for r in rs])
            if np.nanmedian(cap) > 50:
                cap = cap / 1000; notes.append("capacity read as mAh")
            if np.nanmedian(ir) > 1:
                ir = ir / 1000; notes.append("resistance read as milliohm")
            if np.nanmedian(ct) > 300:
                ct = ct / 60; notes.append("charge time read as seconds")
            missing = [lbl for k, lbl in (("ir", "internal resistance"), ("tmax", "peak temperature"),
                                          ("charge_time", "charge time")) if k not in cmap]
            if missing:
                batteries.append({"battery_id": name, "features": None, "notes": notes,
                                  "error": "missing column(s): " + ", ".join(missing)})
                continue
            f = features_from_history(cyc, cap, ir, tmx, ct, nominal_ah=rated)
            if f is None:
                batteries.append({"battery_id": name, "features": None, "notes": notes,
                                  "error": f"needs at least {MIN_HISTORY} valid cycles of history "
                                           f"(found {int(np.isfinite(cap).sum())} rows)"})
                continue
            notes.append(f"features from the last {f.pop('history_cycles')} valid cycles of {len(rs)} rows")
            batteries.append({"battery_id": name, "features": f, "notes": notes, "error": None, **extra})
        else:
            r = rs[-1]
            f = {}
            soh = get(r, "soh")
            if not np.isfinite(soh):
                capn = get(r, "capacity_now") if "capacity_now" in cmap else get(r, "capacity")
                if capn > 50:
                    capn /= 1000
                soh = capn / rated
            elif soh > 1.5:
                soh /= 100
            f["soh"] = soh
            for k in ("fade_100", "ir_mohm", "ir_rise_100", "temp_max_c", "charge_time_min", "cycles"):
                v = get(r, k)
                if not np.isfinite(v) and k == "ir_mohm":
                    v = get(r, "ir") * (1 if get(r, "ir") > 1 else 1000)
                if not np.isfinite(v) and k == "temp_max_c":
                    v = get(r, "tmax")
                if not np.isfinite(v) and k == "charge_time_min":
                    v = get(r, "charge_time")
                f[k] = v
            gaps = [k for k in FEATURES if not np.isfinite(f.get(k, float("nan")))]
            if not np.isfinite(f["soh"]) or len(gaps) > max_gaps:
                batteries.append({"battery_id": name, "features": None, "notes": notes,
                                  "error": "not enough recognised columns (need health or capacity, plus most of: "
                                           + ", ".join(FEATURES[1:]) + ")"})
                continue
            batteries.append({"battery_id": name, "features": f, "notes": notes, "error": None, "gaps": gaps, **extra})
    if not any(b["features"] for b in batteries):
        cols = ", ".join(sorted(cmap)) or "none"
        warnings.append(f"no battery could be screened; recognised columns: {cols}")
    return {"layout": "cycle log" if is_log else "screening summary", "columns": cmap,
            "batteries": batteries, "warnings": warnings}


FIELD_LABELS = {"soh_pct": "health", "capacity_ah": "capacity", "ir_mohm": "internal resistance", "cycles": "cycle count",
                "temp_max_c": "peak temperature", "charge_time_min": "charge time", "chemistry": "chemistry",
                "serial": "battery ID", "report_id": "report ID"}


def parse_document(filename: str, data: bytes) -> dict:
    """Any file (PDF, image, Excel, Word, CSV, JSON, text) -> the same result shape as parse()."""
    doc = report_extract.read_any(filename, data)
    kind = doc["kind"]
    info = {"kind": kind, "notes": list(doc["notes"]), "fields_read": {}}
    if kind in ("csv", "json", "text"):
        out = parse(filename if kind != "json" else re.sub(r"\.[^.]*$", "", filename) + ".json", doc["text"])
        return {**out, "document": info}
    if not doc["readable"] and not doc["table_csv"]:
        raise ValueError("; ".join(doc["notes"]) or "the file could not be read")
    if doc["table_csv"]:                                       # a table in the PDF / Excel / Word / image
        try:
            out = parse(f"{filename}.csv", doc["table_csv"])
            if any(b["features"] for b in out["batteries"]):
                info["notes"].append(f"read the table in this {kind.upper()} file")
                return {**out, "document": info}
        except Exception:
            pass
    f = report_extract.extract_fields(doc["text"])           # otherwise: individual values in the text
    info["fields_read"] = {FIELD_LABELS.get(k, k): v for k, v in f.items() if k in FIELD_LABELS}
    if "soh_pct" not in f and "capacity_ah" not in f:
        raise ValueError(f"no battery health or capacity could be found in this {kind.upper()} file"
                         + (f" ({'; '.join(doc['notes'])})" if doc["notes"] else "")
                         + ". Upload test data, or use 'Type one battery's numbers'.")
    row = {"battery_id": (f.get("serial") or f.get("report_id") or {"value": re.sub(r"\.[^.]*$", "", filename)})["value"]}
    if "soh_pct" in f:
        row["soh"] = f["soh_pct"]["value"]
    else:
        row["capacity_now_ah"] = f["capacity_ah"]["value"]
    for k in ("ir_mohm", "cycles", "temp_max_c", "charge_time_min"):
        if k in f:
            row[k] = f[k]["value"]
    if "chemistry" in f:
        row["chemistry"] = f["chemistry"]["value"]
    out = parse(f"{filename}.json", json.dumps([row]), max_gaps=6)
    found = ", ".join(info["fields_read"]) or "none"
    for b in out["batteries"]:
        b["notes"] = [f"values read from the {kind.upper()} text ({found}) — please check them"] + b["notes"]
    info["notes"].append(f"no table found; read individual values: {found}")
    return {**out, "document": info}
