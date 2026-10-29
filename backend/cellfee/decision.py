"""Transparent, versioned decision rules: the grade from both models.

Applications, usage baselines, stop periods and confidence live in usage.py (registry-driven).

Inputs per battery: its measured health, its recent fade rate, and the two models' probabilities that
it still has >= LONG_LIFE_CYCLES cycles left (XGBoost = classical, AQSVC = quantum).
Grades are preliminary decision support, never a safety certification.
"""

from __future__ import annotations

import numpy as np

from . import config

def combine(p_xgb: float, p_aq: float) -> dict:
    """Both models' answers side by side, and what they mean together."""
    p = (p_xgb + p_aq) / 2
    vx, vq = p_xgb >= 0.5, p_aq >= 0.5
    return {"p_fit": float(p), "agree": bool(vx == vq), "xgb_says_fit": bool(vx), "aqsvc_says_fit": bool(vq)}


def grade(p_xgb: float, p_aq: float) -> dict:
    c = combine(p_xgb, p_aq)
    p = c["p_fit"]
    both = f"XGBoost {p_xgb:.0%}, AQSVC {p_aq:.0%} chance of ≥{config.LONG_LIFE_CYCLES} cycles left"
    if c["agree"] and p >= config.GRADE_A_P:
        g, reason = "A", f"Both models are confident it has a long life ahead ({both})"
    elif c["agree"] and p >= config.GRADE_B_P:
        g, reason = "B", f"Both models say it has a long life ahead ({both})"
    elif c["agree"] and p <= config.GRADE_C_P:
        g, reason = "C", f"Both models say it is close to the end of its useful life ({both}): recycling route"
    else:
        why = "The two models disagree" if not c["agree"] else "The models are not confident"
        g, reason = "T", f"{why} ({both}): a full capacity test is needed to decide"
    return {"grade": g, "reason": reason, **c}


def p_fit_array(p_xgb: np.ndarray, p_aq: np.ndarray) -> np.ndarray:
    return (np.asarray(p_xgb) + np.asarray(p_aq)) / 2
