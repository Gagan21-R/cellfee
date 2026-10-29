# CELLFEE decision rules — v2.0.0

All thresholds live in `backend/cellfee/config.py`. Grades are preliminary decision support,
not safety certification.

## The question both models answer

> Will this battery last at least **300 more full cycles** before its capacity falls to 80% of its 1.1 Ah rating?

- **XGBoost** (classical) returns a probability `p_xgb`.
- **AQSVC** (quantum) returns `p_aqsvc`: the stacked probability over its 100 QUBO-trained SVMs (two tuned quantum feature maps, each with 25 bagged and 25 boosted SVMs), from a logistic-regression meta-learner.
- Both run on every battery at the same time (two worker threads), in the pipeline, the Assess page and uploads.
- Combined chance `p = (p_xgb + p_aqsvc) / 2`; the models **agree** when both are on the same side of 0.5.

## Grades

| Grade | Rule | Meaning |
|---|---|---|
| A | models agree and p ≥ 0.85 | strong second-life candidate |
| B | models agree and p ≥ 0.65 | second-life candidate |
| T | models disagree, or 0.25 < p < 0.65 | evidence insufficient → full capacity test |
| C | models agree and p ≤ 0.25 | recycling route |

The grade summarises the evidence for one battery. The fleet decision (reuse / test / recycle) is made
jointly by the QpiAI Opt model, which also accounts for test-bench capacity and pack compatibility.

## Hard rules
- Reuse is blocked when p ≤ 0.25.
- Two batteries never share a pack when quantum similarity k < 0.15 or their health differs by more than 0.05.
- A pack holds exactly 4 cells; test-bench capacity is 6 per batch.

## Expected-utility objective (per cell, Indian rupees ₹)
- reuse = p·value(health) − (1 − p)·₹49.80 (pack rework cost)
- test = p·value(health) + (1 − p)·₹4.15 − ₹6.64 (test cost)
- recycle = ₹4.15
- value(health) = health · 1.1 Ah · 3.3 V · ₹8,300/kWh (≈ ₹30 for a full cell)
- pack mismatch: ₹12.45 · Σ pairs [½(1 − k) + ½·min(1, |Δhealth|/0.05)]
- All money assumptions are configured in `backend/cellfee/config.py` (`CURRENCY = "INR"`).

## Marketplace distances
18 Indian cities (`market.CITIES`, city-centre coordinates). Road distance = 1.3 × great-circle distance (stated
assumption); 10 km within a city. The distance term of the match score saturates at 2,000 km.

## Applications and service time
See "Usage baselines" below: 15 registry-driven applications, each with a confidence %, and a validated stop period
(this replaces the earlier 4-application list and the ±50% linear service-duration estimate).

## Screening features (computed identically for training data and uploads)
From the last ≤ 100 valid cycles: health now, capacity lost per 100 cycles, internal resistance now,
resistance rise per 100 cycles, peak temperature, charge time, cycles done. A cycle is valid when
0.5 < capacity < 1.3 Ah, 5 < IR < 50 mΩ, 20 < Tmax < 60 °C and 5 < charge time < 120 min.
At least 20 valid cycles are needed to screen a battery from a log.

## Usage baselines, risk factor, stop period, application confidence (v2.1)

Configured in `backend/cellfee/registry/applications.json` (15 applications, each with its baseline limits) and
`backend/cellfee/registry/baselines.json` (pathways, states, risk weights, confidence threshold). These are **configured
assumptions** — "Configured baseline. Adjust to your safety standard." — and the screen always adds
"Decision support from stored test data. Not a safety certification." Formulas live in `backend/cellfee/usage.py`.

- **Risk factor** = 0.25·health margin to 80% + 0.25·fade-rate percentile + 0.15·resistance-rise percentile
  + 0.15·temperature (35→45 °C) + 0.20·model doubt (1 − |2p − 1|, or 1 when XGBoost and AQSVC disagree).
  Low < 0.35 ≤ Elevated < 0.60 ≤ High. Tier limit: Low → tiers 1–3, Elevated → 1–2, High → 1.
- **Stop period** = XGBoost quantile regression (P10/P50/P90) of cycles until the cell's smoothed health falls below
  the application floor, grouped 5-fold CV (fleet = out-of-fold), capped at the application's cycles in service.
  State: Stop use (below floor or P10 = 0) · Approaching limit (P10 ≤ 100 cycles) · Safe.
- **Confidence** that a battery can serve an application = P(health ≥ floor for ≥ the application's required cycles)
  from an XGBoost classifier per requirement (XGBoost is the stronger model in the stored comparison). Measured
  requirements are gates (chemistry, health, capacity, resistance, peak temperature, safety tier vs risk). Below 60%
  the screen advises a full test.
- **Pathways:** Reuse → ranked suitable applications; Test → "restricted use until tested" (≤ 0.2C, ≤ 40 °C,
  ≤ 50 cycles, tier-1 applications only, shown as "conditional on test"); Recycle → "Do not reuse".
- **Packs:** the weakest member governs — confidence = minimum over members, stop period = that member's, named as
  the limiter. The marketplace match score uses the same pack confidence (weight 0.20).
- Health floors are ≥ 80% because the dataset only observes cells down to 80%; lower floors cannot be validated.
