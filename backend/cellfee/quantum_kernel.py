"""Quantum feature map + fidelity quantum kernel, built and run with QpiAI QCloud SDK.

Feature map U(x; theta) on n qubits (one qubit per battery feature), L layers:

    for each layer:
        RY(q, s_q * x_q)                       data re-uploading, trainable scale s_q
        RZ(q, s_q * x_q)
        RZZ(q, q+1, g * x_q * x_{q+1})         entangling, trainable strength g (ring)

Kernel  k(x, x') = |<0| U(x')^dagger U(x) |0>|^2   (state fidelity, in [0, 1]).

Three ways it is evaluated, all on the same circuit definition:
  * qpiai_statevectors(): QpiAI SDK circuits on QpiAI-QSV-Local, exact statevectors
    (n circuits for n batteries; kernel = Gram matrix of overlaps).
  * fidelity_test_kernel(): the compute-uncompute circuit U(x) U(x')^dagger with
    measurements, executed shot-by-shot on QCloud (QSV-Local, cloud simulators or
    QpiAI-Indus-1); k = P(all zeros). This is the hardware-ready path.
  * numpy_statevectors(): a vectorised NumPy twin used only inside the training
    loop for speed; checked against the QpiAI SDK to numerical precision.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import minimize

from . import config
from .sponsors import log_evidence, run_circuit


@dataclass
class FeatureMapParams:
    n_qubits: int
    layers: int = 2
    scales: np.ndarray = field(default=None)  # per-qubit s_q
    entangle: float = 0.5                      # g

    def __post_init__(self):
        if self.scales is None:
            self.scales = np.ones(self.n_qubits)
        self.scales = np.asarray(self.scales, dtype=float)

    def vector(self) -> np.ndarray:
        return np.concatenate([self.scales, [self.entangle]])

    @classmethod
    def from_vector(cls, v: np.ndarray, layers: int) -> "FeatureMapParams":
        return cls(n_qubits=len(v) - 1, layers=layers, scales=np.asarray(v[:-1]), entangle=float(v[-1]))

    def to_dict(self) -> dict:
        return {"n_qubits": self.n_qubits, "layers": self.layers,
                "scales": self.scales.round(4).tolist(), "entangle": round(self.entangle, 4)}


def _pairs(n: int) -> list[tuple[int, int]]:
    return [(q, (q + 1) % n) for q in range(n)] if n > 2 else [(0, 1)]


# ----------------------------------------------------------------------------- QpiAI SDK
def build_feature_map_circuit(x: np.ndarray, p: FeatureMapParams):
    """Return a QpiAI Circuit implementing U(x; theta)."""
    from qpiai_quantum import Circuit

    n = p.n_qubits
    c = Circuit(n, name="cellfee_feature_map")
    for _ in range(p.layers):
        for q in range(n):
            c.ry(q, float(p.scales[q] * x[q]))
        for q in range(n):
            c.rz(q, float(p.scales[q] * x[q]))
        for a, b in _pairs(n):
            c.rzz(a, b, float(p.entangle * x[a] * x[b]))
    return c


def qpiai_statevectors(X: np.ndarray, p: FeatureMapParams) -> np.ndarray:
    """Exact statevectors from the QpiAI SDK local statevector simulator."""
    out = np.empty((len(X), 2 ** p.n_qubits), dtype=complex)
    for i, x in enumerate(X):
        res = build_feature_map_circuit(x, p).run(
            shots=1, device_name="QpiAI-QSV-Local", need_statevector=True,
            experiment_name="cellfee-feature-map")
        out[i] = np.asarray(res.statevector, dtype=complex)
    return out


def kernel_from_states(A: np.ndarray, B: np.ndarray) -> np.ndarray:
    return np.abs(A.conj() @ B.T) ** 2


def fidelity_test_kernel(pairs: list[tuple[int, int]], X: np.ndarray, p: FeatureMapParams,
                         device: str | None = None, shots: int | None = None) -> dict:
    """Shot-based compute-uncompute circuits on QpiAI QCloud. Returns values + evidence."""
    from qpiai_quantum import Circuit

    device = device or config.KERNEL_DEVICE
    shots = shots or config.KERNEL_SHOTS
    requested, notes = device, []
    n = p.n_qubits
    zeros = "0" * n
    values, job_ids, started = [], [], time.time()
    for i, j in pairs:
        c = Circuit(n, n, name=f"cellfee_kernel_{i}_{j}")
        c.compose(build_feature_map_circuit(X[i], p))
        c.compose(build_feature_map_circuit(X[j], p).inverse())
        c.measure(list(range(n)), list(range(n)))
        res, device, note = run_circuit(c, shots, device)
        if note and note not in notes:
            notes.append(note)
        counts = res.get_counts() if hasattr(res, "get_counts") else res.counts
        values.append(counts.get(zeros, 0) / shots)
        jid = getattr(res, "job_id", None)
        if jid:
            job_ids.append(jid)
    run_id = log_evidence("quantum_kernel_fidelity_test", {
        "backend": "QpiAI QCloud SDK", "device": device, "shots": shots,
        "n_qubits": n, "feature_map": p.to_dict(), "pairs": pairs, "kernel_values": values,
        "job_ids": job_ids, "seconds": round(time.time() - started, 2),
        "requested_device": requested, "notes": notes,
        "summary": f"{len(pairs)} fidelity-test circuits on {device}"})
    return {"device": device, "requested_device": requested, "notes": notes, "shots": shots,
            "values": values, "job_ids": job_ids, "run_id": run_id}


# ----------------------------------------------------------------------------- NumPy twin
def _z_table(n: int) -> np.ndarray:
    idx = np.arange(2 ** n)
    return np.array([1 - 2 * ((idx >> q) & 1) for q in range(n)])  # (n, 2^n), qubit q -> bit q (LSB)


def numpy_statevectors(X: np.ndarray, p: FeatureMapParams) -> np.ndarray:
    n, N = p.n_qubits, len(X)
    Z = _z_table(n)
    psi = np.zeros((N, 2 ** n), dtype=complex)
    psi[:, 0] = 1.0
    ang = X * p.scales  # (N, n)
    zz_pairs = _pairs(n)
    for _ in range(p.layers):
        for q in range(n):
            psi = _apply_ry(psi, q, n, ang[:, q])
        phase = -0.5 * (ang @ Z)  # RZ on all qubits (diagonal)
        for a, b in zz_pairs:
            phase += -0.5 * (p.entangle * X[:, a] * X[:, b])[:, None] * (Z[a] * Z[b])[None, :]
        psi = psi * np.exp(1j * phase)
    return psi


def _apply_ry(psi: np.ndarray, q: int, n: int, theta: np.ndarray) -> np.ndarray:
    N = psi.shape[0]
    t = psi.reshape(N, 2 ** (n - q - 1), 2, 2 ** q)
    c, s = np.cos(theta / 2)[:, None, None], np.sin(theta / 2)[:, None, None]
    a0, a1 = t[:, :, 0, :], t[:, :, 1, :]
    out = np.empty_like(t)
    out[:, :, 0, :] = c * a0 - s * a1
    out[:, :, 1, :] = s * a0 + c * a1
    return out.reshape(N, -1)


# ----------------------------------------------------------------------------- training
def centered_alignment(K: np.ndarray, y: np.ndarray) -> float:
    """Centered kernel-target alignment between K and the label kernel y y^T."""
    n = len(y)
    H = np.eye(n) - 1.0 / n
    Kc = H @ K @ H
    yc = y - y.mean()
    Y = np.outer(yc, yc)
    return float(np.sum(Kc * Y) / (np.linalg.norm(Kc) * np.linalg.norm(Y) + 1e-12))


def train_feature_map(X: np.ndarray, y: np.ndarray, n_layers: int = 2, seed: int = config.SEED) -> dict:
    """Learn feature-map parameters by maximising kernel-target alignment (QML training)."""
    n = X.shape[1]
    rng = np.random.default_rng(seed)
    history: list[float] = []

    def loss(v):
        p = FeatureMapParams.from_vector(v, n_layers)
        K = kernel_from_states(*(2 * [numpy_statevectors(X, p)]))
        a = centered_alignment(K, y)
        history.append(a)
        return -a

    init = FeatureMapParams(n_qubits=n, layers=n_layers, scales=np.full(n, 0.6), entangle=0.3)
    best = None
    for start in [init.vector(), np.concatenate([rng.uniform(0.2, 1.2, n), [rng.uniform(0, 0.8)]])]:
        r = minimize(loss, start, method="L-BFGS-B", bounds=[(0.02, 2.5)] * n + [(0.0, 2.0)],
                     options={"maxiter": 60})
        if best is None or r.fun < best.fun:
            best = r
    p = FeatureMapParams.from_vector(best.x, n_layers)
    untrained = centered_alignment(kernel_from_states(*(2 * [numpy_statevectors(X, init)])), y)
    return {"params": p, "alignment_trained": -float(best.fun), "alignment_untrained": untrained,
            "history": history[:: max(1, len(history) // 60)]}


def tune_feature_map(Xa: np.ndarray, y01: np.ndarray, rows: np.ndarray, cells: np.ndarray, n_layers: int = 2,
                     seed: int = config.SEED, n_random: int = 40, n_refine: int = 40, C: float = 3.0) -> dict:
    """Feature-map parameters chosen for held-out accuracy (the AQSVC classifier's map).

    Training cells are split by cell into fit / validation parts (a quarter of the cells validate); each candidate
    (per-qubit scales s and entangling g) builds the quantum kernel, a kernel SVM is fitted on the fit part and scored
    on the validation cells. Random search, then a shrinking random-step refinement. The SVM here is the classical
    solver of the same dual problem, used only to score candidates quickly; the deployed members are trained as QUBOs."""
    from sklearn.svm import SVC

    rng = np.random.default_rng(seed)
    cell_rows = cells[rows]
    uc = np.unique(cell_rows)
    val_cells = set(rng.choice(uc, max(1, len(uc) // 4), replace=False).tolist())
    is_val = np.array([c in val_cells for c in cell_rows])
    a = rng.choice(rows[~is_val], min(1500, int((~is_val).sum())), replace=False)
    b = rng.choice(rows[is_val], min(1200, int(is_val.sum())), replace=False)
    ya, yb = np.where(y01[a] == 1, 1.0, -1.0), np.where(y01[b] == 1, 1.0, -1.0)
    n = Xa.shape[1]
    history: list[float] = []

    def score(v):
        p = FeatureMapParams.from_vector(v, n_layers)
        Sa, Sb = numpy_statevectors(Xa[a], p), numpy_statevectors(Xa[b], p)
        m = SVC(kernel="precomputed", C=C).fit(kernel_from_states(Sa, Sa), ya)
        acc = float(np.mean(np.sign(m.decision_function(kernel_from_states(Sb, Sa))) == yb))
        history.append(acc)
        return acc

    best_v, best = None, -1.0
    for _ in range(n_random):
        v = np.concatenate([rng.uniform(0.05, 1.5, n), [rng.uniform(0.0, 1.0)]])
        s = score(v)
        if s > best:
            best_v, best = v, s
    step = 0.3
    for _ in range(n_refine):
        v = np.clip(best_v + rng.normal(0, step, len(best_v)), 0.0, 2.5)
        s = score(v)
        if s >= best:
            best_v, best = v, s
        else:
            step *= 0.97
    return {"params": FeatureMapParams.from_vector(best_v, n_layers), "validation_accuracy": best,
            "history": history, "validation_cells": len(val_cells)}


def verify_twin(X: np.ndarray, p: FeatureMapParams) -> float:
    """Max |K_numpy - K_qpiai| on a sample: proves the training twin equals the QpiAI circuit."""
    a = numpy_statevectors(X, p)
    b = qpiai_statevectors(X, p)
    return float(np.max(np.abs(kernel_from_states(a, a) - kernel_from_states(b, b))))
