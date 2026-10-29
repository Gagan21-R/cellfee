# Bloq cross-check (do this yourself — it needs your Bloq login)

Goal: an independent check of the CELLFEE quantum kernel on Bloq's platform.

1. Log in at https://platform.bloq.in and open **Experiments**.
2. Upload `data/processed/severson_snapshots.csv` (8,753 real snapshots from 124 cells).
   - Features: `soh, fade_100, ir_mohm, ir_rise_100, temp_max_c, charge_time_min, cycles`
   - Target: `label_fit` (classification: 1 = at least 300 cycles left before 80% capacity).
   - Group / split column: `cell` (split by cell, never by row, to avoid leakage).
3. Run Bloq's **QSVM** and/or **PQK** (projected quantum kernel) with 7 qubits.
4. Record accuracy / ROC-AUC and the run ID, and add them to the "XGBoost vs AQSVC" slide next to
   the CELLFEE numbers on the dashboard's comparison page.
5. Optional: redraw the CELLFEE feature map (RY → RZ → ring RZZ, 2 layers) in **Visual Circuit Studio**
   for the slides, and ask **Bloq Maya** to review the allocation QUBO from `backend/cellfee/allocation.py`.
