# CELLFEE — Quantum-assisted second-life intelligence for used EV batteries

**Live app:** https://cellfee.onrender.com (dashboard: https://cellfee.onrender.com/dashboard/; free hosting, so the first visit after a quiet spell takes about a minute to wake up)
**Demo video (5:41):** https://github.com/Gagan21-R/cellfee/releases/download/demo-video/CELLFEE_demo_1080p.mp4
**QpiAI rubric, evidence and SDK:** [docs/QPIAI_JUDGING.md](docs/QPIAI_JUDGING.md)

> **Two models judge every battery side by side: XGBoost (classical) and AQSVC (quantum, built on QpiAI QCloud +
> QpiAI Opt). Where they agree, CELLFEE acts; where they disagree, it tests. QpiAI Opt turns that into a safe,
> valuable reuse plan.**

CELLFEE screens used batteries from their recent test log, asks both models whether each battery still has a long
life ahead, grades it A/B/T/C, decides **reuse / full test / recycle** for the whole fleet, builds matched
second-life packs, balances them with QAOA, matches packs to buyers, and estimates the environmental trade-off.
Users can **upload their own test results in any common format** (CSV, Excel, JSON, PDF, Word, or a photo / scan) and download
plain-language **PDF / JSON reports**. A **buy & sell marketplace** lets owners list used EV batteries with their health report.
Every quantum and optimisation run is evidence-logged.

## The two models

| | XGBoost (classical) | AQSVC (quantum) |
|---|---|---|
| What it is | gradient-boosted trees (300 trees, depth 4) | annealing-based quantum support vector classifier |
| Kernel / features | 7 screening features | two QpiAI feature maps (RY, RZ, ring RZZ, 2 layers): 8 qubits (7 features + cycles-to-80% estimate) and 7 qubits; inputs rank-encoded to angles, scales tuned for accuracy on held-out training cells; fidelity kernel `k = \|⟨0\|U(x')†U(x)\|0⟩\|²` |
| Training | all training snapshots | each SVM's dual problem written as a QUBO (α in 2 binary bits) and solved on **QpiAI Opt's local annealer** (Willsch et al. 2020); per map 25 **bagged** SVMs on balanced 40-battery subsets + 25 **boosted** SVMs on re-weighted subsets (100 QUBOs per model) |
| Output | P(≥ 300 cycles left) | **stacking**: a logistic-regression meta-learner over all 100 SVM margins (fitted on out-of-bag margins); the plain vote share is reported alongside |
| Runs | on every battery | on every battery, **at the same time** as XGBoost (two threads) |

AQSVC formulation, per SVM with N = 40 batteries and K = 2 bits:

```
α_n = Σ_k 2^k a_{n,k}           a ∈ {0,1}^{N·K}  → 80 binary variables
E(a) = ½ Σ_nm α_n α_m y_n y_m k(x_n,x_m) − Σ_n α_n + ξ/2 (Σ_n α_n y_n)²
b = Σ_n α_n(C−α_n)[y_n − Σ_m α_m y_m k_nm] / Σ_n α_n(C−α_n),   f(x) = Σ_n α_n y_n k(x_n,x) + b
```

```
real cycler data ─► 7 screening features ─┬─► XGBoost ───────────────────────────────┐
                                          └─► [QpiAI QCloud] 7-qubit kernel          │  both answers,
                                               └─► [QpiAI Opt] 100 SVM QUBOs ─► stack┘  side by side
                                                                                      ▼
   P(fit) = mean of both · agree / disagree · health · quantum similarity k(i,j)
                                                                                      ▼
            [QpiAI Opt] fleet QUBO / exact MILP (reuse/test/recycle + packs) ─► [QCloud] QAOA pack balance
                                                                                      ▼
   dashboard: both models · decisions · reasons · packs · uploads · PDF/JSON reports · marketplace · CO₂e · evidence
```

## Data — real, 8,753 samples

**Severson et al. (2019), *Nature Energy* 4, 383–391** — the MIT / Stanford / Toyota Research Institute fast-charging
dataset: **124 commercial A123 APR18650M1A LFP/graphite cells** (1.1 Ah), 72 fast-charge protocols, cycled at 30 °C
until they fell to 80% capacity — **100,501 real cycle records** (licence CC-BY-4.0, data.matr.io).

- `python -m cellfee.fetch_severson` reads only the small per-cycle `summary` struct of each cell from the original
  `.mat` files (HTTP range requests into the bit-exact mirror `huggingface.co/datasets/bsebench-org/severson-2019-raw`),
  so the 8 GB of raw time series is never downloaded. Cell exclusions and the five cells that continue across batches
  follow the authors' published loading notebook; cycle lives match the paper (e.g. b1c0 = 1,852).
- A **snapshot** is one battery at one moment, described only by its last ≤ 100 cycles: one every 10 cycles from cycle
  100 → **8,753 snapshots**. Label: *fit for second life* = at least **300 more cycles** before 80% capacity (58% fit).
- Features: health now, capacity lost / 100 cycles, internal resistance, resistance rise / 100 cycles, peak
  temperature, charge time, cycles done. The same code (`data.features_from_history`) runs on uploaded files.
- Evaluation is **5-fold cross-validation grouped by cell**: no cell is ever in both training and testing.

## The 5,000-battery fleet

The decision stage screens **5,000 battery records** drawn from all 124 cells, each judged by both models out-of-fold
(by models that never saw its cell). They arrive in **152 truckloads of ~33**, dealt so that no cell appears twice in a
truckload, and each truckload is one QpiAI Opt problem (reuse / test / recycle + 4-cell packs): QpiAI Opt's exact
MILP decides every batch, HiGHS re-solves the first 10 as an independent check, and the batch-1 QUBO also goes to
QpiAI Opt's annealer. The decision comparison on the *XGBoost vs AQSVC* page plans the same first 20 truckloads
(~650 batteries) with each model's answers (exact solves capped at 15 s, proven-optimal count recorded); all solves
run in 4 worker processes. One problem
over all 5,000 batteries would need millions of pack-pairing variables, and a hub decides one truckload at a time.
The dashboard lists all 5,000 (50 per page, with search, filters and sort); each passport is loaded on demand from
`/api/fleet/{id}` and downloads as PDF/JSON. The 3D story animates batch 1 (24 cells).

## Honest results

Grouped 5-fold cross-validation by cell (no cell is ever in both training and test):

| Model | Accuracy | AUC |
|---|---|---|
| AQSVC (quantum) | **95.06%** | 0.990 |
| XGBoost (classical) | 94.95% | 0.992 |
| Both together (CELLFEE grade) | **95.64%** | 0.993 |

AQSVC rose from 89.8% (25 voting SVMs on one kernel-alignment map) to 95.1%. Four changes did this:
- rank-encoded inputs and feature maps tuned for held-out accuracy;
- an engineered 8th input: cycles until 80% at the recent fade rate;
- boosting on top of bagging;
- two heterogeneous maps stacked by a meta-learner.

When the two models agree (95.5% of snapshots) they are right 97.1% of the time; disagreements go to a lab test.
**No quantum advantage is claimed.** The circuits run on QpiAI's local statevector simulator, which is classical
simulation, and the same ensemble solved classically (C1) scores 94.9%.
Fair baselines are included:
- XGBoost restricted to the snapshots AQSVC sees;
- a classical RBF-kernel SVM ensemble;
- the quantum ensemble with a classical solver.

See `docs/QPIAI_JUDGING.md` for the QpiAI rubric mapping, evidence and limits.

## CELLFEE SDK (QpiAI runs you can reproduce)

`python -m cellfee.sdk demo` (from `backend/`) runs every QpiAI-backed step live:
- QCloud kernel circuits;
- one AQSVC QUBO on QpiAI Opt;
- deployed screening;
- the QpiAI Opt fleet allocation with a HiGHS cross-check;
- QAOA;
- market matching;
- `verify`, which re-runs the recorded results and compares them (7/7 checks pass).

Each step writes an evidence record, and the demo writes `artifacts/sdk_report.json`.
Single steps: `python -m cellfee.sdk status | kernel | train | screen | allocate | qaoa | match | verify`.
From Python: `from cellfee.sdk import CellfeeSDK`.

## Usage baselines, risk factor, stop period and application confidence

After the reuse / test / recycle decision, every battery and pack gets a **usage baseline**: the limit after which it
must not be used further in a given application. Details and formulas: `docs/DECISION_RULES.md`, code: `backend/cellfee/usage.py`.

- **Registry** (`backend/cellfee/registry/applications.json`): 15 second-life applications (the original 4 plus home
  UPS, C&I peak shaving, EV charging buffer, microgrid, solar pumping, cold-chain, data-centre UPS, material handling,
  traffic/CCTV, emergency lighting, portable power). Skipped, with reasons: railway signalling, community grid support.
- **Baselines** (`backend/cellfee/registry/baselines.json`): test-pathway restrictions, Safe / Approaching / Stop-use
  margin, risk weights, low-confidence threshold. All are configured assumptions for an expert to review.
- **Stop period**: XGBoost quantile models (P10/P50/P90) of cycles until health falls below each floor. The out-of-fold
  P10–P90 band covered the truth 76–81% of the time.
- **Confidence**: XGBoost classifiers per requirement, with AUC 0.97–0.999 out-of-fold; values of 99.5% or more are shown as ">99%".
- **Risk factor**: on the training data, 0% of "Low", 20% of "Elevated" and 96% of "High" snapshots reached 80% health within 100 cycles.
- Tests: `cd backend; python -m tests.test_usage` and `cd frontend; node --test src/usageFormat.test.js`.

## Motion layer

`frontend/src/cellfee-motion.js` + `cellfee-motion.css`, loaded by one line in `main.jsx`. It explains each page with short,
one-shot animations of the real data: transform, opacity and stroke only, no layout shift, nothing under
`prefers-reduced-motion`. **Tuning in one place**: durations, easing and stagger are `--m-*` in `cellfee-motion.css` and
`MOTION` in `cellfee-motion.js`. The ticker speed is `--ticker-speed` (px/s). Debug: `window.__motion.replay('qml')`,
`window.__motion.disable()`, `window.__motion.enable()`.

## Upload your own test results

Dashboard → **Assess & upload**. Choose a file (Chrome/Edge open the picker in your Downloads folder), drop it on the box, or
pick one of the reports you downloaded here ("Screen this file"). Any file up to 10 MB is accepted: CSV / Excel / JSON test
data is read as a table; a PDF, Word file or photo / scan of a test report (JPEG, PNG, WEBP; read with OCR; the first OCR read
loads the model, and the server pre-warms it at start-up) has its values such as State of Health, internal resistance and
cycles picked out of the text, each shown with where it came from. Table layouts:

- **cycle log** — one row per cycle: `battery_id, cycle, discharge_capacity_ah, internal_resistance_ohm, temperature_max_c, charge_time_min`
- **summary** — one row per battery: `battery_id, soh, fade_100, ir_mohm, ir_rise_100, temp_max_c, charge_time_min, cycles`

Column names are matched flexibly; mAh, mΩ and seconds are detected; `rated_capacity_ah` sets a non-1.1 Ah rating.
Both models run on every battery at the same time; results can be downloaded as PDF/JSON (whole file or per battery),
and the last 5 uploads are remembered in the browser. `GET /api/upload/sample.csv` gives a real three-cell cycle log to try.
The models were trained on LFP 18650 cells, so results for other chemistries are indicative only.

## Quick start (Windows)

Already set up on this machine: Python 3.12 venv at `%USERPROFILE%\.venvs\cellfee`, frontend built.

```powershell
.\start.ps1          # story at http://127.0.0.1:8000 · dashboard at /dashboard/
.\run_pipeline.ps1   # fetch data (first time) + full pipeline (~60 min)
# re-run only the decision stage (reuses saved cross-validation and deployed models):
#   cd backend; python -m cellfee.pipeline --reuse-cv        (add --retrain to retrain the deployed models)
```

Fresh machine:

```powershell
py -3.12 -m venv $env:USERPROFILE\.venvs\cellfee
& $env:USERPROFILE\.venvs\cellfee\Scripts\python.exe -m pip install -r requirements.txt
cd frontend; npm install; npx vite build; cd ..
.\run_pipeline.ps1; .\start.ps1
```

## Sponsor keys & where things run

Per the hackathon mentors, everything runs **locally with your QpiAI API keys — no credits needed**.

1. `copy .env.example .env` and fill in `QPIAI_QCLOUD_API_KEY` and `QPIAI_OPT_API_KEY`. Keep `.env` private;
   `.env.example` must stay blank.
2. `.\run_pipeline.ps1`

| Stage | Runs on | Needs |
|---|---|---|
| AQSVC kernel circuits, fidelity tests, QAOA circuits | `QpiAI-QSV-Local` (QpiAI SDK simulator) | nothing |
| **AQSVC training** (100 SVM QUBOs per model, 600 per run) | **QpiAI Opt local QUBO annealer** | Opt key |
| Fleet allocation — **decision** | QpiAI Opt local **exact MILP** (cross-checked vs HiGHS) | Opt key |
| Fleet allocation — QUBO form | QpiAI Opt local annealer (reported as-is; free-tier budget) | Opt key |
| QpiAI Opt QAOA, marketplace matching | QpiAI local simulator / Opt local solver | keys |

With a QCloud subscription, set `CELLFEE_KERNEL_DEVICE` / `CELLFEE_QAOA_DEVICE` to a cloud device
(`QpiAI-QSV-Simulator`, `QpiAI-QDM-Simulator`, `QpiAI-Indus-1`); refusals are logged and fall back to the local simulator.

## Web experience & dashboard

| URL | What |
|---|---|
| `http://localhost:8000/` | Scroll-driven 3D battery teardown (`experience/index.html`, dashboard palette, see `docs/LANDING_COLOURS.md`), cells show health and both models' answers |
| `http://localhost:8000/dashboard/` | Dashboard with the **CELLFEE Guide** ("✦ Explain me" on every card, plus a chat box) |

API: `/api/results`, `/api/assess` (one battery, both models), `/api/upload` (file, both models per battery),
`/api/upload/sample.csv`, `/api/kernel/run`, `/api/market/match`, `/api/environment`, `/api/evidence`, `/api/listings/…` (marketplace).

## Buy & sell marketplace

Dashboard → **Marketplace**: browse used batteries (filters, compatible uses, distance) and sell one in one of two ways:
- **Quick listing:** drop the health report (PDF, Word or a photo of it) and up to 8 photos. The report's "Label: value"
  lines are read: lab, report ID, date, serial, manufacturer, model, vehicle, age, city, pack/module, chemistry, capacity,
  voltage, SoH and resistance. The seller checks what was read, adds a price and contact, previews and submits.
- **Step-by-step wizard:** details → report → price → photos → preview, with a guide on every step.

`/api/listings/sample/report.pdf` and `/api/listings/sample/photo.png` give fictional sample files to try it with.
You can also track your listings and buyer interest.
- **Marketplace assistant:** a rule-based chat over the live listings, e.g. "cheapest LFP in Pune" or "verified packs
  under 2 lakh". It falls back to the dashboard guide for how-to questions. It is not a general AI.
- **Explain me:** buttons on every marketplace card open the CELLFEE guide.
- **Listing CO₂ estimate:** every listing shows its estimated CO₂ saving. Contact details are shared only after the seller accepts an interest. The marketplace always separates three things:
a **seller-uploaded report**, a **report confirmed by a testing partner**, and a **professional safety assessment** (which it never claims).
Automatic checks (ID mismatch, conflicting SoH, outdated or duplicate report, unregistered provider, edited PDF…) give
every listing a verification state with reasons. The testing partners in `registry/testing_partners.json` are **demo placeholders**
(codes `DEMO-PUNE-2026`, `DEMO-BLR-2026`, `DEMO-DEL-2026`). Data: SQLite `artifacts/marketplace.db`, files in `artifacts/market_files/`.
**Demo data:** `python -m cellfee.market_seed` (from `backend/`) fills it with fictional sample data through the real API:
50 people (20 sellers, 30 buyers), 42 listings (34 open in Browse; partner-verified, awaiting, seller-submitted, outdated,
plus sold / withdrawn / mismatch / held / draft ones), about 90 buyer interests (pending, accepted, declined), generated
PDF reports and drawn photos. Every demo listing is labelled "Demo listing". In **My listings & interests**, "Open demo
accounts" shows the seller Ananya Rao and the buyer Vikram Shetty; **Testing partners** lists the reports waiting for a
re-test. `--clear` removes the demo data (real listings are kept); re-running the seed resets it.
Test: `python -m tests.test_marketplace` (from `backend/`).

## Layout

```
backend/cellfee/
  config.py          constants, thresholds, env keys
  fetch_severson.py  reads the dataset's per-cycle summaries (HTTP range reads into the .mat files)
  data.py            screening features, validation, labels, angle scaling
  quantum_kernel.py  feature map, QpiAI circuits, fidelity test, alignment training
  aqsvc.py           AQSVC: SVM dual as a QpiAI Opt QUBO, bias, bagging + boosting ensemble, stacking meta-learner
  sdk.py             CELLFEE SDK: live QpiAI runs (kernel, QUBO, screen, allocate, QAOA, match) + reproducibility verify
  models.py          XGBoost || AQSVC + baselines, grouped CV, final models
  decision.py        grades from both models, applications, duration ranges
  allocation.py      QpiAI Opt fleet model, exact MILP, QUBO annealing, checks
  qaoa.py            XY-mixer QAOA on QpiAI circuits + QpiAI Opt QAOA
  market.py          listings, buyers, explainable matching (QpiAI Opt model)
  environment.py     scenario CO₂e estimate, breakdown, everyday equivalents, fleet / marketplace totals
  uploads.py         reads uploaded test results (any file type) into features
  report_extract.py  PDF / image (OCR) / Excel / Word reading + field extraction with source snippets
  listings.py        buy & sell marketplace API (SQLite), verification checks
  pipeline.py        end-to-end run → artifacts/results.json
  api.py             FastAPI: both models in parallel, uploads, serves the story + dashboard
frontend/            React + Vite dashboard (reports: src/report.js, guide: src/explain.js)
docs/                decision rules, Bloq cross-check guide, LANDING_COLOURS.md (landing palette tokens)
artifacts/           results.json (fleet summary), fleet_details.json (5,000 passports), cv_oof.npz + cv_summary.json,
                     xgb_model.json, final_model.json, aqsvc_sv_states.npy, evidence/
```

## Safety

Grades, application suggestions and matches are preliminary decision support. They are not safety certification.
Real reuse needs qualified inspection, BMS compatibility, electrical and thermal integration review, and applicable standards.
