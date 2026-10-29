"""AQSVC: annealing-based quantum support vector classifier (QpiAI QCloud kernel + QpiAI Opt training).

Two quantum ingredients, one per sponsor tool:
  * Kernel  k(x, x') = |<0|U(x')^dagger U(x)|0>|^2 from the QpiAI feature-map circuit (quantum_kernel.py).
  * Training: the SVM dual problem is written as a QUBO and solved by QpiAI Opt's annealer
    (formulation of Willsch, Willsch, De Raedt & Michielsen, Comput. Phys. Commun. 248, 107006, 2020):

        alpha_n = sum_k B^k a_{n,k}                          a_{n,k} binary, K bits per sample
        E(a) = 1/2 sum_{n,m} alpha_n alpha_m y_n y_m k(x_n, x_m)  -  sum_n alpha_n
               + xi/2 (sum_n alpha_n y_n)^2                  (penalty replaces the equality constraint)

    bias  b = sum_n alpha_n (C - alpha_n) [y_n - sum_m alpha_m y_m k_nm] / sum_n alpha_n (C - alpha_n),
    C = sum_k B^k;  decision f(x) = sum_n alpha_n y_n k(x_n, x) + b.

A QUBO with N samples has N*K binary variables, so each member is trained on a small balanced subset
(AQSVC_SUBSET batteries). The ensemble combines four techniques (models.train_quantum):
  * bagging   - AQSVC_BAG members on balanced random subsets;
  * boosting  - AQSVC_BOOST more members on subsets re-weighted towards the snapshots the bagged members get wrong;
  * heterogeneous models - the same on two quantum feature maps (8 inputs and 7 inputs, each tuned for held-out accuracy);
  * stacking  - a logistic-regression meta-learner over all member margins, fitted on out-of-bag margins,
                gives the probability; the plain vote share is kept alongside as the voting view.
"""

from __future__ import annotations

import time

import numpy as np

from . import config
from .sponsors import log_evidence, opt_assignment, opt_client

OPT_BUDGET = 9_500_000   # QpiAI Opt free local annealing work units per solve (limit 10M)


def build_qubo_model(K: np.ndarray, y: np.ndarray, bits: int = config.AQSVC_BITS, base: int = config.AQSVC_BASE,
                     xi: float = config.AQSVC_XI):
    """The SVM dual as a QpiAI Opt Model (binary encoding of alpha)."""
    from qpiai_opt.opt_modeller import Binary, Model, quicksum

    n = len(y)
    a = [[Binary(f"a_{i}_{k}") for k in range(bits)] for i in range(n)]
    w = [base ** k for k in range(bits)]
    Q = 0.5 * (np.outer(y, y) * K + xi * np.outer(y, y))
    m = Model("cellfee_aqsvc")
    # symmetric terms folded onto i <= j (same energy, half the terms)
    quad = quicksum(float((1 if i == j else 2) * Q[i, j] * w[k] * w[l]) * a[i][k] * a[j][l]
                    for i in range(n) for j in range(i, n) for k in range(bits) for l in range(bits))
    lin = quicksum(float(w[k]) * a[i][k] for i in range(n) for k in range(bits))
    m.minimize(quad - lin)
    return m


def qubo_matrix(K: np.ndarray, y: np.ndarray, bits: int = config.AQSVC_BITS, base: int = config.AQSVC_BASE,
                xi: float = config.AQSVC_XI) -> np.ndarray:
    """Dense upper-form QUBO matrix of the same energy (used for the no-key fallback and energies)."""
    n = len(y)
    w = np.array([base ** k for k in range(bits)], float)
    Q = 0.5 * (np.outer(y, y) * K + xi * np.outer(y, y))
    M = np.kron(Q, np.outer(w, w))
    M[np.diag_indices_from(M)] -= np.tile(w, n)
    return M


def decode(bits_vec: np.ndarray, n: int, bits: int = config.AQSVC_BITS, base: int = config.AQSVC_BASE) -> np.ndarray:
    return bits_vec.reshape(n, bits) @ np.array([base ** k for k in range(bits)], float)


def bias(alpha: np.ndarray, K: np.ndarray, y: np.ndarray, C: float) -> float:
    w = alpha * (C - alpha)
    resid = y - K @ (alpha * y)
    if w.sum() > 1e-12:
        return float((w * resid).sum() / w.sum())
    sv = alpha > 0
    return float(resid[sv].mean()) if sv.any() else 0.0


def _anneal(M: np.ndarray, reads: int, sweeps: int, rng) -> np.ndarray:
    """Plain simulated annealing on x^T M x (fallback when no QpiAI Opt key is configured)."""
    S = (M + M.T) / 2
    diag, off = np.diag(S).copy(), S - np.diag(np.diag(S))
    best, best_e = None, np.inf
    temps = np.geomspace(max(np.abs(S).max(), 1.0) * 2, 1e-3, sweeps)
    for _ in range(reads):
        x = rng.integers(0, 2, len(S)).astype(float)
        field = off @ x
        for T in temps:
            for k in rng.permutation(len(S)):
                d = (1 - 2 * x[k]) * (diag[k] + 2 * field[k])
                if d < 0 or rng.random() < np.exp(-d / T):
                    x[k] = 1 - x[k]
                    field += off[:, k] * (2 * x[k] - 1)
        e = x @ S @ x
        if e < best_e:
            best, best_e = x.copy(), e
    return best


def train_member(K: np.ndarray, y: np.ndarray, seed: int, client=None) -> dict:
    """One AQSVC member: QUBO on QpiAI Opt's local annealer (or the built-in annealer without a key)."""
    n, bits = len(y), config.AQSVC_BITS
    M = qubo_matrix(K, y)
    nv = n * bits
    pairs = nv * (nv - 1) // 2
    reads = config.AQSVC_READS
    sweeps = int(max(50, min(3000, OPT_BUDGET / reads // (nv + 2 * pairs + nv))))
    t0 = time.time()
    solver, info = "built-in simulated annealing (no QpiAI Opt key)", None
    x = None
    if client is not None:
        from qpiai_opt.opt_solvers import solve

        try:
            model = build_qubo_model(K, y)
            res = solve(model, client=client, num_reads=reads, num_sweeps=sweeps, seed=seed)
            sol = opt_assignment(res, model)
            x = np.array([sol.get(f"a_{i}_{k}", 0.0) for i in range(n) for k in range(bits)], float)
            solver, info = "QpiAI Opt local QUBO annealer", str(res.info())[:600]
        except Exception as exc:
            info = f"QpiAI Opt failed ({str(exc)[:200]}); used built-in annealer"
    if x is None:
        x = _anneal(M, reads, sweeps, np.random.default_rng(seed))
    alpha = decode(x, n)
    C = float(sum(config.AQSVC_BASE ** k for k in range(bits)))
    return {"alpha": alpha, "b": bias(alpha, K, y, C), "energy": float(x @ M @ x), "solver": solver,
            "reads": reads, "sweeps": sweeps, "qubo_vars": nv, "seconds": round(time.time() - t0, 2), "info": info}


def balanced_subsets(y: np.ndarray, members: int, size: int, seed: int, weights: np.ndarray | None = None) -> list[np.ndarray]:
    """Balanced training subsets (half fit, half not fit). With weights, rows are drawn in proportion to them (boosting)."""
    rng = np.random.default_rng(seed)
    pos, neg = np.where(y == 1)[0], np.where(y == 0)[0]
    h = size // 2
    pp = None if weights is None else weights[pos] / weights[pos].sum()
    pn = None if weights is None else weights[neg] / weights[neg].sum()
    return [np.concatenate([rng.choice(pos, h, replace=False, p=pp), rng.choice(neg, h, replace=False, p=pn)])
            for _ in range(members)]


_CLIENT = None


def _worker_init():
    global _CLIENT
    _CLIENT = opt_client()


def _solve_job(job):
    K, ys, seed = job
    return train_member(K, ys, seed=seed, client=_CLIENT)


class Ensemble:
    """Kernel SVMs over one precomputed quantum kernel: bagging, then boosting.

    Bagging  : `bag` members on balanced random subsets.
    Boosting : `boost` more members whose subsets are drawn with AdaBoost-style weights exp(-1.5 * y * F), where F is
               the bagged members' mean margin on every training snapshot, so later members concentrate on the
               snapshots the first round gets wrong or nearly wrong.
    `solver` = 'opt' trains every member as a QUBO on QpiAI Opt (AQSVC, members solved in parallel worker processes);
    'classical' solves the same dual with sklearn SVC (the C1 baseline that isolates the annealer's effect)."""

    def __init__(self, solver: str = "opt", bag: int = config.AQSVC_BAG, boost: int = config.AQSVC_BOOST,
                 size: int = config.AQSVC_SUBSET, seed: int = config.SEED):
        self.solver, self.bag, self.boost, self.size, self.seed = solver, bag, boost, size, seed

    def _train(self, kernel_fn, y01: np.ndarray, subsets: list[np.ndarray], log=None, stage: str = "") -> None:
        jobs = [(kernel_fn(idx, idx), np.where(y01[idx] == 1, 1.0, -1.0), self.seed + len(self.members) + k)
                for k, idx in enumerate(subsets)]
        if self.solver == "opt":
            from concurrent.futures import ProcessPoolExecutor
            with ProcessPoolExecutor(config.AQSVC_WORKERS, initializer=_worker_init) as pool:
                results = list(pool.map(_solve_job, jobs))
        for k, (idx, (K, ys, _)) in enumerate(zip(subsets, jobs)):
            if self.solver == "opt":
                r = results[k]
                alpha, b = r["alpha"], r["b"]
                self.runs.append({kk: r[kk] for kk in ("solver", "energy", "reads", "sweeps", "qubo_vars", "seconds", "info")}
                                 | {"support_vectors": int((alpha > 0).sum()), "stage": stage})
            else:
                from sklearn.svm import SVC

                C = float(sum(config.AQSVC_BASE ** j for j in range(config.AQSVC_BITS)))
                svc = SVC(kernel="precomputed", C=C).fit(K, ys)
                alpha = np.zeros(len(idx))
                alpha[svc.support_] = np.abs(svc.dual_coef_[0])
                b = float(svc.intercept_[0])
            keep = alpha > 0
            self.members.append({"idx": idx[keep], "coef": (alpha * ys)[keep], "b": b, "subset": idx, "stage": stage})
        if log and self.solver == "opt" and self.runs:
            log(f"    AQSVC {stage}: {len(subsets)} QUBOs on {sorted({r['solver'] for r in self.runs})[0]}, "
                f"mean {np.mean([r['seconds'] for r in self.runs[-len(subsets):]]):.1f} s each")

    def fit(self, kernel_fn, y01: np.ndarray, log=None) -> "Ensemble":
        """kernel_fn(idx_a, idx_b) -> kernel block between training rows idx_a and idx_b."""
        self.members, self.runs = [], []
        self._train(kernel_fn, y01, balanced_subsets(y01, self.bag, self.size, self.seed), log, "bagging")
        if self.boost:
            rows = np.arange(len(y01))
            F = self.decision(lambda idx: kernel_fn(rows, idx)).mean(axis=0)
            w = np.exp(-1.5 * np.clip(np.where(y01 == 1, 1.0, -1.0) * F, -3, 3))
            self._train(kernel_fn, y01, balanced_subsets(y01, self.boost, self.size, self.seed + 1000, weights=w), log, "boosting")
        return self

    def support_rows(self) -> np.ndarray:
        return np.unique(np.concatenate([m["idx"] for m in self.members])) if self.members else np.array([], int)

    def decision(self, kernel_to_rows) -> np.ndarray:
        """kernel_to_rows(idx) -> kernel block (n_eval, len(idx)). Returns (members, n_eval) margins."""
        return np.array([kernel_to_rows(m["idx"]) @ m["coef"] + m["b"] for m in self.members])

    def out_of_bag(self, kernel_to_rows, n_rows: int) -> np.ndarray:
        """Training margins with each member's own subset masked (replaced by the other members' mean margin), so the
        stacking meta-learner never learns from a member grading its own training data."""
        M = self.decision(kernel_to_rows)
        for k, m in enumerate(self.members):
            M[k, m["subset"]] = np.nan
        return np.where(np.isnan(M), np.nanmean(M, axis=0), M)

    def predict_proba(self, kernel_to_rows) -> np.ndarray:
        """Share of members voting 'fit for second life' (hard vote)."""
        return (self.decision(kernel_to_rows) > 0).mean(axis=0)


class Stack:
    """Stacking: a logistic-regression meta-learner over every member margin of every quantum feature map.
    It learns how much to trust each member (and each map) from out-of-bag training margins."""

    def fit(self, margins_oob: np.ndarray, y01: np.ndarray) -> "Stack":
        from sklearn.linear_model import LogisticRegression

        self.lr = LogisticRegression(C=config.AQSVC_STACK_C, max_iter=5000).fit(margins_oob.T, y01)
        self.coef, self.intercept = self.lr.coef_[0], float(self.lr.intercept_[0])
        return self

    def predict_proba(self, margins: np.ndarray) -> np.ndarray:
        return 1 / (1 + np.exp(-(self.coef @ margins + self.intercept)))


def evidence(runs: list[dict], label: str) -> str:
    solvers = sorted({r["solver"] for r in runs})
    return log_evidence("aqsvc_training", {
        "backend": "QpiAI Opt (QUBO) + QpiAI QCloud feature-map kernel", "label": label, "members": runs,
        "summary": f"{len(runs)} AQSVC members trained as QUBOs ({', '.join(solvers)}), "
                   f"{runs[0]['qubo_vars'] if runs else 0} binary variables each"})
