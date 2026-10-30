"""End-to-end CELLFEE run:  python -m cellfee.pipeline  [--reuse-cv] [--retrain]

Stage A  two models, side by side on every snapshot (8,753 real snapshots, 124 cells, grouped 5-fold CV):
         XGBoost (classical)  ||  AQSVC (quantum: QpiAI QCloud kernel + QpiAI Opt QUBO training)
         -> artifacts/cv_oof.npz + cv_summary.json (reused with --reuse-cv)
Stage B  a 5,000-battery fleet, every battery judged out-of-fold by both models, decided by QpiAI Opt in
         truckload batches of BATCH_SIZE distinct cells (reuse / test / recycle + packs), QAOA pack balance,
         market matching
Final    deployed XGBoost + AQSVC for live screening and uploads (trained once; --retrain to redo)
Results: artifacts/results.json (fleet summary), artifacts/fleet_details.json (one full passport per battery),
run records in artifacts/evidence/.
"""

from __future__ import annotations

import itertools
import json
import os
import pickle
import sys
import time
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed

import numpy as np

from . import aqsvc, config, decision, environment, market, models, passports, quantum_kernel as qk, usage
from .allocation import pair_costs, solve_allocation
from .data import FEATURE_LABELS, FEATURES, AngleScaler, load_cells, load_snapshots, quantum_inputs, write_processed
from .qaoa import run_pack_balance
from .sponsors import log_evidence, status

warnings.filterwarnings("ignore")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DATA_SOURCE = ("Severson et al. (2019), Nature Energy 4, 383-391 - MIT / Stanford / Toyota Research Institute "
               "fast-charging dataset, 124 commercial A123 LFP/graphite 18650 cells (data.matr.io, CC-BY-4.0)")
CV_OOF = config.ARTIFACTS / "cv_oof.npz"
CV_SUMMARY = config.ARTIFACTS / "cv_summary.json"
FLEET_DETAILS = config.ARTIFACTS / "fleet_details.json"
SOLVED_CACHE = config.ARTIFACTS / "solved_batches.pkl"
VARIANTS = ["both", "rule", "xgb_small", "svc_rbf", "xgb", "qsvc", "aqsvc"]
COMPARISON_TIME_LIMIT = 15   # s per batch for the comparison variants (CELLFEE's own plan: 120 s)
HIGHS_CHECK_BATCHES = 10     # CELLFEE plan: QpiAI Opt exact MILP decides every batch; HiGHS re-solves the first 10
WORKERS = int(os.getenv("CELLFEE_WORKERS", str(max(4, min(10, (os.cpu_count() or 8) - 4)))))  # parallel batch solves
COMPARISON_BATCHES = 20      # the 7-variant decision comparison is scored on the first 20 batches (~650 batteries)


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ----------------------------------------------------------------------------- fleet
def choose_fleet(ds, n: int = config.FLEET_SIZE, seed: int = config.SEED) -> np.ndarray:
    """n battery records drawn from all snapshots (all 124 cells), in random arrival order."""
    rng = np.random.default_rng(seed)
    return rng.choice(len(ds.y), min(n, len(ds.y)), replace=False)


def make_batches(fleet_idx: np.ndarray, cells: np.ndarray, size: int = config.BATCH_SIZE) -> list[np.ndarray]:
    """Truckloads of ~size batteries in which no lab cell appears twice: each cell's records are dealt
    round-robin over the batches (possible while no cell has more records than there are batches)."""
    n_batches = int(np.ceil(len(fleet_idx) / size))
    by_cell: dict[str, list[int]] = {}
    for k in fleet_idx:
        by_cell.setdefault(str(cells[k]), []).append(int(k))
    batches: list[list[int]] = [[] for _ in range(n_batches)]
    slot = 0
    for c in sorted(by_cell, key=lambda c: -len(by_cell[c])):
        assert len(by_cell[c]) <= n_batches, "a cell has more records than there are batches"
        for k in by_cell[c]:
            batches[slot % n_batches].append(k)
            slot += 1
    return [np.array(b) for b in batches]


def rbf_similarity(Xa: np.ndarray) -> np.ndarray:
    d2 = ((Xa[:, None, :] - Xa[None, :, :]) ** 2).sum(-1)
    return np.exp(-d2 / np.median(d2[d2 > 0]))


def _solve_batch(job: tuple) -> dict:
    """Process-pool worker: one batch, one model variant."""
    label, ids, p, soh, K, true_fit, opt_milp, annealer, highs = job
    # CELLFEE's own plan gets the full exact solve; comparison variants are capped (proven-optimal flag recorded)
    out = solve_allocation(ids, p, soh, K, true_fit=true_fit, label=label, opt_milp=opt_milp, annealer=annealer,
                           log=False, time_limit=120 if label == "both" else COMPARISON_TIME_LIMIT, highs=highs)
    return {k: (v.tolist() if hasattr(v, "tolist") else v) for k, v in out.items()}


def explain(b: dict, a: str, U: dict, i: int, blocked: bool, test_capacity: int) -> str:
    """Plain reason for one battery's decision, consistent with its batch's optimum."""
    both = (f"XGBoost {b['p_xgb']:.0%} and AQSVC {b['p_aqsvc']:.0%} chance of "
            f"≥{config.LONG_LIFE_CYCLES} cycles left (health {b['soh']:.0%})")
    reuse, test, recyc = U["reuse"][i], U["test"][i], U["recycle"][i]
    if a == "reuse":
        return (f"Reuse in {b['pack']}: {both}. Expected value of reuse ₹{reuse:.2f} (test ₹{test:.2f}, recycle ₹{recyc:.2f}); "
                f"its pack-mates were chosen for high quantum similarity and close health.")
    if a == "test":
        if test >= reuse:
            why = f"testing first is worth ₹{test:.2f} vs ₹{reuse:.2f} for reusing it blind"
        else:
            why = (f"reusing it would be worth ₹{reuse:.2f}, but reuse needs a full {config.PACK_SIZE}-cell pack of "
                   f"compatible cells, and no such pack was available for it in its batch, so testing "
                   f"(₹{test:.2f}) beats recycling (₹{recyc:.2f})")
        agree = "" if b["agree"] else " The two models disagree."
        return f"Send to full capacity test: {both}.{agree} {why[0].upper() + why[1:]}."
    if blocked:
        return (f"Recycle: {both}. Combined chance {b['p_fit']:.0%} is at or below {config.GRADE_C_P:.0%}, "
                f"so reuse is blocked by a hard rule.")
    if test > recyc:
        return (f"Recycle: {both}. A test would be worth ₹{test:.2f}, but the test bench holds {test_capacity} "
                f"per batch and those slots went to batteries where testing adds more value.")
    return f"Recycle: {both}; neither reuse (₹{reuse:.2f}) nor a test (₹{test:.2f}) beats recycling (₹{recyc:.2f})."


# ----------------------------------------------------------------------------- stage A
def stage_a(ds, reuse: bool) -> dict:
    if reuse and CV_OOF.exists() and CV_SUMMARY.exists():
        log("reusing saved cross-validation (artifacts/cv_oof.npz)")
        z = np.load(CV_OOF)
        cv = json.loads(CV_SUMMARY.read_text())
        cv["oof"] = {m: z[m] for m in z.files}
        cv["mean_feature_map"] = np.array(cv["mean_feature_map"])
        return cv
    log("cross-validation by cell: XGBoost and AQSVC side by side, plus baselines...")
    cv = models.cross_validate(ds, n_folds=5, log=log)
    np.savez(CV_OOF, **cv["oof"])
    CV_SUMMARY.write_text(json.dumps({k: (v.tolist() if hasattr(v, "tolist") else v)
                                      for k, v in cv.items() if k != "oof"}, default=float))
    return cv


def final_models(ds, retrain: bool) -> dict:
    meta_path = config.ARTIFACTS / "final_model.json"
    sv_path = lambda n: config.ARTIFACTS / f"aqsvc_sv_states_{n}.npy"
    if not retrain and meta_path.exists() and (config.ARTIFACTS / "xgb_model.json").exists():
        meta = json.loads(meta_path.read_text())
        if "aqsvc" in meta and all(sv_path(m["inputs"]).exists() for m in meta["aqsvc"]["maps"]):
            log("reusing deployed XGBoost + AQSVC (artifacts/final_model.json)")
            return {"evidence_id": meta["evidence_id"], "sdk_vs_twin": meta["sdk_vs_twin_max_overlap_diff"],
                    "support_vectors": sum(len(m["sv_rows"]) for m in meta["aqsvc"]["maps"]), "qubos": meta["aqsvc"]["qubos"],
                    "maps": meta["aqsvc"]["maps"]}
    log("final XGBoost + AQSVC on all snapshots (trained side by side)...")
    final = models.fit_final(ds, log=log)
    q = final["quantum"]
    out_maps, sv_err = [], 0.0
    for m, e in zip(q["maps"], q["fit"]["ensembles"]):
        rows = e.support_rows()                      # indices into the training rows (= all snapshots here)
        log(f"support-vector states for live use, {m['n']}-input map: {len(rows)} circuits on QpiAI SDK...")
        Xa = m["scaler"].transform(quantum_inputs(ds.X[rows], m["n"]))
        st = qk.qpiai_statevectors(Xa, m["params"])
        sv_err = max(sv_err, float(np.max(np.abs(qk.kernel_from_states(st, st)
                                                 - qk.kernel_from_states(m["states"][rows], m["states"][rows])))))
        np.save(sv_path(m["n"]), st)
        remap = {int(r): k for k, r in enumerate(rows)}
        out_maps.append({"inputs": m["n"], "quantiles": m["scaler"].q.tolist(), "params": m["params"].vector().tolist(),
                         "layers": m["params"].layers, "validation_accuracy": m["tune"]["validation_accuracy"],
                         "sv_rows": [int(r) for r in rows],
                         "members": [{"rows": [remap[int(r)] for r in mm["idx"]], "coef": mm["coef"].tolist(), "b": mm["b"],
                                      "stage": mm["stage"]} for mm in e.members]})
    final["xgb"].save_model(str(config.ARTIFACTS / "xgb_model.json"))
    ev = aqsvc.evidence(q["runs"], "deployed model")
    st = q["fit"]["stack"]
    meta_path.write_text(json.dumps({
        "scaler_lo": final["scaler"].lo.tolist(), "scaler_hi": final["scaler"].hi.tolist(),
        "params": q["feature_map"]["params"].vector().tolist(), "layers": q["feature_map"]["params"].layers,
        "alignment": q["feature_map"]["alignment_trained"],
        "aqsvc": {"maps": out_maps, "stack": {"coef": st.coef.tolist(), "intercept": st.intercept}, "qubos": len(q["runs"])},
        "train_seconds": final["seconds"], "sdk_vs_twin_max_overlap_diff": sv_err, "evidence_id": ev}))
    return {"evidence_id": ev, "sdk_vs_twin": sv_err, "support_vectors": sum(len(m["sv_rows"]) for m in out_maps),
            "qubos": len(q["runs"]), "maps": out_maps}


# ----------------------------------------------------------------------------- run
def run(reuse_cv: bool = False, retrain: bool = False) -> dict:
    t_all = time.time()
    log("sponsor status: " + json.dumps(status()))
    ds = load_snapshots()
    write_processed(ds)
    log(f"data: {len(ds.y)} snapshots from {len(set(ds.cell))} cells, {ds.y.mean():.0%} fit; excluded {ds.excluded}")

    cv = stage_a(ds, reuse_cv)
    oof = cv["oof"]
    log("usage baselines: stop-period + application-confidence models (grouped 5-fold CV)...")
    use = usage.train(ds, oof["xgb"], oof["aqsvc"], log=log)
    ref = use["meta"]["risk_ref"]
    for m, v in cv["metrics"].items():
        log(f"  {m:10s} acc {v['accuracy']:.3f}  auc {v['auc']:.3f}  false-fit {v['false_fit_rate']:.3f}  {v['seconds']} s")

    scaler = AngleScaler().fit(ds.X)
    Xa = scaler.transform(ds.X)
    p_mean = qk.FeatureMapParams.from_vector(np.asarray(cv["mean_feature_map"]), 2)
    sample = np.random.default_rng(1).choice(len(Xa), 12, replace=False)
    twin_err = qk.verify_twin(Xa[sample], p_mean)
    log_evidence("twin_verification", {"backend": "QpiAI QCloud SDK", "device": "QpiAI-QSV-Local",
                                       "max_abs_kernel_difference": twin_err,
                                       "summary": f"NumPy twin vs QpiAI SDK kernel: max diff {twin_err:.2e}"})

    # ---------------- the fleet: 5,000 batteries, both models' out-of-fold answers ----------------
    fleet_idx = choose_fleet(ds)
    batches = make_batches(fleet_idx, ds.cell)
    order = np.concatenate(batches)                  # fleet order = batch order
    batch_of = np.concatenate([np.full(len(b), k) for k, b in enumerate(batches)])
    n = len(order)
    log(f"fleet: {n} batteries in {len(batches)} batches of ~{config.BATCH_SIZE} distinct cells")
    states = qk.numpy_statevectors(Xa[order], p_mean)  # QpiAI circuit (verified twin) for every fleet battery
    px, pq = oof["xgb"][order], oof["aqsvc"][order]
    ids = [f"RB-{k + 1:04d}" for k in range(n)]
    slim, detail = [], {}
    for k, i in enumerate(order):
        feats = {f: round(float(v), 5) for f, v in zip(FEATURES, ds.X[i])}
        g = decision.grade(float(px[k]), float(pq[k]))
        slim.append({"id": ids[k], "batch": int(batch_of[k]) + 1, "source_cell": str(ds.cell[i]), "cycle": int(ds.cycle[i]),
                     "soh": feats["soh"], "p_xgb": round(float(px[k]), 4), "p_aqsvc": round(float(pq[k]), 4),
                     "p_fit": round(g["p_fit"], 4), "agree": g["agree"], "grade": g["grade"], "features": feats})
        detail[ids[k]] = {"policy": str(ds.policy[i]), "angles": Xa[i].round(4).tolist(), "reason": g["reason"],
                          "truth": {"fit": bool(ds.y[i]), "cycles_left": int(ds.rul[i]), "cycle_life": int(ds.life[i])},
                          "predictions": {m: round(float(oof[m][i]), 4) for m in oof},
                          "measured": ["soh", "ir_mohm", "temp_max_c", "charge_time_min", "cycles"],
                          "from_history": ["fade_100", "ir_rise_100"]}

    # ---------------- QpiAI Opt decisions, batch by batch, every model variant ----------------
    soh = np.array([b["soh"] for b in slim])
    true_fit = np.array([detail[i]["truth"]["fit"] for i in ids])
    pos = {k: np.where(batch_of == k)[0] for k in range(len(batches))}
    Kq_b = {k: qk.kernel_from_states(states[pos[k]], states[pos[k]]) for k in pos}
    p_var = {"both": decision.p_fit_array(px, pq), **{m: oof[m][order] for m in models.MODEL_LABELS}}
    jobs, keys = [], []
    for v in VARIANTS:
        for k, rows in pos.items():
            if v != "both" and k >= COMPARISON_BATCHES:
                continue
            K = Kq_b[k] if v in ("both", "aqsvc", "qsvc") else (np.ones((len(rows),) * 2) if v == "rule" else
                                                              rbf_similarity(Xa[order[rows]]))
            jobs.append((v, [ids[r] for r in rows], p_var[v][rows], soh[rows], K, true_fit[rows],
                         v == "both", v == "both" and k == 0, v != "both" or k < HIGHS_CHECK_BATCHES))
            keys.append((v, k))
    log(f"QpiAI Opt allocation: {len(jobs)} batch problems (CELLFEE plan on all {len(batches)} batches; "
        f"{len(VARIANTS) - 1} comparison variants on the first {COMPARISON_BATCHES})...")
    t0 = time.time()
    solved = {}
    money = [config.VALUE_PER_KWH_SECOND_LIFE, config.RECYCLE_VALUE_PER_CELL, config.TEST_COST_PER_CELL,
             config.FAILURE_COST_PER_CELL, config.MISMATCH_WEIGHT]
    cache = pickle.loads(SOLVED_CACHE.read_bytes()) if reuse_cv and SOLVED_CACHE.exists() else None
    if cache and cache["keys"] == keys and cache["n"] == n and cache.get("money") == money:
        solved, jobs = cache["solved"], []
        log("  reusing solved batches from artifacts/solved_batches.pkl")
    with ProcessPoolExecutor(WORKERS) as pool:
        futures = {pool.submit(_solve_batch, j): key for j, key in zip(jobs, keys)}
        for done, fut in enumerate(as_completed(futures), 1):
            solved[futures[fut]] = fut.result()
            if done % 50 == 0 or done == len(futures):
                log(f"  {done}/{len(jobs)} batch problems solved ({time.time() - t0:.0f} s)")
    log(f"  solved in {time.time() - t0:.0f} s")
    SOLVED_CACHE.write_bytes(pickle.dumps({"keys": keys, "n": n, "money": money, "solved": solved}))

    # ---------------- assemble the CELLFEE plan (both models) ----------------
    pack_no, packs_named = 0, {}
    for k, rows in pos.items():
        plan = solved[("both", k)]
        names = []
        for pk in plan["packs"]:
            pack_no += 1
            names.append(f"PACK-{pack_no:03d}")
            packs_named[names[-1]] = [ids[rows[c]] for c in pk]
        Kk = Kq_b[k]
        for c, r in enumerate(rows):
            b = slim[r]
            b["action"] = plan["actions"][c]
            b["pack"] = next((names[j] for j, pk in enumerate(plan["packs"]) if c in pk), None)
            b["reuse_blocked"] = bool(plan["reuse_blocked"][c])
            U = plan["utilities"]
            d = detail[b["id"]]
            d["utilities"] = {u: round(float(U[u][c]), 4) for u in ("p_ok", "reuse", "test", "recycle")}
            d["explanation"] = explain(b, b["action"], U, c, b["reuse_blocked"], plan["test_capacity"])
            sims = sorted(((float(Kk[c, j]), j) for j in range(len(rows)) if j != c), reverse=True)[:5]
            d["similar"] = [{"id": ids[rows[j]], "k": round(v, 4)} for v, j in sims]
            gap = np.abs(soh[rows] - soh[r])
            # batteries in the same batch that may never share its pack (self has k = 1, gap 0, so never counted)
            d["incompatible"] = int(((Kk[c] < config.KERNEL_FORBID_BELOW) | (gap > config.SOH_SPREAD_FORBID)).sum())
            d["batch_size"] = len(rows)
            # usage baseline: risk, stop periods and application confidence (out-of-fold models), now the action is known
            i = order[r]
            u = usage.evaluate(b["features"], b["p_xgb"], b["p_aqsvc"], b["action"], usage.oof_row(use, i), ref)
            d["usage"] = u
            best = next((a for a in u["applications"] if a["id"] == u["best"]), None)
            b["risk"] = u["risk"]["level"]
            b["state"] = u["state"]
            b["best_app"] = best["name"] if best else None
            b["best_conf"] = best["confidence"] if best else None
            b["stop_p10"] = best["stop"]["p10"] if best else 0
    id_pos = {i: k for k, i in enumerate(ids)}
    for d in detail.values():   # actions are known for every battery only now
        for s in d["similar"]:
            s["action"] = slim[id_pos[s["id"]]]["action"]

    # batch 1 is the showcase batch: kernel heatmap, fidelity circuits, QAOA
    rows1 = pos[0]
    ids1 = [ids[r] for r in rows1]
    log(f"batch 1 kernel on QpiAI SDK ({len(rows1)} batteries)...")
    Xf = Xa[order[rows1]]
    Kq1 = qk.kernel_from_states(*(2 * [qk.qpiai_statevectors(Xf, p_mean)]))
    all_pairs = list(itertools.combinations(range(len(rows1)), 2))
    n_pairs = min(config.KERNEL_EVIDENCE_PAIRS, len(all_pairs))
    pairs = [all_pairs[k] for k in sorted(np.random.default_rng(2).choice(len(all_pairs), n_pairs, replace=False))]
    log(f"shot-based fidelity test: {len(pairs)} circuits on {config.KERNEL_DEVICE}...")
    ft = qk.fidelity_test_kernel(pairs, Xf, p_mean)
    exact_vals = [float(Kq1[i, j]) for i, j in pairs]
    ft_err = float(np.mean(np.abs(np.array(ft["values"]) - np.array(exact_vals))))

    plan1 = solved[("both", 0)]
    soh1 = soh[rows1]
    d_q, _ = pair_costs(soh1, Kq1)
    qcells = plan1["packs"][0] + plan1["packs"][1] if len(plan1["packs"]) >= 2 else list(np.argsort(-soh1)[: 2 * config.PACK_SIZE])
    log(f"QAOA pack balancing on {len(qcells)} cells of batch 1...")
    qa = run_pack_balance([int(c) for c in qcells], d_q)
    qa["cell_ids"] = [ids1[c] for c in qcells]
    for key in ("packs_exact", "packs_qaoa"):
        if qa.get(key):
            qa[key] = [[ids1[c] for c in pk] for pk in qa[key]]

    # pack-level usage baseline: the weakest member governs
    by_id = {b["id"]: k for k, b in enumerate(slim)}
    packs_detail = {}
    for name, cells_ in packs_named.items():
        pu = usage.pack_usage([detail[c]["usage"] for c in cells_], cells_)
        packs_detail[name] = {**pu, "members": cells_, "batch": slim[by_id[cells_[0]]]["batch"],
                              "capacity_ah": round(sum(slim[by_id[c]]["soh"] for c in cells_) * config.NOMINAL_CAPACITY_AH, 3)}

    # marketplace: a spread of CELLFEE packs (weakest to strongest) + seller listings
    pack_list = sorted(packs_named.items(), key=lambda kv: min(soh[by_id[c]] for c in kv[1]))
    show = [pack_list[int(round(j))] for j in np.linspace(0, len(pack_list) - 1, min(6, len(pack_list)))] if pack_list else []
    listings = [market.pack_listing(int(name.split("-")[1]) - 1, [by_id[c] for c in cells_], slim) for name, cells_ in show]
    for l, (name, _) in zip(listings, show):
        l["id"] = name
        l["app_confidence"] = {r["id"]: r["confidence"] for r in packs_detail[name]["applications"]}
    listings += market.SELLER_LISTINGS
    mk = market.match(listings, market.DEMO_BUYERS)
    reused_soh = [b["soh"] for b in slim if b["action"] == "reuse"]
    env_example = environment.estimate(soh=float(np.mean(reused_soh)) if reused_soh else 0.9,
                                       nominal_kwh=config.PACK_SIZE * config.NOMINAL_CAPACITY_AH * config.NOMINAL_VOLTAGE_V / 1000,
                                       distance_km=150)

    fin = final_models(ds, retrain)

    # ---------------- scores per model variant, summed over all batches ----------------
    def aggregate(v, upto=None):
        parts = [solved[(v, k)] for k in pos if upto is None or k < upto]
        R = {f: sum(p["realized"][f] for p in parts) for f in ("realized_value", "unfit_reused", "reused", "tested", "good_cells_recycled")}
        R["realized_value"] = round(R["realized_value"], 3)
        spreads = [p["realized"]["mean_pack_health_spread"] for p in parts if p["realized"]["mean_pack_health_spread"] is not None]
        R["mean_pack_health_spread"] = round(float(np.mean(spreads)), 4) if spreads else None
        R["forbidden_assignments"] = sum(p["constraint_check"]["forbidden_assignments"] for p in parts)
        R["objective"] = round(sum(p["objective"] for p in parts), 3)
        R["all_feasible"] = all(p["constraint_check"]["feasible"] for p in parts)
        R["proven_optimal_batches"] = sum(any(r.get("optimal") for r in p["solver_runs"]) for p in parts)
        R["batches_scored"] = len(parts)
        return R

    agg_cmp = {v: aggregate(v, COMPARISON_BATCHES) for v in VARIANTS}   # like-for-like comparison batches
    agg = {**agg_cmp, "both": aggregate("both")}                         # CELLFEE's own plan: the whole fleet
    both_parts = [solved[("both", k)] for k in pos]
    opt_runs = [r for p in both_parts for r in p["solver_runs"] if r["solver"] == "QpiAI Opt local MILP (exact)"]
    fleet_plan = {
        "batches": len(batches), "batteries": n, "batch_size": config.BATCH_SIZE, "packs": len(packs_named),
        "all_feasible": agg["both"]["all_feasible"], "forbidden_assignments": agg["both"]["forbidden_assignments"],
        "opt_milp_batches": sum("error" not in r for r in opt_runs),
        "opt_matches_highs": sum(bool(r.get("matches_highs")) for r in opt_runs),
        "highs_checked_batches": min(HIGHS_CHECK_BATCHES, len(batches)),
        "comparison_batches": min(COMPARISON_BATCHES, len(batches)),
        "comparison_batteries": int(sum(len(pos[k]) for k in pos if k < COMPARISON_BATCHES)),
        "opt_solved_by": sorted({p["solved_by"] for p in both_parts}),
        "objective": agg["both"]["objective"], "seconds": round(time.time() - t0, 1),
    }
    for v in VARIANTS:
        fleet_plan.setdefault("evidence_ids", {})[v] = log_evidence("fleet_allocation", {
            "backend": "QpiAI Opt local MILP + HiGHS" if v == "both" else "HiGHS exact MILP (comparison variant)",
            "label": v, **agg[v],
            "summary": f"{v}: {agg[v]['batches_scored']} batches, value ₹{agg[v]['realized_value']:.2f}, "
                       f"{agg[v]['forbidden_assignments']} forbidden assignments"})
    plan1["evidence_id"] = log_evidence("allocation", {
        "backend": "QpiAI Opt modeller + QpiAI Opt solver", "label": "both · batch 1", "qubo": plan1["qubo"],
        "solver_runs": plan1["solver_runs"], "actions": plan1["actions"], "packs": plan1["packs"],
        "summary": f"batch 1: {len(rows1)} batteries, solved by {plan1['solved_by']}, objective {plan1['objective']:.3f}"})

    comparison = {v: {"label": models.MODEL_LABELS.get(v, "B + C · XGBoost and AQSVC together (CELLFEE)"),
                      **(cv["metrics"][v] if v in cv["metrics"] else models.metrics(ds.y, decision.p_fit_array(oof["xgb"], oof["aqsvc"]))),
                      **agg_cmp[v]} for v in VARIANTS}
    agree = (oof["xgb"] >= 0.5) == (oof["aqsvc"] >= 0.5)
    yb = ds.y.astype(bool)
    side = {"agree_rate": float(agree.mean()),
            "accuracy_when_agree": float(((oof["xgb"] >= 0.5) == yb)[agree].mean()),
            "accuracy_xgb_when_disagree": float(((oof["xgb"] >= 0.5) == yb)[~agree].mean()) if (~agree).any() else None,
            "accuracy_aqsvc_when_disagree": float(((oof["aqsvc"] >= 0.5) == yb)[~agree].mean()) if (~agree).any() else None,
            "disagreements": int((~agree).sum())}
    runs = cv["aqsvc_runs"]
    results = {
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"), "rules_version": config.RULES_VERSION,
        "runtime_s": round(time.time() - t_all, 1), "sponsor_status": status(),
        "data": {"source": DATA_SOURCE, "snapshots": len(ds.y), "cells": len(set(ds.cell.tolist())),
                 "cycle_records": sum(len(c["cycle"]) for c in load_cells().values()), "excluded": ds.excluded,
                 "fit_share": float(ds.y.mean()), "policies": len(set(ds.policy.tolist())),
                 "features": [{"key": f, "label": FEATURE_LABELS[f]} for f in FEATURES],
                 "target": f"fit for second life = at least {config.LONG_LIFE_CYCLES} more cycles before capacity "
                           f"falls to 80% of 1.1 Ah", "soh_range": [float(ds.X[:, 0].min()), float(ds.X[:, 0].max())]},
        "qml": {
            "n_qubits": len(FEATURES), "layers": 2, "feature_map": p_mean.to_dict(),
            "circuit_text": circuit_description(len(FEATURES), 2),
            "folds": cv["folds"], "twin_max_error": twin_err,
            "fidelity_test": {"device": ft["device"], "requested_device": ft["requested_device"], "notes": ft["notes"],
                              "shots": ft["shots"], "pairs": pairs, "values": ft["values"], "exact": exact_vals,
                              "mean_abs_error": ft_err, "job_ids": ft["job_ids"], "evidence_id": ft["run_id"]},
            "fleet_kernel": np.round(Kq1, 4).tolist(), "kernel_ids": ids1, "kernel_angles": np.round(Xf, 4).tolist(),
        },
        "aqsvc": {
            "members": config.AQSVC_MEMBERS, "bag": config.AQSVC_BAG, "boost": config.AQSVC_BOOST,
            "maps": [{"inputs": m["inputs"], "layers": m["layers"], "scales": [round(v, 4) for v in m["params"][:-1]],
                      "entangle": round(m["params"][-1], 4), "validation_accuracy": m["validation_accuracy"]} for m in fin["maps"]],
            "fold_maps": [f.get("aqsvc_maps") for f in cv["folds"]],
            "vote_accuracy_by_fold": [f.get("aqsvc_vote_accuracy") for f in cv["folds"]],
            "ensemble": "bagging + boosting on two tuned quantum feature maps (8 and 7 inputs), combined by a stacking meta-learner",
            "subset": config.AQSVC_SUBSET, "bits": config.AQSVC_BITS,
            "base": config.AQSVC_BASE, "xi": config.AQSVC_XI, "qubo_vars": runs[0]["qubo_vars"] if runs else None,
            "solver": sorted({r["solver"] for r in runs}), "reads": config.AQSVC_READS,
            "sweeps": runs[0]["sweeps"] if runs else None, "qubos_solved": len(runs) + fin["qubos"],
            "mean_support_vectors": float(np.mean([r["support_vectors"] for r in runs])) if runs else None,
            "mean_seconds_per_qubo": float(np.mean([r["seconds"] for r in runs])) if runs else None,
            "cv_evidence_id": cv["aqsvc_evidence_id"], "final_evidence_id": fin["evidence_id"],
            "deployed_support_vectors": fin["support_vectors"], "sdk_vs_twin_max_overlap_diff": fin["sdk_vs_twin"],
            "formulation": "E(a) = 1/2 Σ α_n α_m y_n y_m k(x_n,x_m) − Σ α_n + ξ/2 (Σ α_n y_n)², "
                           "α_n = Σ_k 2^k a_{n,k} (Willsch et al. 2020)",
        },
        "side_by_side": side, "comparison": comparison, "fleet": slim, "fleet_plan": fleet_plan,
        "plan": {**plan1, "batch": 1, "ids": ids1}, "packs": packs_named,
        "qaoa": qa, "market": {**mk, "listings": listings, "buyers": market.DEMO_BUYERS, "locations": market.locations(),
                               "currency": "INR"},
        "environment_example": env_example, "applications": usage.applications(), "packs_detail": packs_detail,
        "usage": {"validation": use["meta"]["validation"], "evidence_id": use["meta"]["evidence_id"],
                  "baselines": usage.baselines(), "skipped_applications": usage.registry()["skipped"],
                  "label": usage.baselines()["label"], "note": usage.baselines()["note"],
                  "counts": {s: sum(b["state"] == s for b in slim) for s in ("Safe", "Approaching limit", "Stop use")},
                  "risk_counts": {lv: sum(b["risk"] == lv for b in slim) for lv in ("Low", "Elevated", "High")}},
        "assumptions": {k: getattr(config, k) for k in dir(config)
                        if k.isupper() and isinstance(getattr(config, k), (int, float)) and not isinstance(getattr(config, k), bool)},
    }
    FLEET_DETAILS.write_text(json.dumps(detail, default=float))
    passports.write(detail)                     # per-battery rows: the API reads one passport at a time
    config.RESULTS_JSON.write_text(json.dumps(results, default=float))
    log(f"done in {results['runtime_s']} s -> {config.RESULTS_JSON} ({n} batteries)")
    return results


def circuit_description(n: int, layers: int) -> str:
    return (f"{n} qubits (one per feature) · {layers} layers of [RY(s_q·x_q) → RZ(s_q·x_q) → ring RZZ(g·x_q·x_q+1)] · "
            f"kernel k(x,x') = |⟨0|U(x')†U(x)|0⟩|² · trainable s (per qubit) and g, fitted by kernel-target alignment")


if __name__ == "__main__":
    run(reuse_cv="--reuse-cv" in sys.argv, retrain="--retrain" in sys.argv)
