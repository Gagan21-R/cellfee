"""Two production models, run side by side on every battery, plus fair baselines.

    xgb        CLASSICAL  XGBoost gradient-boosted trees on all training snapshots
    aqsvc      QUANTUM    AQSVC: QpiAI feature-map kernels + SVMs trained as QUBOs on QpiAI Opt, combined by bagging,
                          boosting, two heterogeneous feature maps and a stacking meta-learner (aqsvc.py)

Baselines that make the comparison honest:
    rule       no ML: "fit" if health now >= a threshold learned on the training cells
    xgb_small  XGBoost trained on only the snapshots AQSVC saw (same data budget as the quantum model)
    svc_rbf    classical SVM ensemble, RBF kernel, same subsets, classical solver
    qsvc       the same quantum maps and ensemble (bagging + boosting + stacking), classical solver (isolates the annealer)

Evaluation is grouped cross-validation by cell: every prediction for a cell comes from models that never
saw any snapshot of that cell. Inside each fold XGBoost and AQSVC are trained at the same time
(two worker threads), and each records its own wall-clock time.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from sklearn.metrics import (accuracy_score, balanced_accuracy_score, brier_score_loss, f1_score,
                             precision_score, recall_score, roc_auc_score)
from sklearn.model_selection import GroupKFold

from . import aqsvc, config, quantum_kernel as qk
from .data import AngleScaler, Dataset, RankScaler, quantum_inputs

MODEL_LABELS = {
    "rule": "A · No ML (health threshold)",
    "xgb_small": "B1 · XGBoost, same data budget as AQSVC",
    "svc_rbf": "B2 · Classical SVM ensemble (RBF kernel)",
    "xgb": "B · XGBoost (classical model)",
    "qsvc": "C1 · Quantum-kernel SVM, classical solver",
    "aqsvc": "C · AQSVC (quantum model, QpiAI)",
}
PRIMARY = ("xgb", "aqsvc")
XGB_PARAMS = dict(n_estimators=300, max_depth=4, learning_rate=0.05, subsample=0.8, colsample_bytree=0.8,
                  random_state=config.SEED, n_jobs=4, eval_metric="logloss")


def make_xgb():
    import xgboost as xgb

    return xgb.XGBClassifier(**XGB_PARAMS)


def kta_subset(y: np.ndarray, rows: np.ndarray, n: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    pos, neg = rows[y[rows] == 1], rows[y[rows] == 0]
    return np.concatenate([rng.choice(pos, n // 2, replace=False), rng.choice(neg, n // 2, replace=False)])


def rbf_kernel(A: np.ndarray, B: np.ndarray, gamma: float) -> np.ndarray:
    return np.exp(-gamma * ((A[:, None, :] - B[None, :, :]) ** 2).sum(-1))


def fit_rule(soh: np.ndarray, y: np.ndarray) -> float:
    grid = np.unique(np.round(soh, 3))
    return float(max(grid, key=lambda t: balanced_accuracy_score(y, soh >= t)))


def similarity_map(Xa: np.ndarray, y: np.ndarray, rows: np.ndarray, seed: int) -> dict:
    """The 7-qubit feature map trained by kernel-target alignment: the quantum *similarity* used to build packs."""
    kta = kta_subset(y, rows, config.KTA_TRAIN_SAMPLES, seed)
    return qk.train_feature_map(Xa[kta], np.where(y[kta] == 1, 1.0, -1.0), n_layers=2, seed=seed)


def tuned_maps(X: np.ndarray, y: np.ndarray, rows: np.ndarray, cells: np.ndarray, seed: int) -> list[dict]:
    """AQSVC's classifier maps (heterogeneous models): rank-encoded inputs, scales tuned for held-out accuracy."""
    from concurrent.futures import ProcessPoolExecutor

    enc = {}
    for n in config.AQSVC_MAPS:
        Xn = quantum_inputs(X, n)
        scaler = RankScaler().fit(Xn[rows])
        enc[n] = (scaler, scaler.transform(Xn))
    with ProcessPoolExecutor(len(enc)) as pool:      # the maps are tuned at the same time
        jobs = {n: pool.submit(qk.tune_feature_map, Xa, y, rows, cells, 2, seed + n) for n, (_, Xa) in enc.items()}
        tuned = {n: f.result() for n, f in jobs.items()}
    return [{"n": n, "scaler": enc[n][0], "tune": tuned[n], "params": tuned[n]["params"],
             "states": qk.numpy_statevectors(enc[n][1], tuned[n]["params"])} for n in config.AQSVC_MAPS]


def fit_stack(maps: list[dict], y: np.ndarray, rows: np.ndarray, solver: str, seed: int, log=None) -> dict:
    """Bagging + boosting on each map (QUBOs on QpiAI Opt, or classical SVC), then stacking over all margins."""
    ens, oob = [], []
    for m in maps:
        S = m["states"][rows]
        e = aqsvc.Ensemble(solver, seed=seed + m["n"]).fit(lambda a, b, S=S: qk.kernel_from_states(S[a], S[b]), y[rows], log=log)
        ens.append(e)
        oob.append(e.out_of_bag(lambda idx, S=S: qk.kernel_from_states(S, S[idx]), len(rows)))
    stack = aqsvc.Stack().fit(np.vstack(oob), y[rows])
    return {"ensembles": ens, "stack": stack, "rows": rows}


def predict_stack(maps: list[dict], fit: dict, eval_rows: np.ndarray) -> dict:
    """Stacked probability and the plain vote share for eval_rows (indices into the full dataset)."""
    M = np.vstack([e.decision(lambda idx, m=m: qk.kernel_from_states(m["states"][eval_rows], m["states"][fit["rows"]][idx]))
                   for m, e in zip(maps, fit["ensembles"])])
    return {"p": fit["stack"].predict_proba(M), "vote": (M > 0).mean(axis=0)}


def train_quantum(X: np.ndarray, Xa: np.ndarray, y: np.ndarray, rows: np.ndarray, cells: np.ndarray, seed: int, log=None) -> dict:
    """AQSVC: similarity map (KTA), two accuracy-tuned classifier maps, bagged + boosted QUBO members, stacking."""
    t0 = time.time()
    sim = similarity_map(Xa, y, rows, seed)
    maps = tuned_maps(X, y, rows, cells, seed)
    if log:
        log("    AQSVC feature maps tuned: " + ", ".join(f"{m['n']} inputs -> validation accuracy {m['tune']['validation_accuracy']:.3f}" for m in maps))
    fit = fit_stack(maps, y, rows, "opt", seed, log=log)
    return {"feature_map": sim, "states": qk.numpy_statevectors(Xa[rows], sim["params"]), "maps": maps, "fit": fit,
            "runs": [r for e in fit["ensembles"] for r in e.runs], "seconds": round(time.time() - t0, 1)}


def train_classical(X: np.ndarray, y: np.ndarray, rows: np.ndarray) -> dict:
    t0 = time.time()
    m = make_xgb().fit(X[rows], y[rows])
    return {"model": m, "seconds": round(time.time() - t0, 1)}


def metrics(y: np.ndarray, p: np.ndarray) -> dict:
    yhat = p >= 0.5
    return {
        "accuracy": float(accuracy_score(y, yhat)), "balanced_accuracy": float(balanced_accuracy_score(y, yhat)),
        "precision": float(precision_score(y, yhat, zero_division=0)), "recall": float(recall_score(y, yhat)),
        "f1": float(f1_score(y, yhat)), "auc": float(roc_auc_score(y, p)) if len(set(y)) > 1 else None,
        "brier": float(brier_score_loss(y, np.clip(p, 0, 1))),
        # the costly mistake in second life: calling a battery fit when it is not
        "false_fit_rate": float(((yhat == 1) & (y == 0)).sum() / max(1, (y == 0).sum())),
    }


def cross_validate(ds: Dataset, n_folds: int = 5, log=print) -> dict:
    X, y = ds.X, ds.y
    oof = {m: np.full(len(y), np.nan) for m in MODEL_LABELS}
    seconds = {m: 0.0 for m in MODEL_LABELS}
    folds, aq_runs = [], []
    for f, (tr, te) in enumerate(GroupKFold(n_splits=n_folds).split(X, y, ds.cell)):
        log(f"fold {f + 1}/{n_folds}: {len(set(ds.cell[tr]))} training cells, {len(set(ds.cell[te]))} test cells")
        scaler = AngleScaler().fit(X[tr])
        Xa = scaler.transform(X)
        seed = config.SEED + f
        # the two production models train at the same time
        with ThreadPoolExecutor(2) as pool:
            fq = pool.submit(train_quantum, X, Xa, y, tr, ds.cell, seed, log)
            fc = pool.submit(train_classical, X, y, tr)
            q, c = fq.result(), fc.result()
        pq = predict_stack(q["maps"], q["fit"], te)
        oof["aqsvc"][te] = pq["p"]
        oof["xgb"][te] = c["model"].predict_proba(X[te])[:, 1]
        seconds["aqsvc"] += q["seconds"]
        seconds["xgb"] += c["seconds"]
        aq_runs += q["runs"]

        # baselines on the same fold
        t = time.time()
        thr = fit_rule(X[tr, 0], y[tr])
        oof["rule"][te] = (X[te, 0] >= thr).astype(float)
        seconds["rule"] += time.time() - t
        # exactly the snapshots the AQSVC members were trained on (same subsets, same seed)
        seen = tr[np.unique(np.concatenate([m["subset"] for e in q["fit"]["ensembles"] for m in e.members]))]
        t = time.time()
        oof["xgb_small"][te] = make_xgb().fit(X[seen], y[seen]).predict_proba(X[te])[:, 1]
        seconds["xgb_small"] += time.time() - t
        # same quantum maps, same bagging + boosting + stacking, but every SVM solved classically: isolates the annealer
        t = time.time()
        oof["qsvc"][te] = predict_stack(q["maps"], fit_stack(q["maps"], y, tr, "classical", seed), te)["p"]
        seconds["qsvc"] += time.time() - t
        Xs = Xa / np.pi
        gamma = 1.0 / (Xs.shape[1] * Xs[tr].var())
        kr = lambda a, b: rbf_kernel(Xs[tr][a], Xs[tr][b], gamma)
        t = time.time()
        e = aqsvc.Ensemble("classical", boost=0, seed=seed).fit(kr, y[tr])
        oof["svc_rbf"][te] = e.predict_proba(lambda idx: rbf_kernel(Xs[te], Xs[tr][idx], gamma))
        seconds["svc_rbf"] += time.time() - t

        fold_acc = {m: float(accuracy_score(y[te], oof[m][te] >= 0.5)) for m in MODEL_LABELS}
        log(f"  fold {f + 1} accuracy: " + ", ".join(f"{m} {v:.3f}" for m, v in fold_acc.items()))
        tf = q["feature_map"]
        folds.append({"fold": f + 1, "test_cells": sorted(set(ds.cell[te].tolist())), "accuracy": fold_acc,
                      "rule_threshold": thr, "alignment_untrained": tf["alignment_untrained"],
                      "alignment_trained": tf["alignment_trained"], "alignment_history": tf["history"],
                      "feature_map": tf["params"].to_dict(),
                      "aqsvc_maps": [{"inputs": m["n"], **m["params"].to_dict(), "validation_accuracy": m["tune"]["validation_accuracy"],
                                      "tuning_history": m["tune"]["history"]} for m in q["maps"]],
                      "aqsvc_vote_accuracy": float(accuracy_score(y[te], pq["vote"] >= 0.5)),
                      "seconds": {"xgb": c["seconds"], "aqsvc": q["seconds"]}})

    ev = aqsvc.evidence(aq_runs, "cross-validation")
    return {"oof": oof, "folds": folds, "aqsvc_runs": aq_runs, "aqsvc_evidence_id": ev,
            "metrics": {m: {**metrics(y, oof[m]), "seconds": round(seconds[m], 1)} for m in MODEL_LABELS},
            "mean_feature_map": np.mean([np.concatenate([fo["feature_map"]["scales"], [fo["feature_map"]["entangle"]]])
                                         for fo in folds], axis=0)}


def fit_final(ds: Dataset, log=print) -> dict:
    """Deployed models for live screening and uploads: both trained on every snapshot."""
    scaler = AngleScaler().fit(ds.X)
    Xa = scaler.transform(ds.X)
    rows = np.arange(len(ds.y))
    with ThreadPoolExecutor(2) as pool:
        fq = pool.submit(train_quantum, ds.X, Xa, ds.y, rows, ds.cell, config.SEED + 100, log)
        fc = pool.submit(train_classical, ds.X, ds.y, rows)
        q, c = fq.result(), fc.result()
    return {"scaler": scaler, "quantum": q, "xgb": c["model"], "seconds": {"xgb": c["seconds"], "aqsvc": q["seconds"]}}
