"""Fleet allocation with QpiAI Opt: reuse / test / recycle + second-life pack building.

Every coefficient below is produced by the ML stage, not typed in:
  * value of reuse      <- measured health (usable energy)
  * risk of reuse       <- P(fit) from the two models (XGBoost + AQSVC), i.e. the chance it still has
                           >= LONG_LIFE_CYCLES cycles left
  * pack mismatch cost  <- 1 - quantum kernel similarity  +  health gap
  * forbidden pairs     <- very low quantum similarity or health gap

Decision variables (binary):
  r_b, t_b, c_b  battery b is reused / sent to full test / recycled   (exactly one)
  y_bp           battery b is placed in pack p                         (only if reused)
  u_p            pack p is built (then it holds exactly PACK_SIZE cells)

Solved three ways:
  1. QpiAI Opt local MILP (exact) and QpiAI Opt local QUBO annealer (needs QPIAI_OPT_API_KEY)
  2. built-in simulated annealing on the *same* QUBO exported by QpiAI Opt (no key)
  3. exact MILP (HiGHS) of the same model -> trusted optimum / certificate
"""

from __future__ import annotations

import itertools
import time

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp

from . import config
from .sponsors import log_evidence, opt_assignment, opt_client


def cell_value(soh: float) -> float:
    kwh = max(soh, 0) * config.NOMINAL_CAPACITY_AH * config.NOMINAL_VOLTAGE_V / 1000.0
    return kwh * config.VALUE_PER_KWH_SECOND_LIFE


def utilities(p_ok: np.ndarray, soh: np.ndarray) -> dict:
    """Expected utility of each action given P(fit) and the battery's usable energy."""
    p_ok = np.asarray(p_ok, float)
    val = np.array([cell_value(s) for s in soh])
    reuse = p_ok * val - (1 - p_ok) * config.FAILURE_COST_PER_CELL
    test = p_ok * val + (1 - p_ok) * config.RECYCLE_VALUE_PER_CELL - config.TEST_COST_PER_CELL
    recycle = np.full(len(soh), config.RECYCLE_VALUE_PER_CELL)
    return {"p_ok": p_ok, "value": val, "reuse": reuse, "test": test, "recycle": recycle}


def pair_costs(soh: np.ndarray, K: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Mismatch cost d_bc and forbidden-pair mask from quantum similarity + health gap."""
    gap = np.abs(soh[:, None] - soh[None, :])
    d = 0.5 * (1 - K) + 0.5 * np.minimum(1.0, gap / 0.05)
    forbid = (K < config.KERNEL_FORBID_BELOW) | (gap > config.SOH_SPREAD_FORBID)
    np.fill_diagonal(forbid, False)
    return d, forbid


def build_model(ids, p_ok, soh, K, n_packs: int, test_capacity: int, reuse_blocked):
    """Build the allocation as a QpiAI Opt Model (QUBO-compilable)."""
    from qpiai_opt.opt_modeller import Binary, Model, quicksum

    n = len(ids)
    U = utilities(p_ok, soh)
    d, forbid = pair_costs(soh, K)
    m = Model("cellfee_fleet_allocation")
    r = [Binary(f"r_{i}") for i in range(n)]
    t = [Binary(f"t_{i}") for i in range(n)]
    c = [Binary(f"c_{i}") for i in range(n)]
    reusable = [i for i in range(n) if not reuse_blocked[i]]
    y = {(i, p): Binary(f"y_{i}_{p}") for i in reusable for p in range(n_packs)}
    u = [Binary(f"u_{p}") for p in range(n_packs)]

    for i in range(n):
        m.add_constraint(r[i] + t[i] + c[i] == 1, label=f"one_action_{i}")
        if reuse_blocked[i]:
            m.add_constraint(r[i] == 0, label=f"reuse_blocked_{i}")
        else:
            m.add_constraint(quicksum(y[i, p] for p in range(n_packs)) == r[i], label=f"pack_if_reused_{i}")
    for p in range(n_packs):
        m.add_constraint(quicksum(y[i, p] for i in reusable) == config.PACK_SIZE * u[p], label=f"pack_size_{p}")
        for i, j in itertools.combinations(reusable, 2):
            if forbid[i, j]:
                m.add_constraint(y[i, p] + y[j, p] <= 1, label=f"forbid_{i}_{j}_{p}")
    m.add_constraint(quicksum(t) <= test_capacity, label="test_bench_capacity")
    for p in range(n_packs - 1):   # packs are interchangeable: build them in order (same optimum, less search)
        m.add_constraint(u[p] - u[p + 1] >= 0, label=f"pack_order_{p}")

    gain = quicksum(U["reuse"][i] * r[i] + U["test"][i] * t[i] + U["recycle"][i] * c[i] for i in range(n))
    mismatch = quicksum(config.MISMATCH_WEIGHT * d[i, j] * y[i, p] * y[j, p]
                        for p in range(n_packs) for i, j in itertools.combinations(reusable, 2) if not forbid[i, j])
    m.maximize(gain - mismatch)
    return m, {"r": r, "t": t, "c": c, "y": y, "u": u}, U, d, forbid


def build_milp_model(n, U, d, forbid, n_packs, test_capacity, reuse_blocked):
    """Same allocation, linearised (w >= y_b + y_c - 1) so QpiAI Opt can solve it exactly as a MILP."""
    from qpiai_opt.opt_modeller import Binary, Model, quicksum

    m = Model("cellfee_fleet_allocation_milp")
    r = [Binary(f"r_{i}") for i in range(n)]
    t = [Binary(f"t_{i}") for i in range(n)]
    c = [Binary(f"c_{i}") for i in range(n)]
    reusable = [i for i in range(n) if not reuse_blocked[i]]
    y = {(i, p): Binary(f"y_{i}_{p}") for i in reusable for p in range(n_packs)}
    u = [Binary(f"u_{p}") for p in range(n_packs)]
    pairs = [(i, j, p) for p in range(n_packs) for i, j in itertools.combinations(reusable, 2) if not forbid[i, j]]
    w = {k: Binary(f"w_{k[0]}_{k[1]}_{k[2]}") for k in pairs}
    for i in range(n):
        m.add_constraint(r[i] + t[i] + c[i] == 1, label=f"one_action_{i}")
        if reuse_blocked[i]:
            m.add_constraint(r[i] == 0, label=f"reuse_blocked_{i}")
        else:
            m.add_constraint(quicksum(y[i, p] for p in range(n_packs)) == r[i], label=f"pack_if_reused_{i}")
    for p in range(n_packs):
        m.add_constraint(quicksum(y[i, p] for i in reusable) == config.PACK_SIZE * u[p], label=f"pack_size_{p}")
        for i, j in itertools.combinations(reusable, 2):
            if forbid[i, j]:
                m.add_constraint(y[i, p] + y[j, p] <= 1, label=f"forbid_{i}_{j}_{p}")
    m.add_constraint(quicksum(t) <= test_capacity, label="test_bench_capacity")
    for p in range(n_packs - 1):   # packs are interchangeable: build them in order (same optimum, less search)
        m.add_constraint(u[p] - u[p + 1] >= 0, label=f"pack_order_{p}")
    for (i, j, p), wv in w.items():
        m.add_constraint(wv - y[i, p] - y[j, p] >= -1, label=f"link_{i}_{j}_{p}")
    m.maximize(quicksum(U["reuse"][i] * r[i] + U["test"][i] * t[i] + U["recycle"][i] * c[i] for i in range(n))
               - quicksum(config.MISMATCH_WEIGHT * d[i, j] * w[i, j, p] for i, j, p in pairs))
    return m


# ----------------------------------------------------------------------------- solvers
def _decode(values: dict, n: int, n_packs: int) -> tuple[list[str], list[list[int]]]:
    actions = []
    for i in range(n):
        if values.get(f"r_{i}", 0) > 0.5:
            actions.append("reuse")
        elif values.get(f"t_{i}", 0) > 0.5:
            actions.append("test")
        else:
            actions.append("recycle")
    packs = [[i for i in range(n) if values.get(f"y_{i}_{p}", 0) > 0.5] for p in range(n_packs)]
    return actions, packs


def solve_exact_milp(n, U, d, forbid, n_packs, test_capacity, reuse_blocked, time_limit: float = 120) -> dict:
    """Exact optimum via MILP (HiGHS) with product linearisation w >= y_i + y_j - 1."""
    reusable = [i for i in range(n) if not reuse_blocked[i]]
    names: list[str] = []
    idx = {}

    def var(name):
        idx[name] = len(names); names.append(name); return idx[name]

    for i in range(n):
        var(f"r_{i}"); var(f"t_{i}"); var(f"c_{i}")
    for i in reusable:
        for p in range(n_packs):
            var(f"y_{i}_{p}")
    for p in range(n_packs):
        var(f"u_{p}")
    pairs = [(i, j, p) for p in range(n_packs) for i, j in itertools.combinations(reusable, 2) if not forbid[i, j]]
    for i, j, p in pairs:
        var(f"w_{i}_{j}_{p}")
    nv = len(names)
    cost = np.zeros(nv)
    for i in range(n):
        cost[idx[f"r_{i}"]] = -U["reuse"][i]
        cost[idx[f"t_{i}"]] = -U["test"][i]
        cost[idx[f"c_{i}"]] = -U["recycle"][i]
    for i, j, p in pairs:
        cost[idx[f"w_{i}_{j}_{p}"]] = config.MISMATCH_WEIGHT * d[i, j]

    rows, lo, hi = [], [], []

    def add(coefs: dict, l, h):
        row = np.zeros(nv)
        for k, v in coefs.items():
            row[idx[k]] += v
        rows.append(row); lo.append(l); hi.append(h)

    for i in range(n):
        add({f"r_{i}": 1, f"t_{i}": 1, f"c_{i}": 1}, 1, 1)
        if reuse_blocked[i]:
            add({f"r_{i}": 1}, 0, 0)
        else:
            add({**{f"y_{i}_{p}": 1 for p in range(n_packs)}, f"r_{i}": -1}, 0, 0)
    for p in range(n_packs):
        add({**{f"y_{i}_{p}": 1 for i in reusable}, f"u_{p}": -config.PACK_SIZE}, 0, 0)
        for i, j in itertools.combinations(reusable, 2):
            if forbid[i, j]:
                add({f"y_{i}_{p}": 1, f"y_{j}_{p}": 1}, -np.inf, 1)
    add({f"t_{i}": 1 for i in range(n)}, -np.inf, test_capacity)
    for p in range(n_packs - 1):   # symmetry breaking, as in the QpiAI Opt model
        add({f"u_{p}": 1, f"u_{p + 1}": -1}, 0, np.inf)
    for i, j, p in pairs:
        add({f"w_{i}_{j}_{p}": 1, f"y_{i}_{p}": -1, f"y_{j}_{p}": -1}, -1, np.inf)

    integrality = np.array([0 if nm.startswith("w_") else 1 for nm in names])
    t0 = time.time()
    res = milp(cost, constraints=LinearConstraint(np.array(rows), lo, hi), integrality=integrality,
               bounds=Bounds(0, 1), options={"time_limit": time_limit})
    values = {nm: float(v) for nm, v in zip(names, res.x)} if res.x is not None else {}
    return {"values": values, "objective": -float(res.fun) if res.x is not None else None,
            "status": res.message, "optimal": res.status == 0, "seconds": round(time.time() - t0, 2),
            "mip_gap": getattr(res, "mip_gap", None)}


def solve_qubo_annealing(qubo: dict, offset: float, n_vars: int, sweeps: int = 700, reads: int = 6,
                         seed: int = config.SEED) -> tuple[np.ndarray, float]:
    """Simulated annealing on the QUBO exported by QpiAI Opt (fallback when no Opt key)."""
    Q = np.zeros((n_vars, n_vars))
    for (i, j), v in qubo.items():
        Q[i, j] += v
    Q = (Q + Q.T) / 2
    diag = np.diag(Q).copy()
    off = Q - np.diag(diag)
    rng = np.random.default_rng(seed)
    best_x, best_e = None, np.inf
    temps = np.geomspace(max(np.abs(Q).max(), 1.0) * 2, 1e-3, sweeps)
    for _ in range(reads):
        x = rng.integers(0, 2, n_vars).astype(float)
        field = off @ x
        e = x @ Q @ x
        for T in temps:
            for k in rng.permutation(n_vars):
                delta = (1 - 2 * x[k]) * (diag[k] + 2 * field[k])
                if delta < 0 or rng.random() < np.exp(-delta / T):
                    x[k] = 1 - x[k]
                    field += off[:, k] * (2 * x[k] - 1)
                    e += delta
        if e < best_e:
            best_e, best_x = e, x.copy()
    return best_x, float(best_e + offset)


def solve_allocation(ids, p_ok, soh, K, safety_flags=None, n_packs: int | None = None,
                     test_capacity: int = 6, true_fit=None, label="both",
                     opt_milp: bool = True, annealer: bool = True, log: bool = True,
                     time_limit: float = 120, highs: bool = True) -> dict:
    """One batch of batteries. opt_milp / annealer switch the QpiAI Opt runs (HiGHS always runs as the
    exact reference); log=False skips the per-batch evidence record (the caller logs one per fleet)."""
    n = len(ids)
    reuse_blocked = np.array([(p_ok[i] <= config.GRADE_C_P)
                              or bool(safety_flags is not None and safety_flags[i]) for i in range(n)])
    if n_packs is None:
        n_packs = max(1, min(config.MAX_PACKS_PER_BATCH, int((~reuse_blocked).sum()) // config.PACK_SIZE))
    if annealer:
        model, var, U, d, forbid = build_model(ids, p_ok, soh, K, n_packs, test_capacity, reuse_blocked)
    else:
        U = utilities(p_ok, soh)
        d, forbid = pair_costs(soh, K)

    solver_runs = []
    exact = {"objective": None, "values": {}}
    chosen_values, chosen_by = {}, None
    if highs or not opt_milp:   # HiGHS: the exact reference (skipped only when QpiAI Opt decides on its own)
        exact = solve_exact_milp(n, U, d, forbid, n_packs, test_capacity, reuse_blocked, time_limit)
        solver_runs.append({"solver": "Exact MILP (HiGHS)", "objective": exact["objective"], "optimal": exact["optimal"],
                            "seconds": exact["seconds"]})
        chosen_values, chosen_by = exact["values"], "Exact MILP (HiGHS)"

    qubo_info = None
    if annealer:
        qubo, offset = model.to_qubo_dict()
        var_names = list(model.qubo_variable_names)
        n_q = len(var_names)
        qubo_info = {"variables": n_q, "terms": len(qubo), "decision_variables": len(model.variables())}

    client = opt_client() if (opt_milp or annealer) else None
    if client is not None:
        from qpiai_opt.opt_solvers import solve

        try:
            if not opt_milp:
                raise _Skip
            t0 = time.time()
            milp_model = build_milp_model(n, U, d, forbid, n_packs, test_capacity, reuse_blocked)
            res = solve(milp_model, client=client)
            sol = opt_assignment(res, milp_model)
            chk = _check(sol, n, n_packs, forbid, reuse_blocked, test_capacity)
            obj = _objective(sol, n, n_packs, U, d, forbid, reuse_blocked)
            info = res.info() if callable(getattr(res, "info", None)) else None
            proven = bool(getattr(info, "optimality_proven", False)) or "optimality_proven=True" in str(info)
            solver_runs.append({"solver": "QpiAI Opt local MILP (exact)", "objective": obj, "feasible": chk["feasible"],
                                "optimal": proven, "seconds": round(time.time() - t0, 2),
                                "matches_highs": (exact["objective"] is not None and abs(obj - exact["objective"]) < 1e-6) if highs else None,
                                "info": str(info)[:1500]})
            if chk["feasible"]:
                chosen_values, chosen_by = sol, "QpiAI Opt local MILP (exact)"
        except _Skip:
            pass
        except Exception as exc:
            solver_runs.append({"solver": "QpiAI Opt local MILP (exact)", "error": str(exc)[:500]})
        try:
            if not annealer:
                raise _Skip
            t0 = time.time()
            # size reads/sweeps to stay inside QpiAI Opt's free local annealing budget (10M work units)
            pairs = sum(1 for i, j in qubo if i < j)
            linear = sum(1 for i, j in qubo if i == j)
            sweep_work = n_q + 2 * pairs + linear
            reads = 1
            sweeps = int(max(200, min(5000, (9_500_000 / reads - (2 * pairs + linear)) // sweep_work)))
            res = solve(model, client=client, num_reads=reads, num_sweeps=sweeps, seed=config.SEED)
            sol = opt_assignment(res, model)
            solver_runs.append({"solver": "QpiAI Opt local QUBO annealer (free-tier budget)",
                                "objective": _objective(sol, n, n_packs, U, d, forbid, reuse_blocked),
                                "feasible": _check(sol, n, n_packs, forbid, reuse_blocked, test_capacity)["feasible"],
                                "seconds": round(time.time() - t0, 2), "num_reads": reads, "num_sweeps": sweeps,
                                "info": str(res.info())[:1500]})
        except _Skip:
            pass
        except Exception as exc:
            solver_runs.append({"solver": "QpiAI Opt local QUBO annealer (free-tier budget)", "error": str(exc)[:500]})
    elif annealer:
        t0 = time.time()
        x, energy = solve_qubo_annealing(qubo, offset, n_q)
        sol = {var_names[k]: float(x[k]) for k in range(n_q) if var_names[k]}
        chk = _check(sol, n, n_packs, forbid, reuse_blocked, test_capacity)
        solver_runs.append({"solver": "Simulated annealing on QpiAI-Opt QUBO (no Opt key)",
                            "objective": _objective(sol, n, n_packs, U, d, forbid, reuse_blocked),
                            "feasible": chk["feasible"], "qubo_energy": energy, "seconds": round(time.time() - t0, 2)})

    if chosen_by is None:
        exact = solve_exact_milp(n, U, d, forbid, n_packs, test_capacity, reuse_blocked, time_limit)
        solver_runs.append({"solver": "Exact MILP (HiGHS)", "objective": exact["objective"], "optimal": exact["optimal"],
                            "seconds": exact["seconds"], "note": "fallback after QpiAI Opt"})
        chosen_values, chosen_by = exact["values"], "Exact MILP (HiGHS)"
    actions, packs = _decode(chosen_values, n, n_packs)
    check = _check(chosen_values, n, n_packs, forbid, reuse_blocked, test_capacity)
    out = {
        "label": label, "n_packs": n_packs, "test_capacity": test_capacity, "actions": actions,
        "packs": [pk for pk in packs if pk], "objective": _objective(chosen_values, n, n_packs, U, d, forbid, reuse_blocked),
        "solved_by": chosen_by,
        "solver_runs": solver_runs, "qubo": qubo_info, "constraint_check": check,
        "utilities": {k: np.round(v, 4).tolist() for k, v in U.items()},
        "reuse_blocked": reuse_blocked.tolist(), "forbidden_pairs": int(np.triu(forbid, 1).sum()),
        "mismatch_matrix": np.round(d, 4).tolist(),
    }
    if true_fit is not None:
        out["realized"] = realized_outcome(actions, out["packs"], true_fit, soh)
    if not log:
        return out
    out["evidence_id"] = log_evidence("allocation", {
        "backend": "QpiAI Opt modeller" + (" + QpiAI Opt solver" if client else " + built-in solvers"),
        "label": label, "qubo": qubo_info, "solver_runs": solver_runs, "actions": actions, "packs": out["packs"],
        "summary": f"{n} batteries, {n_packs} packs, solved by {chosen_by}, objective {out['objective']:.3f}"})
    return out


class _Skip(Exception):
    """Internal: a QpiAI Opt run switched off for this batch."""


def _objective(values, n, n_packs, U, d, forbid, reuse_blocked) -> float:
    actions, packs = _decode(values, n, n_packs)
    g = sum(U[a][i] for i, a in enumerate(actions))
    mm = sum(config.MISMATCH_WEIGHT * d[i, j] for pk in packs for i, j in itertools.combinations(pk, 2))
    return float(g - mm)


def _check(values, n, n_packs, forbid, reuse_blocked, test_capacity) -> dict:
    actions, packs = _decode(values, n, n_packs)
    v = []
    for i in range(n):
        k = sum(values.get(f"{a}_{i}", 0) > 0.5 for a in "rtc")
        if k != 1:
            v.append(f"battery {i}: {k} actions")
        in_packs = sum(i in pk for pk in packs)
        if (actions[i] == "reuse") != (in_packs == 1) or in_packs > 1:
            v.append(f"battery {i}: reuse/pack mismatch")
        if actions[i] == "reuse" and reuse_blocked[i]:
            v.append(f"battery {i}: blocked battery reused")
    for p, pk in enumerate(packs):
        if pk and len(pk) != config.PACK_SIZE:
            v.append(f"pack {p}: size {len(pk)}")
        for i, j in itertools.combinations(pk, 2):
            if forbid[i, j]:
                v.append(f"pack {p}: forbidden pair {i},{j}")
    if actions.count("test") > test_capacity:
        v.append("test capacity exceeded")
    return {"feasible": not v, "violations": v, "forbidden_assignments": sum("forbidden" in s for s in v)}


def realized_outcome(actions, packs, true_fit, soh) -> dict:
    """Score a plan against what really happened to each battery (possible only on held-out lab data):
    reusing a battery that in fact had < LONG_LIFE_CYCLES cycles left costs a pack rework."""
    true_fit = np.asarray(true_fit, bool)
    reused = [i for i, a in enumerate(actions) if a == "reuse"]
    tested = [i for i, a in enumerate(actions) if a == "test"]
    unfit = [i for i in reused if not true_fit[i]]
    value = sum(cell_value(soh[i]) if true_fit[i] else -config.FAILURE_COST_PER_CELL for i in reused)
    value += sum((cell_value(soh[i]) if true_fit[i] else config.RECYCLE_VALUE_PER_CELL)
                 - config.TEST_COST_PER_CELL for i in tested)
    value += sum(config.RECYCLE_VALUE_PER_CELL for i, a in enumerate(actions) if a == "recycle")
    missed = [i for i, a in enumerate(actions) if a == "recycle" and true_fit[i]]
    spreads = [float(np.ptp([soh[i] for i in pk])) for pk in packs if pk]
    return {"realized_value": round(float(value), 3), "unfit_reused": len(unfit), "reused": len(reused),
            "tested": len(tested), "good_cells_recycled": len(missed),
            "mean_pack_health_spread": round(float(np.mean(spreads)), 4) if spreads else None}
