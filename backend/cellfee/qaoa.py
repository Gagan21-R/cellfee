"""QAOA pack balancing: split 2*PACK_SIZE reuse-grade cells into two matched packs.

The sub-problem is written once with the QpiAI Opt modeller:
    minimise  sum_{i<j} d_ij * [x_i x_j + (1-x_i)(1-x_j)]     (same-pack mismatch)
    s.t.      sum_i x_i = PACK_SIZE
where d_ij comes from the quantum kernel + predicted SOH (see allocation.pair_costs).
A/B mirror solutions are the same split, so assignments are canonicalised with x_0 = 0.

Runs:
  * XY-mixer QAOA built from QpiAI QCloud circuits on QpiAI-QSV-Local: start in a valid
    4+4 split (X gates), cost layer RZ/RZZ from the Opt QUBO, ring XY mixer RXX+RYY that
    preserves the number of cells per pack, so every sample is a valid split. Angles are
    optimised classically (COBYLA on CVaR), then sampled with shots   [always, key-free]
  * QpiAI Opt's own QAOA through QCloud                           [when QCloud key set]
  * exact brute force over all 2^n assignments                     [ground truth]
"""

from __future__ import annotations

import itertools
import time

import numpy as np
from scipy.optimize import minimize

from . import config
from .sponsors import log_evidence, opt_assignment, qcloud_login, run_circuit


def build_split_model(d: np.ndarray):
    from qpiai_opt.opt_modeller import Binary, Model, quicksum

    n = len(d)
    x = [Binary(f"x_{i}") for i in range(n)]
    m = Model("cellfee_pack_balance")
    m.add_constraint(quicksum(x) == n // 2, label="equal_packs")
    m.minimize(quicksum(d[i, j] * (x[i] * x[j] + (1 - x[i]) * (1 - x[j]))
                        for i, j in itertools.combinations(range(n), 2)))
    return m


def _qubo_matrix(qubo: dict, n: int) -> np.ndarray:
    Q = np.zeros((n, n))
    for (i, j), v in qubo.items():
        Q[i, j] += v
    return Q


def _ising(Q: np.ndarray) -> tuple[np.ndarray, dict]:
    n = len(Q)
    h, J = np.zeros(n), {}
    for i in range(n):
        h[i] -= Q[i, i] / 2
        for j in range(n):
            if i != j and Q[i, j] != 0:
                h[i] -= Q[i, j] / 4
                h[j] -= Q[i, j] / 4
                a, b = min(i, j), max(i, j)
                J[a, b] = J.get((a, b), 0.0) + Q[i, j] / 4
    return h, J


def _all_energies(Q: np.ndarray, offset: float) -> np.ndarray:
    n = len(Q)
    idx = np.arange(2 ** n)
    bits = ((idx[:, None] >> np.arange(n)) & 1).astype(float)  # statevector index -> x (qubit q = bit q)
    return np.einsum("ki,ij,kj->k", bits, Q, bits) + offset, bits


def _qaoa_circuit(gammas, betas, h, J, n, measure=False):
    from qpiai_quantum import Circuit

    c = Circuit(n, n, name="cellfee_qaoa") if measure else Circuit(n, name="cellfee_qaoa")
    for q in range(1, n, 2):          # valid initial split: alternate cells into pack B
        c.x(q)
    for g, b in zip(gammas, betas):
        for q in range(n):
            if abs(h[q]) > 1e-12:
                c.rz(q, float(2 * g * h[q]))
        for (a, bq), w in J.items():
            if abs(w) > 1e-12:
                c.rzz(a, bq, float(2 * g * w))
        for parity in (0, 1):          # ring XY mixer, even then odd bonds
            for q in range(parity, n, 2):
                a, bq = q, (q + 1) % n
                c.rxx(a, bq, float(b))
                c.ryy(a, bq, float(b))
    if measure:
        c.measure(list(range(n)), list(range(n)))
    return c


def run_pack_balance(cells: list[int], d_full: np.ndarray, reps: int = 3, shots: int = 4000,
                     seed: int = config.SEED) -> dict:
    d = d_full[np.ix_(cells, cells)]
    model = build_split_model(d)
    qubo, offset = model.to_qubo_dict()
    names = list(model.qubo_variable_names)
    n = len(names)
    Q = _qubo_matrix(qubo, n)
    E, bits = _all_energies(Q, offset)

    # map QUBO variable order back to x_i
    xi = [int(nm.split("_")[1]) for nm in names]

    def to_assign(b_row):
        x = np.zeros(len(cells), int)
        for k, i in enumerate(xi):
            x[i] = int(b_row[k])
        return 1 - x if x[0] == 1 else x   # canonical: cell 0 always in pack A

    def objective(x):
        return float(sum(d[i, j] for i, j in itertools.combinations(range(len(x)), 2) if x[i] == x[j]))

    def feasible(x):
        return x[0] == 0 and x.sum() == len(cells) // 2

    feas_idx = [k for k in range(2 ** n) if feasible(to_assign(bits[k]))]
    opt_k = min(feas_idx, key=lambda k: E[k])
    exact_x = to_assign(bits[opt_k])
    exact_obj = objective(exact_x)

    # ---------------- QAOA on QpiAI QCloud circuits (QSV-Local) ----------------
    scale = np.abs(Q).max()
    h, J = _ising(Q / scale)
    Ef = E[feas_idx]
    En = (E - Ef.min()) / (Ef.max() - Ef.min() + 1e-12)
    history = []
    cvar_alpha = 0.25

    def expectation(theta):
        g, b = theta[:reps], theta[reps:]
        res = _qaoa_circuit(g, b, h, J, n).run(shots=1, device_name="QpiAI-QSV-Local", need_statevector=True,
                                               experiment_name="cellfee-qaoa-optimise")
        probs = np.abs(np.asarray(res.statevector)) ** 2
        order = np.argsort(En)
        cum = np.cumsum(probs[order])
        tail = cum <= cvar_alpha
        tail[np.argmax(cum > cvar_alpha)] = True
        w = probs[order] * tail
        val = float(w @ En[order] / max(w.sum(), 1e-12))
        history.append(val)
        return val

    t0 = time.time()
    rng = np.random.default_rng(seed)
    best = None
    for start in [np.concatenate([np.linspace(0.2, 0.8, reps), np.linspace(0.6, 0.2, reps)]),
                  rng.uniform(0, np.pi / 2, 2 * reps), rng.uniform(0, np.pi, 2 * reps)]:
        r = minimize(expectation, start, method="COBYLA", options={"maxiter": 150, "rhobeg": 0.4})
        if best is None or r.fun < best.fun:
            best = r
    g, b = best.x[:reps], best.x[reps:]

    res, device, device_note = run_circuit(_qaoa_circuit(g, b, h, J, n, measure=True), shots,
                                           config.QAOA_DEVICE if qcloud_login() else "QpiAI-QSV-Local")
    counts = res.get_counts() if hasattr(res, "get_counts") else res.counts
    job_ids = [res.job_id] if getattr(res, "job_id", None) else []
    sampled = []
    for key, cnt in counts.items():
        row = np.array([int(key[-1 - q]) for q in range(n)])  # QpiAI keys: qubit 0 is the rightmost bit
        x = to_assign(row)
        sampled.append((x, cnt, feasible(x), objective(x) if feasible(x) else None))
    feas_shots = sum(c for _, c, f, _ in sampled if f)
    opt_shots = sum(c for x, c, f, o in sampled if f and abs(o - exact_obj) < 1e-9)
    best_sample = min((s for s in sampled if s[2]), key=lambda s: s[3], default=None)
    mean_sampled = sum(c * o for _, c, f, o in sampled if f) / max(feas_shots, 1)
    mean_random = float(np.mean([objective(to_assign(bits[k])) for k in feas_idx]))
    n_opt_states = sum(1 for k in feas_idx if abs(objective(to_assign(bits[k])) - exact_obj) < 1e-9)
    random_p_opt = n_opt_states / len(feas_idx)
    n_feasible_states = len(feas_idx) // 2   # distinct splits (mirror pairs counted once)
    qaoa = {
        "solver": f"XY-mixer QAOA (p={reps}, CVaR α={cvar_alpha}) on QpiAI QCloud circuits",
        "optimise_device": "QpiAI-QSV-Local", "sample_device": device, "shots": shots,
        "angles": {"gamma": np.round(g, 4).tolist(), "beta": np.round(b, 4).tolist()},
        "energy_history": np.round(history, 5).tolist(),
        "feasible_fraction": feas_shots / shots, "optimal_probability": opt_shots / shots,
        "random_guess_optimal_probability": random_p_opt,
        "best_objective": best_sample[3] if best_sample else None,
        "mean_sampled_objective": mean_sampled, "mean_random_objective": mean_random,
        "best_assignment": best_sample[0].tolist() if best_sample else None,
        "approximation_ratio": (exact_obj / best_sample[3]) if best_sample and best_sample[3] else None,
        "seconds": round(time.time() - t0, 2), "job_ids": job_ids, "device_note": device_note,
    }

    runs = [qaoa]
    if qcloud_login():
        try:
            from qpiai_opt.opt_solvers import solve
            from qpiai_opt.opt_solvers.qubo import QUBOProblem
            from qpiai_opt.quantum import QAOA, QuantumRun

            t1 = time.time()
            r = solve(QUBOProblem.from_model(model), algorithm=QAOA(reps=reps, max_iterations=60),
                      execution=QuantumRun(shots=2048, seed=seed, experiment_name=config.QCLOUD_EXPERIMENT), mode="local")
            sol = opt_assignment(r, model)
            x = np.array([int(round(sol.get(f"x_{i}", 0))) for i in range(len(cells))])
            x = 1 - x if x[0] == 1 else x   # same canonical A/B labelling as above
            runs.append({"solver": "QpiAI Opt QAOA (local, QCloud-authenticated)", "assignment": x.tolist(), "feasible": bool(feasible(x)),
                         "objective": objective(x) if feasible(x) else None, "seconds": round(time.time() - t1, 2),
                         "info": str(r.info())[:2000]})
        except Exception as exc:
            runs.append({"solver": "QpiAI Opt QAOA (local, QCloud-authenticated)", "error": str(exc)[:500]})

    out = {
        "cells": cells, "n_qubits": n, "qubo_terms": len(qubo),
        "exact": {"objective": exact_obj, "assignment": exact_x.tolist(), "feasible_states": n_feasible_states},
        "runs": runs,
        "packs_exact": [[cells[i] for i in range(len(cells)) if exact_x[i] == k] for k in (0, 1)],
        "packs_qaoa": ([[cells[i] for i in range(len(cells)) if best_sample[0][i] == k] for k in (0, 1)]
                       if best_sample else None),
        "top_counts": sorted(({"bits": k, "count": v} for k, v in counts.items()), key=lambda z: -z["count"])[:12],
    }
    out["evidence_id"] = log_evidence("qaoa_pack_balance", {
        "backend": "QpiAI QCloud SDK circuits" + (" + QpiAI Opt QAOA" if len(runs) > 1 else ""),
        "device": device, "job_ids": job_ids, "result": out,
        "summary": f"{n}-qubit QAOA: P(optimal)={qaoa['optimal_probability']:.3f} vs random "
                   f"{random_p_opt:.3f}; exact objective {exact_obj:.3f}"})
    return out
