"""CELLFEE SDK: one entry point to every QpiAI-backed computation, each call a live run with recorded evidence.

Python:
    from cellfee.sdk import CellfeeSDK
    sdk = CellfeeSDK()
    sdk.status()                                  # QpiAI SDK version, keys configured, devices
    sdk.kernel(battery_a, battery_b, shots=2000)  # QpiAI QCloud: statevector + shot-based fidelity circuit
    sdk.train_qubo_svm(n=40)                      # QpiAI Opt: one AQSVC member trained as a QUBO
    sdk.screen(battery)                           # deployed XGBoost + AQSVC (QpiAI circuits, QUBO-trained SVMs)
    sdk.allocate(batch=1)                         # QpiAI Opt: reuse / test / recycle + packs for a truckload
    sdk.qaoa(batch=1)                             # QpiAI QCloud circuits: QAOA pack balancing
    sdk.match()                                   # QpiAI Opt: buyer <-> pack matching
    sdk.verify()                                  # reproducibility: re-run and compare with the recorded results

Command line (from backend/):
    python -m cellfee.sdk status | kernel | train | screen | allocate | qaoa | match | verify | demo
`demo` runs all of them and writes artifacts/sdk_report.json; every run is also an evidence record in
artifacts/evidence/ (shown on the dashboard's Evidence log). Keys are read from .env and never printed.
"""

from __future__ import annotations

import json
import sys
import time
from typing import Any

import numpy as np

from . import aqsvc, config, quantum_kernel as qk
from .data import FEATURES, AngleScaler, load_snapshots
from .sponsors import log_evidence, opt_client, status as sponsor_status

EXAMPLE_BATTERY = {"soh": 0.93, "fade_100": 0.012, "ir_mohm": 16.5, "ir_rise_100": 0.08, "temp_max_c": 34.0,
                   "charge_time_min": 11.5, "cycles": 420}
OTHER_BATTERY = {"soh": 0.86, "fade_100": 0.031, "ir_mohm": 18.9, "ir_rise_100": 0.35, "temp_max_c": 36.5,
                 "charge_time_min": 12.4, "cycles": 760}


def _results() -> dict:
    if not config.RESULTS_JSON.exists():
        raise RuntimeError("no pipeline results yet: run `python -m cellfee.pipeline` first")
    return json.loads(config.RESULTS_JSON.read_text())


def _vec(b: dict) -> np.ndarray:
    return np.array([[float(b[f]) for f in FEATURES]])


class CellfeeSDK:
    def __init__(self):
        self._ds = None

    # ------------------------------------------------------------------ status
    def status(self) -> dict:
        """Installed QpiAI packages, which keys are configured (never their values), devices in use."""
        s = sponsor_status()
        import qpiai_opt
        s["qpiai_opt_version"] = getattr(qpiai_opt, "__version__", "installed")
        s["opt_client_ready"] = opt_client() is not None
        return s

    # ------------------------------------------------------------------ QpiAI QCloud: quantum kernel
    def kernel(self, a: dict = EXAMPLE_BATTERY, b: dict = OTHER_BATTERY, shots: int | None = None, device: str | None = None) -> dict:
        """Quantum similarity of two batteries with the deployed similarity feature map:
        exact (QpiAI SDK statevectors) and shot-based (compute-uncompute circuit, P(all zeros), on `device`)."""
        meta = json.loads((config.ARTIFACTS / "final_model.json").read_text())
        sc = AngleScaler()
        sc.lo, sc.hi = np.array(meta["scaler_lo"]), np.array(meta["scaler_hi"])
        p = qk.FeatureMapParams.from_vector(np.array(meta["params"]), meta["layers"])
        X = sc.transform(np.vstack([_vec(a), _vec(b)]))
        st = qk.qpiai_statevectors(X, p)
        exact = float(qk.kernel_from_states(st[:1], st[1:])[0, 0])
        twin = qk.numpy_statevectors(X, p)
        ft = qk.fidelity_test_kernel([(0, 1)], X, p, device=device, shots=shots)
        return {"exact_statevector": exact, "shot_estimate": ft["values"][0], "shots": ft["shots"], "device": ft["device"],
                "notes": ft["notes"], "job_ids": ft["job_ids"], "twin_difference": float(abs(exact - qk.kernel_from_states(twin[:1], twin[1:])[0, 0])),
                "circuit": {"qubits": p.n_qubits, "layers": p.layers}, "evidence_id": ft["run_id"]}

    # ------------------------------------------------------------------ QpiAI Opt: one AQSVC member as a QUBO
    def train_qubo_svm(self, n: int = config.AQSVC_SUBSET, seed: int = config.SEED) -> dict:
        """Train one SVM of AQSVC as a QUBO on QpiAI Opt, on n real snapshots (balanced), with the deployed 8-input map.
        Checks: QUBO energy vs the built-in annealer on the same matrix, and held-out accuracy vs the classical SVC
        solution of the same dual problem."""
        from sklearn.svm import SVC
        from .data import RankScaler, quantum_inputs

        ds = self._data()
        meta = json.loads((config.ARTIFACTS / "final_model.json").read_text())
        mp = next(m for m in meta["aqsvc"]["maps"] if m["inputs"] == 8)
        rs = RankScaler(); rs.q = np.array(mp["quantiles"])
        p = qk.FeatureMapParams.from_vector(np.array(mp["params"]), mp["layers"])
        rng = np.random.default_rng(seed)
        idx = aqsvc.balanced_subsets(ds.y, 1, n, seed)[0]
        test = rng.choice(np.setdiff1d(np.arange(len(ds.y)), idx), 500, replace=False)
        S = qk.numpy_statevectors(rs.transform(quantum_inputs(ds.X[np.concatenate([idx, test])], 8)), p)
        K, Kt = qk.kernel_from_states(S[:n], S[:n]), qk.kernel_from_states(S[n:], S[:n])
        ys, yt = np.where(ds.y[idx] == 1, 1.0, -1.0), np.where(ds.y[test] == 1, 1.0, -1.0)
        client = opt_client()
        r = aqsvc.train_member(K, ys, seed=seed, client=client)
        M = aqsvc.qubo_matrix(K, ys)
        sa = aqsvc._anneal(M, 4, r["sweeps"], np.random.default_rng(seed))
        acc_q = float(np.mean(np.sign(Kt @ (r["alpha"] * ys) + r["b"]) == yt))
        C = float(sum(config.AQSVC_BASE ** j for j in range(config.AQSVC_BITS)))
        acc_c = float(np.mean(np.sign(SVC(kernel="precomputed", C=C).fit(K, ys).decision_function(Kt)) == yt))
        ev = aqsvc.evidence([{k: r[k] for k in ("solver", "energy", "reads", "sweeps", "qubo_vars", "seconds", "info")}
                             | {"support_vectors": int((r["alpha"] > 0).sum()), "stage": "sdk"}], "SDK single-member check")
        return {"solver": r["solver"], "qubo_variables": r["qubo_vars"], "reads": r["reads"], "sweeps": r["sweeps"],
                "seconds": r["seconds"], "energy_qpiai_opt": r["energy"], "energy_builtin_annealer": float(sa @ M @ sa),
                "support_vectors": int((r["alpha"] > 0).sum()), "held_out_accuracy_qubo": acc_q,
                "held_out_accuracy_classical_svc": acc_c, "held_out_snapshots": len(test), "evidence_id": ev}

    # ------------------------------------------------------------------ deployed models on one battery
    def screen(self, battery: dict = EXAMPLE_BATTERY) -> dict:
        """XGBoost and AQSVC side by side on one battery (AQSVC: QpiAI SDK circuits + QUBO-trained SVMs, stacked)."""
        from . import api

        t = time.time()
        r = api.screen(dict(battery))
        out = {"p_xgb": r["models"]["xgb"]["p_fit"], "p_aqsvc": r["models"]["aqsvc"]["p_fit"],
               "aqsvc_votes": f"{r['models']['aqsvc']['votes_fit']} of {r['models']['aqsvc']['members']}",
               "grade": r["grade"], "suggested_action": r["suggested_action"], "circuit": r["circuit"],
               "nearest_fleet_batteries": r["nearest_fleet_batteries"][:3], "seconds": round(time.time() - t, 2)}
        out["evidence_id"] = log_evidence("sdk_screen", {"backend": "QpiAI QCloud SDK (circuits) + QUBO-trained AQSVC", "device": "QpiAI-QSV-Local",
                                                         "battery": battery, **out, "summary": f"SDK screen: XGBoost {out['p_xgb']:.2f}, AQSVC {out['p_aqsvc']:.2f}, grade {out['grade']}"})
        return out

    # ------------------------------------------------------------------ QpiAI Opt: fleet decision for one truckload
    def _batch(self, batch: int):
        R = _results()
        rows = [b for b in R["fleet"] if b["batch"] == batch]
        ids = [b["id"] for b in rows]
        p = np.array([b["p_fit"] for b in rows])
        soh = np.array([b["soh"] for b in rows])
        return R, rows, ids, p, soh

    def allocate(self, batch: int = 1, time_limit: float = 120) -> dict:
        """Reuse / test / recycle + packs for one truckload with QpiAI Opt (exact MILP + QUBO annealer), HiGHS as reference.
        Batch 1 uses the recorded quantum kernel, so the objective can be compared with the pipeline's."""
        from .allocation import solve_allocation

        R, rows, ids, p, soh = self._batch(batch)
        if batch == 1:
            K = np.array(R["qml"]["fleet_kernel"])
        else:
            raise ValueError("the SDK re-solves the recorded showcase batch (batch=1)")
        out = solve_allocation(ids, p, soh, K, label=f"sdk · batch {batch}", time_limit=time_limit)
        runs = [{"solver": r["solver"], "objective": r.get("objective"), "optimal": r.get("optimal"), "seconds": r.get("seconds")} for r in out["solver_runs"]]
        return {"batteries": len(ids), "solved_by": out["solved_by"], "objective": out["objective"], "solver_runs": runs,
                "packs": [[ids[c] for c in pk] for pk in out["packs"]], "actions": dict(zip(ids, out["actions"])),
                "feasible": out["constraint_check"]["feasible"], "qubo": out.get("qubo"), "evidence_id": out.get("evidence_id")}

    # ------------------------------------------------------------------ QpiAI QCloud: QAOA pack balancing
    def qaoa(self, batch: int = 1, shots: int = 4000) -> dict:
        """Split the 8 reuse cells of the batch's first two packs into two balanced packs with QAOA (QpiAI circuits)."""
        from .allocation import pair_costs
        from .qaoa import run_pack_balance

        R, rows, ids, p, soh = self._batch(batch)
        K = np.array(R["qml"]["fleet_kernel"])
        d, _ = pair_costs(soh, K)
        cells = [ids.index(c) for c in R["qaoa"]["cell_ids"]]
        r = run_pack_balance(cells, d, shots=shots)
        best = r["runs"][0]
        return {"cells": [ids[c] for c in cells], "qubits": r["n_qubits"], "qubo_terms": r["qubo_terms"], "solver": best["solver"],
                "device": best.get("sample_device"), "optimal_probability": best["optimal_probability"],
                "random_guess_optimal_probability": best["random_guess_optimal_probability"],
                "approximation_ratio": best["approximation_ratio"], "exact_optimum": r["exact"], "evidence_id": r.get("evidence_id")}

    # ------------------------------------------------------------------ QpiAI Opt: market matching
    def match(self) -> dict:
        from . import market

        R = _results()
        mk = market.match(R["market"]["listings"], R["market"]["buyers"])
        out = {"solver": mk["solver"], "pairs_screened": mk["all_pairs"], "compatible_pairs": mk["compatible_pairs"],
               "matches": [(m["buyer"], m["listing"], round(m["score"], 4)) for m in mk["matches"]], "total_score": mk["total_score"]}
        out["evidence_id"] = mk.get("evidence_id") or log_evidence("sdk_market_matching", {
            "backend": "QpiAI Opt", **out, "summary": f"SDK match: {len(out['matches'])} buyer-listing matches, total score {out['total_score']:.3f}"})
        return out

    # ------------------------------------------------------------------ reproducibility
    def verify(self) -> dict:
        """Re-run deterministic parts and compare with the recorded results (results.json)."""
        R = _results()
        checks = []
        def add(name, ok, detail):
            checks.append({"check": name, "pass": bool(ok), "detail": detail})

        fm = R["qml"]["feature_map"]
        p = qk.FeatureMapParams(n_qubits=fm["n_qubits"], layers=fm["layers"], scales=np.array(fm["scales"]), entangle=fm["entangle"])
        Xf = np.array(R["qml"]["kernel_angles"])
        st = qk.qpiai_statevectors(Xf, p)
        Kq = qk.kernel_from_states(st, st)
        Krec = np.array(R["qml"]["fleet_kernel"])
        err = float(np.max(np.abs(Kq - Krec)))
        add("QpiAI SDK kernel (batch 1) reproduces the recorded kernel", err < 2e-3, f"max |difference| {err:.2e} (recorded to 4 decimals, angles to 4 decimals)")
        twin = qk.numpy_statevectors(Xf, p)
        e2 = float(np.max(np.abs(qk.kernel_from_states(twin, twin) - Kq)))
        add("NumPy training twin equals the QpiAI SDK circuit", e2 < 1e-9, f"max |difference| {e2:.2e}")
        ft = R["qml"]["fidelity_test"]
        fe = float(np.mean(np.abs(np.array(ft["values"]) - np.array(ft["exact"]))))
        add("Recorded shot-based fidelity circuits agree with exact overlaps", fe < 0.05, f"mean |shots - exact| {fe:.4f} over {len(ft['values'])} circuits, {ft['shots']} shots")
        a = self.allocate(1)
        rec = R["plan"]["objective"]
        add("QpiAI Opt re-solves batch 1 to the recorded objective", abs(a["objective"] - rec) <= 1e-3 * max(1.0, abs(rec)),
            f"now {a['objective']:.4f} vs recorded {rec:.4f} (solved by {a['solved_by']})")
        hi = next((r for r in a["solver_runs"] if "HiGHS" in r["solver"]), None)
        qo = next((r for r in a["solver_runs"] if "QpiAI Opt local MILP" in r["solver"]), None)
        if hi and qo and qo["objective"] is not None:
            add("QpiAI Opt exact MILP matches the HiGHS reference", abs(qo["objective"] - hi["objective"]) <= 1e-6 * max(1, abs(hi["objective"])),
                f"QpiAI Opt {qo['objective']:.6f} vs HiGHS {hi['objective']:.6f}")
        m = self.match()
        add("QpiAI Opt market matching reproduces the recorded total score", abs(m["total_score"] - R["market"]["total_score"]) < 1e-6,
            f"now {m['total_score']:.4f} vs recorded {R['market']['total_score']:.4f}")
        ev = sorted(config.EVIDENCE_DIR.glob("*.json"))
        add("Evidence log present", len(ev) > 0, f"{len(ev)} run records in artifacts/evidence/")
        out = {"passed": sum(c["pass"] for c in checks), "total": len(checks), "checks": checks}
        out["evidence_id"] = log_evidence("sdk_verify", {"backend": "QpiAI QCloud SDK + QpiAI Opt", **out,
                                                         "summary": f"SDK verify: {out['passed']}/{out['total']} checks passed"})
        return out

    def _data(self):
        if self._ds is None:
            self._ds = load_snapshots()
        return self._ds

    # ------------------------------------------------------------------ everything
    def demo(self) -> dict:
        report = {"generated": time.strftime("%Y-%m-%d %H:%M:%S")}
        for name, fn in (("status", self.status), ("kernel", self.kernel), ("train_qubo_svm", self.train_qubo_svm),
                         ("screen", self.screen), ("allocate", self.allocate), ("qaoa", self.qaoa), ("match", self.match),
                         ("verify", self.verify)):
            t = time.time()
            try:
                report[name] = {"ok": True, **fn(), "wall_seconds": round(time.time() - t, 2)}
            except Exception as exc:          # report, don't hide
                report[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}", "wall_seconds": round(time.time() - t, 2)}
            print(f"  {name:15s} {'ok ' if report[name]['ok'] else 'FAILED'}  {report[name]['wall_seconds']:6.1f} s"
                  f"  {report[name].get('evidence_id') or ''}", flush=True)
        (config.ARTIFACTS / "sdk_report.json").write_text(json.dumps(report, indent=2, default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o)))
        return report


def _print(obj: Any) -> None:
    print(json.dumps(obj, indent=2, default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o)))


def main(argv: list[str]) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    cmd = argv[0] if argv else "status"
    sdk = CellfeeSDK()
    fns = {"status": sdk.status, "kernel": sdk.kernel, "train": sdk.train_qubo_svm, "screen": sdk.screen, "allocate": sdk.allocate,
           "qaoa": sdk.qaoa, "match": sdk.match, "verify": sdk.verify}
    if cmd == "demo":
        print("CELLFEE SDK demo: every step is a live QpiAI QCloud / QpiAI Opt run with an evidence record")
        r = sdk.demo()
        v = r.get("verify", {})
        print(f"verify: {v.get('passed', 0)}/{v.get('total', 0)} reproducibility checks passed · report: artifacts/sdk_report.json")
        return
    if cmd not in fns:
        print(__doc__)
        return
    _print(fns[cmd]())


if __name__ == "__main__":
    main(sys.argv[1:])
