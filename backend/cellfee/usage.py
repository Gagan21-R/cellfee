"""Usage baselines, risk factor, stop period and per-application confidence.

Everything here is computed from the stored test data and documented models; the limits themselves are policy
constants in registry/applications.json and registry/baselines.json ("Configured baseline. Adjust to your safety
standard."). Decision support only, never a safety certification.

Risk factor (0-1, Low / Elevated / High)
    risk = Σ w_k · c_k over five components, each scaled to 0-1:
      health_margin   = clip((good_soh − soh) / (good_soh − floor_soh))          closer to 80% health → higher
      fade_rate       = percentile of "capacity lost per 100 cycles" among the 8,753 training snapshots
      resistance_rise = percentile of "resistance rise per 100 cycles" among the training snapshots
      temperature     = clip((peak °C − cool_c) / (hot_c − cool_c))
      model_doubt     = 1 − |2p − 1| with p = mean(XGBoost, AQSVC); 1 when the two models disagree
    Levels: Low < elevated_from ≤ Elevated < high_from ≤ High. The level caps the safety tier a battery may serve.
    Validation: the share of training snapshots in each level that really reached 80% health within 100 cycles.

Stop period (cycles, P10 / P50 / P90, also in months for each application's duty)
    target = cycles until the cell's smoothed health first falls below the application floor (0 if already below),
    learned by XGBoost quantile regression (one model per distinct floor) on the 7 screening features, grouped 5-fold
    CV by cell for out-of-fold predictions; capped at the application's max_cycles_in_service. The P10 ("stop by")
    drives the state: Stop use (already below floor or P10 = 0), Approaching limit (P10 ≤ margin), Safe.
    Validation: out-of-fold coverage of the P10–P90 band.

Confidence that a battery can serve an application (0-100 %)
    = P(health stays ≥ the application's floor for ≥ its min_remaining_cycles), from an XGBoost classifier per
    distinct (floor, cycles) requirement (XGBoost is the stronger model in the stored comparison), out-of-fold for the
    fleet. Measured requirements are hard gates, not probabilities: chemistry, health ≥ floor, capacity, internal
    resistance, peak temperature, and safety tier ≤ the risk level's tier limit. If a gate fails there is no %.
    Pack confidence = the MINIMUM over its members (conservative); the pack's stop period is its weakest member's,
    and that member is named as the limiter.
"""

from __future__ import annotations

import json
import time
from functools import lru_cache
from pathlib import Path

import numpy as np
from sklearn.model_selection import GroupKFold

from . import config
from .data import FEATURES, load_cells, valid_mask
from .sponsors import log_evidence

REGISTRY = Path(__file__).parent / "registry"
MODEL_DIR = config.ARTIFACTS / "usage"
META = config.ARTIFACTS / "usage_meta.json"
QUANTILES = [0.1, 0.5, 0.9]
XGB = dict(n_estimators=250, max_depth=4, learning_rate=0.05, subsample=0.8, colsample_bytree=0.8,
           random_state=config.SEED, n_jobs=8)


@lru_cache(maxsize=1)
def registry() -> dict:
    return json.loads((REGISTRY / "applications.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def baselines() -> dict:
    return json.loads((REGISTRY / "baselines.json").read_text(encoding="utf-8"))


def applications() -> list[dict]:
    return registry()["applications"]


def floors() -> list[float]:
    return sorted({a["min_soh"] for a in applications()})


def req_key(floor: float, cycles: int) -> str:
    return f"f{int(round(floor * 100))}_c{int(cycles)}"


def requirements() -> list[tuple[float, int]]:
    return sorted({(a["min_soh"], a["min_remaining_cycles"]) for a in applications()})


# ----------------------------------------------------------------------------- targets
def cycles_to_floor(ds) -> dict[float, np.ndarray]:
    """For every snapshot: cycles until the cell's smoothed health first drops below each floor (0 if below now)."""
    cells = load_cells()
    cross: dict[str, dict[float, float]] = {}
    for name, c in cells.items():
        cyc, q = np.asarray(c["cycle"], float), np.asarray(c["QDischarge"], float)
        ok = valid_mask(q, c["IR"], c["Tmax"], c["chargetime"])
        cyc, q = cyc[ok], q[ok]
        order = np.argsort(cyc)
        cyc, q = cyc[order], q[order]
        soh = np.array([np.median(q[max(0, i - 4):i + 1]) for i in range(len(q))]) / config.NOMINAL_CAPACITY_AH
        life = float(c["cycle_life_reported"])
        cross[name] = {}
        for f in floors():
            if f <= config.FIRST_LIFE_EOL_SOH + 1e-9:
                cross[name][f] = life                       # the published end of life (80%)
            else:
                below = np.where(soh < f)[0]
                cross[name][f] = float(cyc[below[0]]) if len(below) else life
    return {f: np.array([max(0.0, cross[str(cl)][f] - cy) for cl, cy in zip(ds.cell, ds.X[:, FEATURES.index("cycles")])])
            for f in floors()}


# ----------------------------------------------------------------------------- training
def _cls():
    import xgboost as xgb
    return xgb.XGBClassifier(**XGB, eval_metric="logloss")


def _qreg():
    import xgboost as xgb
    return xgb.XGBRegressor(**XGB, objective="reg:quantileerror", quantile_alpha=np.array(QUANTILES))


def _fit_cls(X, y):
    if y.min() == y.max():                                   # constant label in this fold
        return float(y[0])
    return _cls().fit(X, y)


def _pred_cls(m, X):
    return np.full(len(X), m) if isinstance(m, float) else m.predict_proba(X)[:, 1]


def _pred_q(m, X):
    return np.sort(np.maximum(0.0, m.predict(X)), axis=1)   # monotone P10 ≤ P50 ≤ P90


def train(ds, p_xgb: np.ndarray, p_aqsvc: np.ndarray, log=print) -> dict:
    """Out-of-fold predictions for every snapshot + final models on all snapshots (saved for live use)."""
    t0 = time.time()
    T = cycles_to_floor(ds)
    X = ds.X
    oof_c = {req_key(f, c): np.zeros(len(X)) for f, c in requirements()}
    oof_q = {f: np.zeros((len(X), 3)) for f in floors()}
    for k, (tr, te) in enumerate(GroupKFold(n_splits=5).split(X, ds.y, ds.cell)):
        for f, c in requirements():
            oof_c[req_key(f, c)][te] = _pred_cls(_fit_cls(X[tr], (T[f][tr] >= c).astype(int)), X[te])
        for f in floors():
            oof_q[f][te] = _pred_q(_qreg().fit(X[tr], T[f][tr]), X[te])
        log(f"  usage models fold {k + 1}/5 ({time.time() - t0:.0f} s)")

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    for f, c in requirements():
        m = _fit_cls(X, (T[f] >= c).astype(int))
        if not isinstance(m, float):
            m.save_model(str(MODEL_DIR / f"cls_{req_key(f, c)}.json"))
    for f in floors():
        _qreg().fit(X, T[f]).save_model(str(MODEL_DIR / f"q_f{int(round(f * 100))}.json"))

    # validation, all out-of-fold
    from sklearn.metrics import brier_score_loss, roc_auc_score
    val_cls = {}
    for f, c in requirements():
        y = (T[f] >= c).astype(int)
        p = oof_c[req_key(f, c)]
        val_cls[req_key(f, c)] = {"floor": f, "cycles": c, "positives": float(y.mean()), "brier": float(brier_score_loss(y, p)),
                                  "auc": float(roc_auc_score(y, p)) if 0 < y.mean() < 1 else None}
    val_q = {}
    for f in floors():
        q = oof_q[f]
        inside = (T[f] >= q[:, 0]) & (T[f] <= q[:, 2])
        val_q[str(f)] = {"coverage_p10_p90": float(inside.mean()), "below_p10": float((T[f] < q[:, 0]).mean()),
                         "median_abs_error_cycles": float(np.median(np.abs(T[f] - q[:, 1])))}
    ref = {"fade_100": np.percentile(X[:, FEATURES.index("fade_100")], np.arange(101)).tolist(),
           "ir_rise_100": np.percentile(X[:, FEATURES.index("ir_rise_100")], np.arange(101)).tolist()}
    levels = np.array([risk(dict(zip(FEATURES, row)), float(a), float(b), ref)["level"]
                       for row, a, b in zip(X, p_xgb, p_aqsvc)])
    val_risk = {lv: {"snapshots": int((levels == lv).sum()),
                     "reached_80pct_within_100_cycles": float((ds.rul[levels == lv] < 100).mean()) if (levels == lv).any() else None}
                for lv in ("Low", "Elevated", "High")}
    meta = {"requirements": [req_key(f, c) for f, c in requirements()], "floors": floors(), "quantiles": QUANTILES,
            "risk_ref": ref, "validation": {"confidence_models": val_cls, "stop_period_models": val_q, "risk_levels": val_risk},
            "trained_on": int(len(X)), "seconds": round(time.time() - t0, 1)}
    meta["evidence_id"] = log_evidence("usage_baseline_models", {
        "backend": "XGBoost (classifiers per application requirement + quantile regressors per floor)",
        "inputs": FEATURES, "registry": [a["id"] for a in applications()], "baselines": baselines(),
        "validation": meta["validation"],
        "summary": f"{len(requirements())} confidence models + {len(floors())} stop-period models, grouped 5-fold CV on {len(X)} snapshots"})
    META.write_text(json.dumps(meta))
    return {"oof_cls": oof_c, "oof_q": oof_q, "meta": meta}


@lru_cache(maxsize=1)
def deployed() -> dict:
    """Final models for live screening (Assess / Upload)."""
    import xgboost as xgb
    meta = json.loads(META.read_text())
    cls, q = {}, {}
    for f, c in requirements():
        path = MODEL_DIR / f"cls_{req_key(f, c)}.json"
        if path.exists():
            m = xgb.XGBClassifier(); m.load_model(str(path)); cls[req_key(f, c)] = m
    for f in floors():
        m = xgb.XGBRegressor(); m.load_model(str(MODEL_DIR / f"q_f{int(round(f * 100))}.json")); q[f] = m
    return {"meta": meta, "cls": cls, "q": q}


def predict_live(x_row: np.ndarray) -> dict:
    d = deployed()
    X = np.asarray(x_row, float).reshape(1, -1)
    return {"cls": {k: float(m.predict_proba(X)[0, 1]) for k, m in d["cls"].items()},
            "q": {f: _pred_q(m, X)[0].tolist() for f, m in d["q"].items()}}


def oof_row(tr: dict, i: int) -> dict:
    return {"cls": {k: float(v[i]) for k, v in tr["oof_cls"].items()},
            "q": {f: tr["oof_q"][f][i].tolist() for f in floors()}}


# ----------------------------------------------------------------------------- per battery
def risk(feats: dict, p_xgb: float, p_aqsvc: float, ref: dict) -> dict:
    R = baselines()["risk"]
    hm = R["health_margin"]
    tp = R["temperature"]
    clip = lambda v: float(min(1.0, max(0.0, v)))
    pct = lambda key: clip(np.interp(feats[key], ref[key], np.arange(101)) / 100)
    p = (p_xgb + p_aqsvc) / 2
    disagree = (p_xgb >= 0.5) != (p_aqsvc >= 0.5)
    comp = {"health_margin": clip((hm["good_soh"] - feats["soh"]) / (hm["good_soh"] - hm["floor_soh"])),
            "fade_rate": pct("fade_100"), "resistance_rise": pct("ir_rise_100"),
            "temperature": clip((feats["temp_max_c"] - tp["cool_c"]) / (tp["hot_c"] - tp["cool_c"])),
            "model_doubt": 1.0 if disagree else clip(1 - abs(2 * p - 1))}
    score = sum(R["weights"][k] * v for k, v in comp.items())
    level = "High" if score >= R["levels"]["high_from"] else "Elevated" if score >= R["levels"]["elevated_from"] else "Low"
    return {"score": round(score, 3), "level": level, "components": {k: round(v, 3) for k, v in comp.items()},
            "tier_limit": R["tier_limit"][level]}


def _state(soh: float, floor: float, p10: float) -> str:
    if soh < floor or p10 <= 0:
        return "Stop use"
    if p10 <= baselines()["states"]["approaching_margin_cycles"]:
        return "Approaching limit"
    return "Safe"


def _stop(q: list[float], cap: float, cycles_per_year: float, soh: float, floor: float, state_cap: float | None = None) -> dict:
    """state_cap: the application's own cycle cap (the state follows it even while a temporary test cap applies)."""
    p10, p50, p90 = (min(cap, max(0.0, v)) for v in q)
    raw10 = min(state_cap if state_cap is not None else cap, max(0.0, q[0]))
    if soh < floor:
        p10 = p50 = p90 = raw10 = 0.0
    months = lambda c: round(c / (cycles_per_year / 12), 1)
    return {"p10": int(round(p10)), "p50": int(round(p50)), "p90": int(round(p90)), "cap": int(cap),
            "months_p10": months(p10), "months_p50": months(p50), "months_p90": months(p90),
            "state": _state(soh, floor, raw10)}


def _q(pred: dict, floor: float) -> list[float]:
    q = pred["q"]
    return q[floor] if floor in q else q[str(floor)]


def evaluate(feats: dict, p_xgb: float, p_aqsvc: float, action: str, pred: dict, ref: dict,
             chemistry: str = "LFP", rated_ah: float = config.NOMINAL_CAPACITY_AH) -> dict:
    """Usage baseline, risk factor, stop periods and ranked application confidence for one battery."""
    B = baselines()
    rk = risk(feats, p_xgb, p_aqsvc, ref)
    soh = float(feats["soh"])
    pathway = {"action": action, "label": {"reuse": "Reuse within the application's baseline",
                                           "test": B["pathways"]["test"]["label"],
                                           "recycle": B["pathways"]["recycle"]["label"]}[action]}
    if action == "test":
        pathway["baseline"] = {k: B["pathways"]["test"][k] for k in ("min_soh", "max_c_rate", "max_temp_c", "max_ir_mohm", "max_cycles_in_service")}
    apps = []
    for a in applications():
        gates = []
        if chemistry.upper() not in a["chemistries"]:
            gates.append(f"chemistry {chemistry} not allowed")
        if soh < a["min_soh"]:
            gates.append(f"health {soh:.0%} below floor {a['min_soh']:.0%}")
        if soh * rated_ah < a["min_capacity_ah"] * rated_ah / config.NOMINAL_CAPACITY_AH:
            gates.append("capacity below minimum")
        if abs(rated_ah - config.NOMINAL_CAPACITY_AH) < 1e-6 and feats["ir_mohm"] > a["max_ir_mohm"]:
            gates.append(f"resistance {feats['ir_mohm']:.1f} mΩ above {a['max_ir_mohm']} mΩ")
        if feats["temp_max_c"] > a["max_temp_c"]:
            gates.append(f"ran at {feats['temp_max_c']:.0f} °C, above {a['max_temp_c']} °C")
        if a["safety_tier"] > rk["tier_limit"]:
            gates.append(f"safety tier {a['safety_tier']} not allowed at {rk['level'].lower()} risk")
        tier_ok_for_test = a["safety_tier"] in B["pathways"]["test"]["allowed_safety_tiers"]
        if action == "recycle":
            status = "no second-life application"
        elif gates:
            status = "not suitable"
        elif action == "test":
            status = "conditional on test" if tier_ok_for_test else "not until tested"
        else:
            status = "suitable"
        # the model's stop period under the application's own baseline; a Test battery additionally carries the
        # temporary "restricted use until tested" cap, shown separately so it does not mask the prediction
        stop = _stop(_q(pred, a["min_soh"]), a["max_cycles_in_service"], a["cycles_per_year"], soh, a["min_soh"])
        if action == "test":
            stop["restricted_cap"] = B["pathways"]["test"]["max_cycles_in_service"]
        conf = None
        if status in ("suitable", "conditional on test"):
            conf = round(100 * pred["cls"][req_key(a["min_soh"], a["min_remaining_cycles"])], 1)
        apps.append({"id": a["id"], "name": a["name"], "icon": a["icon"], "safety_tier": a["safety_tier"], "status": status,
                     "confidence": conf, "confidence_source": "XGBoost classifier for this requirement (out-of-fold for fleet batteries)",
                     "low_confidence": conf is not None and conf < B["confidence"]["low_threshold_pct"],
                     "gates_failed": gates, "stop": stop,
                     "requirement": f"health ≥ {a['min_soh']:.0%} for ≥ {a['min_remaining_cycles']} more cycles",
                     "baseline": {k: a[k] for k in ("min_soh", "max_c_rate", "max_temp_c", "max_ir_mohm", "max_cycles_in_service")}})
    order = {"suitable": 0, "conditional on test": 1, "not until tested": 2, "not suitable": 3, "no second-life application": 4}
    apps.sort(key=lambda r: (order[r["status"]], -(r["confidence"] or 0), r["name"]))
    best = next((r for r in apps if r["confidence"] is not None), None)
    state = "Stop use" if action == "recycle" else (best["stop"]["state"] if best else "Stop use")
    return {"risk": rk, "pathway": pathway, "applications": apps, "best": best["id"] if best else None, "state": state,
            "label": B["label"], "note": B["note"],
            # the raw model outputs behind every % and stop period above, so they can be re-derived and audited
            "model_outputs": {"cls": {k: float(v) for k, v in pred["cls"].items()},
                              "q": {str(f): [float(x) for x in v] for f, v in pred["q"].items()}}}


def pack_usage(members: list[dict], ids: list[str]) -> dict:
    """Weakest member governs: per application, minimum confidence and minimum stop period over the members."""
    by_id = [{a["id"]: a for a in m["applications"]} for m in members]
    rows = []
    for a in applications():
        recs = [b[a["id"]] for b in by_id]
        if all(r["status"] == "suitable" for r in recs):
            k = int(np.argmin([r["stop"]["p10"] for r in recs]))
            conf = min(r["confidence"] for r in recs)
            rows.append({"id": a["id"], "name": a["name"], "icon": a["icon"], "confidence": conf,
                         "low_confidence": conf < baselines()["confidence"]["low_threshold_pct"],
                         "stop": {key: min(r["stop"][key] for r in recs) if key != "state" else recs[k]["stop"]["state"]
                                  for key in recs[k]["stop"]},
                         "limiter": ids[k], "baseline": recs[k]["baseline"]})
    rows.sort(key=lambda r: -r["confidence"])
    worst = {"Stop use": 0, "Approaching limit": 1, "Safe": 2}
    return {"applications": rows, "best": rows[0]["id"] if rows else None,
            "limiter": rows[0]["limiter"] if rows else None,
            "state": rows[0]["stop"]["state"] if rows else min((m["state"] for m in members), key=lambda s: worst.get(s, 0)),
            "risk_levels": [m["risk"]["level"] for m in members], "confidence_rule": "minimum over members"}
