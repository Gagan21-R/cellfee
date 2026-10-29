# QpiAI technology in CELLFEE: rubric A1–A3, with commands and recorded evidence

Every number below comes from a recorded run in `artifacts/` (pipeline run of 2026-10-30 and the SDK demo).
Re-run any of it with the commands in **A3**. No quantum advantage is claimed: circuits run on QpiAI's local
statevector simulator (QpiAI-QSV-Local), which is classical simulation, and the QpiAI Opt solves run locally.

## A1. Product choice and domain integration

| Domain decision | QpiAI component | Inputs → outputs (and where they go) |
|---|---|---|
| Is a used battery fit for second life (≥ 300 more cycles)? | **QpiAI QCloud SDK** feature-map circuits → quantum kernel; **QpiAI Opt** trains each SVM as a QUBO | 7 screening features of a real battery snapshot → `p_aqsvc` (AQSVC probability). It is combined with XGBoost into the grade (A/B/T/C) and the decision value of every battery. |
| Which cells may share a pack? | **QpiAI QCloud** kernel similarity `k(i,j)` | Pairs with similarity < 0.15 are forbidden in the same pack, and the mismatch cost uses `1 − k`. This feeds the allocation model. |
| Reuse / test / recycle + which pack, for each truckload | **QpiAI Opt** modeller + exact MILP and QUBO annealer (HiGHS re-solves as an independent reference) | Probabilities, health and kernel → actions and packs for 5,000 batteries in 152 batches. These drive the dashboard decisions and the fleet value in ₹. |
| Balancing two packs | **QpiAI QCloud** circuits: XY-mixer QAOA on the QUBO built with the QpiAI Opt modeller | 8 reuse cells → a balanced 4+4 split. |
| Buyer ↔ pack matching | **QpiAI Opt** assignment model | Compatibility scores → one-to-one matches on the Marketplace tab. |

Validated outcome (grouped 5-fold cross-validation by cell, 8,753 real snapshots from 124 cells, Severson et al. 2019):

| Model | Accuracy | AUC | False-fit rate |
|---|---|---|---|
| **AQSVC (quantum: QpiAI kernel + QpiAI Opt QUBOs)** | **95.06%** | 0.990 | 5.9% |
| XGBoost (classical) | 94.95% | 0.992 | 4.4% |
| Both together (CELLFEE grade) | **95.64%** | 0.993 | 4.6% |
| C1: same quantum maps and ensemble, classical SVM solver | 94.87% | 0.989 | 5.6% |

The two models agree on 95.5% of snapshots and are right 97.1% of the time when they do. The 390 disagreements are
sent to a lab test.

## A2. Technical formulation

**QpiAI QCloud (`quantum_kernel.py`, `qaoa.py`)**
- Feature map `U(x; θ)`, one qubit per input, 2 layers of `RY(s_q x_q) → RZ(s_q x_q) → ring RZZ(g x_q x_{q+1})`.
  Fidelity kernel `k(x, x') = |⟨0|U(x')†U(x)|0⟩|²`.
- Three evaluation paths, all on the same circuit definition:
  - exact QpiAI SDK statevectors;
  - shot-based compute-uncompute circuits `U(x)U(x')†` measured on `QpiAI-QSV-Local` (k = P(0…0));
  - a NumPy twin used inside training, checked equal to the SDK (max kernel difference 3.6×10⁻¹⁵).
- AQSVC uses two classifier maps: 8 qubits (7 features + cycles-to-80% estimate) and 7 qubits.
  - Inputs are rank-encoded to angles.
  - Scales are tuned for held-out accuracy on training cells only, never on the test fold.
- The pack-similarity map (7 qubits) is trained by kernel-target alignment.
- QAOA: p = 3, XY mixer (keeps 4+4 valid), CVaR objective.
  - Optimal-split probability 6.5%, vs 2.9% for a random guess.
  - Approximation ratio 1.0.

**QpiAI Opt (`aqsvc.py`, `allocation.py`, `market.py`)**
- SVM dual as a QUBO (Willsch et al. 2020):
  - encoding `α_n = Σ_k 2^k a_{n,k}`;
  - energy `E = ½ Σ α_n α_m y_n y_m k_nm − Σ α_n + ξ/2 (Σ α_n y_n)²`;
  - 40 batteries × 2 bits = 80 binary variables per SVM, solved on QpiAI Opt's local QUBO annealer.
- **600 QUBOs** were solved in this run: 100 per model × 5 folds + the deployed model.
- The ensemble combines four techniques:
  - **bagging**: 25 SVMs per map on balanced subsets;
  - **boosting**: 25 more per map on re-weighted subsets;
  - **heterogeneous maps**: the 8-qubit and 7-qubit maps;
  - **stacking**: a logistic meta-learner on out-of-bag margins.
  The fold-by-fold gain is shown on the dashboard (Quantum ML tab): the plain vote reaches 92.3% and stacking 95.1%.
- Fleet allocation:
  - binary actions and pack-assignment variables with capacity, pack-size and forbidden-pair constraints, built with the QpiAI Opt modeller;
  - solved exactly by QpiAI Opt's MILP solver on all 152 batches;
  - HiGHS re-solves the first 10, and the objectives match.
  - The same model is also compiled to a QUBO (168 variables for batch 1) and run on the annealer.
- Market matching: a one-to-one assignment, binary, solved by QpiAI Opt.

## A3. Working implementation, recorded evidence, reproducibility

**CELLFEE SDK** (`backend/cellfee/sdk.py`). Each command makes live QpiAI calls and writes an evidence record:

```bash
cd backend
python -m cellfee.sdk status      # QpiAI SDK version, keys configured (never printed), devices
python -m cellfee.sdk kernel      # QpiAI circuits: exact vs 2,000-shot fidelity estimate
python -m cellfee.sdk train       # one AQSVC member as an 80-variable QUBO on QpiAI Opt
python -m cellfee.sdk screen      # deployed XGBoost + AQSVC (QpiAI circuits, 100 QUBO-trained SVMs)
python -m cellfee.sdk allocate    # QpiAI Opt exact MILP + QUBO annealer on batch 1, HiGHS reference
python -m cellfee.sdk qaoa        # QAOA pack balancing on QpiAI circuits
python -m cellfee.sdk match       # QpiAI Opt buyer-pack matching
python -m cellfee.sdk verify      # reproducibility checks against the recorded results
python -m cellfee.sdk demo        # all of the above -> artifacts/sdk_report.json
```

`verify` (latest run: **7 / 7 passed**):

| Check | Result |
|---|---|
| QpiAI SDK kernel reproduces the recorded batch-1 kernel | max difference 2.3×10⁻⁴ (stored to 4 decimals) |
| NumPy training twin equals the QpiAI SDK circuit | 2.7×10⁻¹⁵ |
| Shot-based fidelity circuits agree with exact overlaps | mean error 0.0066 (60 circuits × 2,000 shots) |
| QpiAI Opt re-solves batch 1 to the recorded objective | ₹515.818 vs ₹515.822 recorded (kernel stored to 4 decimals) |
| QpiAI Opt exact MILP matches HiGHS | 515.818164 = 515.818164 |
| QpiAI Opt market matching reproduces the recorded score | 4.6424 = 4.6424 |
| Evidence log present | ≥ 150 run records |

**Evidence:**
- Every QpiAI QCloud / QpiAI Opt run is written to `artifacts/evidence/<run_id>.json`. Each record holds the backend, device, settings, job IDs (cloud runs) and outputs.
- The records are listed on the dashboard's **Evidence log** tab.
- Full rebuild: `python -m cellfee.pipeline --retrain` (about 70 min). It regenerates `results.json`, the deployed models and the evidence.

**Honest limits:**
- **Free-tier annealer is weaker on a single QUBO.** QpiAI Opt's local annealer runs on a free-tier work budget, about 4 reads per QUBO. On the SDK's single-member check it reached energy −6.76, where CELLFEE's built-in annealer reached −9.00 on the same matrix. That member's held-out accuracy was 83.6%, vs 86.0% for the exact classical solution. The ensemble absorbs this: the C1 classical-solver version scores 94.9% and AQSVC 95.1%.
- **Annealer vs MILP on allocation.** On the 168-variable allocation QUBO, the annealer's objective is far below the exact MILP's (201 vs 516). The exact QpiAI Opt MILP therefore makes the decisions, and the annealer result is reported for comparison.
- **One map has no entanglement.** Tuning chose entangling strength g = 0 for the 8-qubit classifier map, so that kernel is a product of single-qubit kernels. The 7-qubit map keeps entanglement (g ≈ 0.13), and so does the pack-similarity map. Accuracy, not entanglement, was the tuning target.
- **Simulator only.** No cloud QPU job was run. With a QCloud subscription, `CELLFEE_KERNEL_DEVICE` / `CELLFEE_QAOA_DEVICE` send the same circuits to QpiAI cloud simulators or QpiAI-Indus-1. If the cloud refuses a job, the fallback to QSV-Local is recorded in the evidence.
