"""FastAPI backend:  uvicorn cellfee.api:app --port 8000   (from backend/)"""

from __future__ import annotations

import base64
import io
import json
import os
import sys
import re
import time
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config, decision, environment, experience_data, listings, market, passports, quantum_kernel as qk, report_extract, uploads, usage
from .data import FEATURES, AngleScaler, RankScaler, load_cells, quantum_inputs
from .sponsors import list_evidence, log_evidence, status

app = FastAPI(title="CELLFEE API", version=config.RULES_VERSION)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(listings.router)          # buy & sell marketplace (/api/listings ...)
FRONTEND = config.ROOT / "frontend" / "dist"
EXPERIENCE = config.ROOT / "experience"
NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate"}
DISCLAIMER = ("Preliminary decision support only — not a safety certification. "
              "Qualified inspection, BMS compatibility and integration checks are required.")


@lru_cache(maxsize=1)
def results() -> dict:
    if not config.RESULTS_JSON.exists():
        raise HTTPException(503, "Run `python -m cellfee.pipeline` first")
    return json.loads(config.RESULTS_JSON.read_text())


@lru_cache(maxsize=1)
def final_model() -> dict:
    import xgboost as xgb

    meta = json.loads((config.ARTIFACTS / "final_model.json").read_text())
    scaler = AngleScaler()
    scaler.lo, scaler.hi = np.array(meta["scaler_lo"]), np.array(meta["scaler_hi"])
    params = qk.FeatureMapParams.from_vector(np.array(meta["params"]), meta["layers"])
    clf = xgb.XGBClassifier()
    clf.load_model(str(config.ARTIFACTS / "xgb_model.json"))
    maps = []
    for mp in meta["aqsvc"]["maps"]:
        rs = RankScaler()
        rs.q = np.array(mp["quantiles"])
        maps.append({"inputs": mp["inputs"], "scaler": rs, "params": qk.FeatureMapParams.from_vector(np.array(mp["params"]), mp["layers"]),
                     "sv_states": np.load(config.ARTIFACTS / f"aqsvc_sv_states_{mp['inputs']}.npy"),
                     "members": [{"rows": np.array(m["rows"], int), "coef": np.array(m["coef"]), "b": m["b"]} for m in mp["members"]]})
    # fleet states for similarity: NumPy twin of the same QpiAI circuit (verified equal, see evidence)
    fleet_X = np.array([[b["features"][f] for f in FEATURES] for b in results()["fleet"]])
    return {"scaler": scaler, "params": params, "xgb": clf, "maps": maps, "stack": meta["aqsvc"]["stack"],
            "fleet_states": qk.numpy_statevectors(scaler.transform(fleet_X), params)}


@app.on_event("startup")
def warm_ocr() -> None:
    # the OCR model takes ~15 s to load: do it in the background so the first image upload is quick.
    # CELLFEE_WARM_OCR=0 (small cloud instances) loads it on the first image upload instead, to save memory.
    if os.getenv("CELLFEE_WARM_OCR", "1") == "0":
        return
    import threading
    threading.Thread(target=report_extract.ocr_available, daemon=True).start()


@app.on_event("startup")
def warm() -> None:
    if config.RESULTS_JSON.exists() and (config.ARTIFACTS / "final_model.json").exists():
        try:
            m = final_model()
        except (KeyError, FileNotFoundError):   # deployed model from an older pipeline version: retrain it
            return
        _run_aqsvc(np.array([[results()["fleet"][0]["features"][f] for f in FEATURES]]), m)
    if sys.platform.startswith("linux"):         # hand freed start-up buffers back to the OS (small cloud instances)
        try:
            import ctypes
            ctypes.CDLL("libc.so.6").malloc_trim(0)
        except OSError:
            pass


def _run_xgb(x: np.ndarray, m: dict) -> dict:
    t = time.perf_counter()
    p = float(m["xgb"].predict_proba(x)[0, 1])
    return {"p_fit": p, "says_fit": p >= 0.5, "ms": round((time.perf_counter() - t) * 1000, 1),
            "how": f"XGBoost, 300 trees, trained on {results()['data']['snapshots']:,} real snapshots"}


def _run_aqsvc(x: np.ndarray, m: dict) -> dict:
    """x: raw features (1, 7). Each tuned map builds this battery's QpiAI circuit; every member's margin feeds the
    stacking meta-learner (the probability); the members' plain vote is reported alongside."""
    t = time.perf_counter()
    margins = []
    for mp in m["maps"]:
        state = qk.qpiai_statevectors(mp["scaler"].transform(quantum_inputs(x, mp["inputs"])), mp["params"])
        k = qk.kernel_from_states(state, mp["sv_states"])[0]
        margins += [k[mm["rows"]] @ mm["coef"] + mm["b"] for mm in mp["members"]]
    margins = np.array(margins)
    p = float(1 / (1 + np.exp(-(np.dot(m["stack"]["coef"], margins) + m["stack"]["intercept"]))))
    votes = int((margins > 0).sum())
    sim_state = qk.qpiai_statevectors(m["scaler"].transform(x), m["params"])   # similarity map, for nearest batteries
    return {"p_fit": p, "says_fit": p >= 0.5, "votes_fit": votes, "members": len(margins),
            "ms": round((time.perf_counter() - t) * 1000, 1), "state": sim_state,
            "how": f"AQSVC: {len(margins)} quantum SVMs (QUBOs on QpiAI Opt) on {len(m['maps'])} QpiAI feature maps, "
                   f"bagged + boosted, combined by a stacking meta-learner"}


def screen(features: dict, distance_km: float = 150, notes: list[str] | None = None,
           chemistry: str = "LFP", rated_ah: float = config.NOMINAL_CAPACITY_AH) -> dict:
    """Run both models on one battery at the same time, then grade and explain."""
    m = final_model()
    x = np.array([[features[f] for f in FEATURES]], float)
    xa = m["scaler"].transform(x)
    with ThreadPoolExecutor(2) as pool:
        fx, fq = pool.submit(_run_xgb, x, m), pool.submit(_run_aqsvc, x, m)
        rx, rq = fx.result(), fq.result()
    state = rq.pop("state")
    g = decision.grade(rx["p_fit"], rq["p_fit"])
    soh = float(features["soh"])
    action = {"A": "reuse", "B": "reuse", "T": "test", "C": "recycle"}[g["grade"]]
    u = usage.evaluate(features, rx["p_fit"], rq["p_fit"], action, usage.predict_live(x[0]),
                       usage.deployed()["meta"]["risk_ref"], chemistry=chemistry, rated_ah=rated_ah)
    sim = qk.kernel_from_states(state, m["fleet_states"])[0]
    fleet = results()["fleet"]
    nearest = [{"id": fleet[i]["id"], "similarity": round(float(sim[i]), 3), "action": fleet[i].get("action")}
               for i in np.argsort(-sim)[:5]]
    circ = qk.build_feature_map_circuit(xa[0], m["params"])
    return {
        "features": {f: round(float(v), 5) for f, v in zip(FEATURES, x[0])}, "angles": xa[0].round(4).tolist(),
        "models": {"xgb": rx, "aqsvc": rq}, **g,
        "suggested_action": action, "soh": soh, "usage": u, "notes": notes or [], "chemistry": chemistry,
        "environment": environment.estimate(soh, config.NOMINAL_CAPACITY_AH * config.NOMINAL_VOLTAGE_V / 1000,
                                            distance_km),
        "circuit": {"qubits": circ.num_qubits, "depth": circ.depth(), "gates": circ.size(), "device": "QpiAI-QSV-Local"},
        "nearest_fleet_batteries": nearest, "disclaimer": DISCLAIMER,
    }


def _fill_gaps(feats: dict) -> tuple[dict, list[str]]:
    """Missing features are set to the fleet's typical value and flagged in the notes."""
    notes = []
    fleet = results()["fleet"]
    labels = {"fade_100": "capacity fade per 100 cycles (needs a test history)",
              "ir_rise_100": "resistance rise per 100 cycles (needs a test history)"}
    for k in FEATURES:
        v = feats.get(k)
        if v is None or not np.isfinite(v):
            feats[k] = float(np.median([b["features"][k] for b in fleet]))
            notes.append(f"{labels.get(k, k)} not given — assumed a typical value ({feats[k]:.3f})")
    return feats, notes


@app.get("/api/status")
def api_status():
    return {**status(), "results_ready": config.RESULTS_JSON.exists(), "passports": "per-battery database",
            "server_version": "2026-10-30 low-memory"}


@app.get("/api/results")
def api_results():
    return results()


@app.get("/api/fleet/{battery_id}")
def api_fleet_one(battery_id: str):
    """Full passport for one fleet battery (the fleet list in /api/results carries only the summary)."""
    slim = next((b for b in results()["fleet"] if b["id"] == battery_id), None)
    if slim is None:
        raise HTTPException(404, "unknown battery")
    return {**slim, **passports.get(battery_id)}   # one row read, not the whole 58 MB file


@app.get("/api/evidence")
def api_evidence():
    return list_evidence()


@app.get("/api/evidence/{run_id}")
def api_evidence_one(run_id: str):
    if not re.fullmatch(r"[0-9A-Za-z_-]{1,64}", run_id):
        raise HTTPException(404)
    path = config.EVIDENCE_DIR / f"{run_id}.json"
    if not path.exists():
        raise HTTPException(404)
    return json.loads(path.read_text())


class AssessIn(BaseModel):
    soh: float | None = Field(None, gt=0.3, le=1.2, description="health now = capacity / rating")
    capacity_ah: float | None = Field(None, gt=0, lt=1000)
    rated_capacity_ah: float = Field(config.NOMINAL_CAPACITY_AH, gt=0, lt=1000)
    fade_100: float | None = Field(None, ge=-0.05, le=0.5)
    ir_mohm: float = Field(..., gt=1, lt=200)
    ir_rise_100: float | None = Field(None, ge=-5, le=20)
    temp_max_c: float = Field(..., ge=-20, le=80)
    charge_time_min: float = Field(..., gt=1, lt=600)
    cycles: float = Field(..., ge=0, lt=10000)
    chemistry: str = Field("LFP", max_length=8)
    distance_km: float = 150


@app.post("/api/assess")
def api_assess(body: AssessIn):
    """Live screening of one battery: XGBoost and AQSVC run side by side."""
    soh = body.soh if body.soh is not None else (body.capacity_ah / body.rated_capacity_ah if body.capacity_ah else None)
    if soh is None:
        raise HTTPException(422, "give either soh or capacity_ah")
    feats, notes = _fill_gaps({"soh": soh, "fade_100": body.fade_100, "ir_mohm": body.ir_mohm,
                               "ir_rise_100": body.ir_rise_100, "temp_max_c": body.temp_max_c,
                               "charge_time_min": body.charge_time_min, "cycles": body.cycles})
    out = screen(feats, distance_km=body.distance_km, notes=notes, chemistry=body.chemistry.upper(),
                 rated_ah=body.rated_capacity_ah)
    out["evidence_id"] = log_evidence("assessment", {
        "backend": "XGBoost + AQSVC (deployed) + usage-baseline models", "inputs": out["features"],
        "outputs": {"grade": out["grade"], "action": out["suggested_action"], "state": out["usage"]["state"],
                    "risk": out["usage"]["risk"], "best_app": out["usage"]["best"],
                    "confidence": {a["id"]: a["confidence"] for a in out["usage"]["applications"] if a["confidence"] is not None}},
        "summary": f"live assessment: grade {out['grade']}, {out['usage']['state']}, risk {out['usage']['risk']['level']}"})
    return out


class UploadIn(BaseModel):
    filename: str = Field(..., max_length=200)
    content: str | None = Field(None, max_length=5_000_000)          # text files
    content_b64: str | None = Field(None, max_length=14_000_000)     # any file (PDF, image, Excel, Word, ...)
    distance_km: float = 150


@app.post("/api/upload")
def api_upload(body: UploadIn):
    """Screen every battery in an uploaded test-result file (CSV or JSON) with both models."""
    try:
        if body.content_b64 is not None:
            data = base64.b64decode(body.content_b64, validate=False)
            if len(data) > 10_000_000:
                raise ValueError("the file is larger than 10 MB")
            parsed = uploads.parse_document(body.filename, data)
        elif body.content is not None:
            parsed = uploads.parse(body.filename, body.content)
        else:
            raise ValueError("empty upload")
    except Exception as exc:
        raise HTTPException(422, f"could not read the file: {str(exc)[:300]}")
    out = []
    for b in parsed["batteries"]:
        if b["features"] is None:
            out.append({"battery_id": b["battery_id"], "error": b["error"], "notes": b["notes"]})
            continue
        feats, notes = _fill_gaps({k: b["features"].get(k) for k in FEATURES})
        out.append({"battery_id": b["battery_id"], "error": None,
                    **screen(feats, distance_km=body.distance_km, notes=b["notes"] + notes,
                             chemistry=b.get("chemistry", "LFP"), rated_ah=b.get("rated_ah", config.NOMINAL_CAPACITY_AH))})
    ok = [r for r in out if not r["error"]]
    ev = log_evidence("upload_screening", {
        "backend": "XGBoost + AQSVC (deployed) + usage-baseline models", "file": body.filename, "layout": parsed["layout"],
        "outputs": [{"battery_id": r["battery_id"], "grade": r["grade"], "state": r["usage"]["state"],
                     "risk": r["usage"]["risk"]["level"], "best_app": r["usage"]["best"]} for r in ok],
        "summary": f"upload {body.filename}: {len(ok)} screened"})
    return {"filename": body.filename, "evidence_id": ev, "document": parsed.get("document"), "layout": parsed["layout"], "columns": parsed["columns"],
            "warnings": parsed["warnings"], "screened": len(ok), "failed": len(out) - len(ok),
            "summary": {a: sum(r["suggested_action"] == a for r in ok) for a in ("reuse", "test", "recycle")},
            "results": out, "disclaimer": DISCLAIMER}


@app.get("/api/upload/sample.csv")
def api_upload_sample():
    """A real cycle log to try the upload with: three lab cells from the fleet (one per decision where possible),
    each up to the cycle at which it was screened."""
    cells = load_cells()
    fleet = results()["fleet"]
    pick = [b for b in (next((b for b in fleet if b.get("action") == a), None) for a in ("reuse", "test", "recycle")) if b]
    buf = io.StringIO()
    buf.write("battery_id,cycle,discharge_capacity_ah,internal_resistance_ohm,temperature_max_c,charge_time_min\n")
    for b in pick or fleet[:3]:
        c = cells[b["source_cell"]]
        for k in range(len(c["cycle"])):
            if b["cycle"] - 120 <= c["cycle"][k] <= b["cycle"]:
                buf.write(f"{b['id']},{int(c['cycle'][k])},{c['QDischarge'][k]:.4f},{c['IR'][k]:.5f},"
                          f"{c['Tmax'][k]:.2f},{c['chargetime'][k]:.2f}\n")
    return PlainTextResponse(buf.getvalue(), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=cellfee-sample-test-log.csv"})


class EnvIn(BaseModel):
    soh: float = Field(0.9, gt=0, le=1.1)
    nominal_kwh: float = Field(10.0, gt=0, le=200)
    distance_km: float = Field(150, ge=0, le=5000)
    baseline: str = "new_battery"
    overrides: dict[str, float] = {}


@app.post("/api/environment")
def api_environment(body: EnvIn):
    return environment.estimate(body.soh, body.nominal_kwh, body.distance_km, body.baseline, body.overrides)


@app.get("/api/environment/summary")
def api_environment_summary():
    """Totals under the same assumptions: the fleet plan's reused (and expected-after-test) cells, and the marketplace."""
    cell_kwh = config.NOMINAL_CAPACITY_AH * config.NOMINAL_VOLTAGE_V / 1000
    fleet = results()["fleet"]
    reused = [(b["soh"], cell_kwh) for b in fleet if b["action"] == "reuse"]
    # a tested battery is reused only if the test confirms it: weight each by the models' combined chance
    tested = [(b["soh"], cell_kwh * b["p_fit"]) for b in fleet if b["action"] == "test"]
    market_live, market_sold = [], []
    for r in listings.db().execute("SELECT * FROM listings WHERE status IN ('listed','interest_received','in_contact','sold')"):
        if r["verification"] not in listings.PUBLIC_VERIFICATION:
            continue
        doc = json.loads(r["doc"])
        rep, det = doc.get("report", {}), doc.get("details", {})
        try:
            soh = float(rep["soh_pct"]) / 100
            nominal = float(det["rated_capacity_kwh"]) if det.get("rated_capacity_kwh") not in (None, "", "not_available") \
                else float(rep["measured_capacity_kwh"]) / soh
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            continue
        (market_sold if r["status"] == "sold" else market_live).append((soh, nominal))
    return {
        "fleet_reused": environment.portfolio(reused, 150), "fleet_expected_after_test": environment.portfolio(tested, 150),
        "market_listed": environment.portfolio(market_live, 300), "market_sold": environment.portfolio(market_sold, 300),
        "assumptions": {"cell_kwh": round(cell_kwh, 5), "fleet_distance_km": 150, "market_distance_km": 300, "baseline": "buy a new battery instead"},
        "label": "Estimates under the stated assumptions, not measured savings",
    }


class BuyerIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=80)
    application: str
    min_energy_wh: float = Field(..., gt=0, le=10000)
    max_price: float = Field(..., gt=0, le=10_000_000)   # ₹
    location: str = "Pune"
    needs_test_report: bool = False

    def model_post_init(self, _ctx) -> None:
        if self.location not in market.CITIES:
            raise ValueError(f"unknown location {self.location}")


@app.post("/api/market/match")
def api_market_match(buyers: list[BuyerIn] | None = None):
    r = results()["market"]
    all_buyers = list(r["buyers"]) + [{"id": f"BUY-N{k + 1}", **b.model_dump()} for k, b in enumerate(buyers or [])]
    if any(b["application"] not in {a["id"] for a in usage.applications()} for b in all_buyers):
        raise HTTPException(422, "unknown application")
    return {**market.match(r["listings"], all_buyers), "listings": r["listings"], "buyers": all_buyers,
            "locations": market.locations(), "currency": "INR"}


class KernelRunIn(BaseModel):
    pairs: int = Field(6, ge=1, le=40)
    device: str = "QpiAI-QSV-Local"
    shots: int = Field(1000, ge=100, le=20000)


@app.post("/api/kernel/run")
def api_kernel_run(body: KernelRunIn):
    """Run fresh compute-uncompute kernel circuits on QpiAI QCloud and compare with exact values."""
    r = results()
    ids = r["qml"]["kernel_ids"]                   # the showcase batch (batch 1)
    X = np.array(r["qml"]["kernel_angles"])        # its angles under the mean feature map
    p = qk.FeatureMapParams(n_qubits=r["qml"]["n_qubits"], layers=r["qml"]["layers"],
                            scales=np.array(r["qml"]["feature_map"]["scales"]),
                            entangle=r["qml"]["feature_map"]["entangle"])
    rng = np.random.default_rng()
    pairs = [tuple(int(v) for v in rng.choice(len(ids), 2, replace=False)) for _ in range(body.pairs)]
    ft = qk.fidelity_test_kernel(pairs, X, p, device=body.device, shots=body.shots)
    K = r["qml"]["fleet_kernel"]
    return {**ft, "pairs": [[ids[i], ids[j]] for i, j in pairs],
            "exact": [K[i][j] for i, j in pairs]}


@app.get("/cellfee_results.json")
def experience_results():
    """Pipeline results in the scroll experience's data contract (see experience/index.html)."""
    return experience_data.build(results())


if (EXPERIENCE / "assets").exists():
    app.mount("/story-assets", StaticFiles(directory=EXPERIENCE / "assets"), name="story-assets")


@app.get("/")
def experience_page():
    return FileResponse(EXPERIENCE / "index.html", headers=NO_CACHE)


if FRONTEND.exists():
    app.mount("/dashboard/assets", StaticFiles(directory=FRONTEND / "assets"), name="assets")

    @app.get("/dashboard")
    @app.get("/dashboard/{path:path}")
    def spa(path: str = ""):
        # never cache the page shell, so a rebuilt dashboard shows up on a normal refresh
        return FileResponse(FRONTEND / "index.html", headers=NO_CACHE)
