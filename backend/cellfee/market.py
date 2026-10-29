"""Marketplace: listings (CELLFEE-built packs + seller listings) matched to buyer needs.

Hard compatibility filters first (application, energy, budget, evidence), then a
transparent score, then a one-to-one assignment solved as a QpiAI Opt model
(exact MILP solve; QpiAI Opt solver when a key is configured).
Matching is screening only: it never certifies that a battery is safe to install.
"""

from __future__ import annotations

import itertools

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp

from . import config
from .usage import applications as registry_apps
from .sponsors import log_evidence, opt_assignment, opt_client

DEMO_BUYERS = [
    {"id": "BUY-01", "name": "Rooftop-solar homeowner (Pune)", "application": "solar", "min_energy_wh": 11,
     "max_price": 170, "location": "Pune", "needs_test_report": True},
    {"id": "BUY-02", "name": "Telecom tower backup (Nashik)", "application": "backup", "min_energy_wh": 10,
     "max_price": 125, "location": "Nashik", "needs_test_report": False},
    {"id": "BUY-03", "name": "E-cycle refurbisher (Bengaluru)", "application": "mobility", "min_energy_wh": 13,
     "max_price": 250, "location": "Bengaluru", "needs_test_report": True},
    {"id": "BUY-04", "name": "Smart street-light integrator (Mumbai)", "application": "iot", "min_energy_wh": 6,
     "max_price": 100, "location": "Mumbai", "needs_test_report": False},
    {"id": "BUY-05", "name": "Rural microgrid co-operative (Jaipur)", "application": "microgrid", "min_energy_wh": 11,
     "max_price": 180, "location": "Jaipur", "needs_test_report": True},
    {"id": "BUY-06", "name": "Cold-storage operator (Nagpur)", "application": "cold_chain", "min_energy_wh": 10,
     "max_price": 150, "location": "Nagpur", "needs_test_report": False},
    {"id": "BUY-07", "name": "Data-centre UPS integrator (Hyderabad)", "application": "datacentre", "min_energy_wh": 13,
     "max_price": 260, "location": "Hyderabad", "needs_test_report": True},
]

# City centres (latitude, longitude). Road distance is estimated as 1.3 × the great-circle distance (a stated
# assumption for Indian highways); the same city counts as 10 km.
CITIES = {
    "Pune": (18.52, 73.86), "Mumbai": (19.08, 72.88), "Nashik": (20.00, 73.79), "Bengaluru": (12.97, 77.59),
    "Delhi": (28.61, 77.21), "Hyderabad": (17.39, 78.49), "Chennai": (13.08, 80.27), "Kolkata": (22.57, 88.36),
    "Ahmedabad": (23.02, 72.57), "Jaipur": (26.91, 75.79), "Lucknow": (26.85, 80.95), "Kochi": (9.93, 76.27),
    "Nagpur": (21.15, 79.09), "Bhopal": (23.26, 77.41), "Chandigarh": (30.73, 76.78), "Coimbatore": (11.02, 76.96),
    "Visakhapatnam": (17.69, 83.22), "Indore": (22.72, 75.86),
}
ROAD_FACTOR = 1.3
MAX_SCORED_KM = 2000


def locations() -> list[str]:
    return sorted(CITIES)


def distance(a: str, b: str) -> int:
    if a == b:
        return 10
    if a not in CITIES or b not in CITIES:
        return 500
    (la1, lo1), (la2, lo2) = (np.radians(CITIES[a]), np.radians(CITIES[b]))
    h = np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2
    return int(round(ROAD_FACTOR * 2 * 6371 * np.arcsin(np.sqrt(h))))


def pack_listing(k: int, pack: list[int], fleet: list[dict]) -> dict:
    """A CELLFEE-built 4-cell module listed by the recycler hub."""
    soh = [fleet[i]["soh"] for i in pack]
    p_fit = [fleet[i]["p_fit"] for i in pack]
    energy = sum(s * config.NOMINAL_CAPACITY_AH * config.NOMINAL_VOLTAGE_V for s in soh)
    return {"id": f"PACK-{k + 1}", "seller": "CELLFEE recycler hub (Pune)", "location": "Pune", "source": "cellfee_pack",
            "cells": [fleet[i]["id"] for i in pack], "chemistry": "LFP 18650", "series_parallel": "4P",
            "energy_wh": round(energy, 1), "soh_min": round(min(soh), 3), "soh_mean": round(float(np.mean(soh)), 3),
            "p_fit_min": round(min(p_fit), 3),
            "price": round(energy / 1000 * config.VALUE_PER_KWH_SECOND_LIFE * 0.9),
            "test_report": "XGBoost + AQSVC screening report + run evidence", "verified": False,
            "known_defects": "none reported"}


SELLER_LISTINGS = [
    {"id": "LST-11", "seller": "Fleet operator (Mumbai)", "location": "Mumbai", "source": "seller", "cells": [],
     "chemistry": "LFP 18650", "series_parallel": "4P", "energy_wh": 11.6, "soh_min": 0.84, "soh_mean": 0.8,
     "p_fit_min": None, "price": 85, "test_report": "capacity test 2026-09", "verified": True,
     "known_defects": "minor casing dent on 1 cell"},
    {"id": "LST-12", "seller": "Service centre (Nashik)", "location": "Nashik", "source": "seller", "cells": [],
     "chemistry": "LFP 18650", "series_parallel": "4P", "energy_wh": 13.4, "soh_min": 0.92, "soh_mean": 0.93,
     "p_fit_min": 0.9, "price": 200, "test_report": "capacity + cycle log 2026-10", "verified": True,
     "known_defects": "none reported"},
    {"id": "LST-13", "seller": "Individual seller (Bengaluru)", "location": "Bengaluru", "source": "seller", "cells": [],
     "chemistry": "LFP 18650", "series_parallel": "4P", "energy_wh": 9.0, "soh_min": None, "soh_mean": 0.62,
     "p_fit_min": None, "price": 40, "test_report": None, "verified": False,
     "known_defects": "unknown history"},
    {"id": "LST-14", "seller": "Battery recycler (Chennai)", "location": "Chennai", "source": "seller", "cells": [],
     "chemistry": "LFP 18650", "series_parallel": "4P", "energy_wh": 12.5, "soh_min": 0.88, "soh_mean": 0.9,
     "p_fit_min": None, "price": 110, "test_report": "capacity test 2026-10", "verified": True,
     "known_defects": "none reported"},
    {"id": "LST-15", "seller": "E-rickshaw fleet (Delhi)", "location": "Delhi", "source": "seller", "cells": [],
     "chemistry": "LFP 18650", "series_parallel": "4P", "energy_wh": 11.0, "soh_min": 0.82, "soh_mean": 0.85,
     "p_fit_min": None, "price": 70, "test_report": "BMS log export 2026-09", "verified": False,
     "known_defects": "one cell swapped in 2025"},
]


def evaluate_pair(listing: dict, buyer: dict) -> dict:
    app = next(a for a in registry_apps() if a["id"] == buyer["application"])
    reasons, blockers, missing = [], [], []
    if listing["soh_min"] is None:
        missing.append("no health evidence")
        blockers.append("critical health evidence missing")
    elif listing["soh_min"] < app["min_soh"]:
        blockers.append(f"weakest cell health {listing['soh_min']} < {app['min_soh']} required for {app['name']}")
    else:
        reasons.append(f"weakest cell health {listing['soh_min']} meets {app['min_soh']}")
    conf = (listing.get("app_confidence") or {}).get(buyer["application"])
    if listing.get("app_confidence") is None:
        missing.append("no application-confidence screening")
    elif conf is None:
        blockers.append(f"pack not qualified for {app['name']} (a member fails its usage baseline)")
    else:
        shown = ">99%" if conf >= 99.5 else f"{conf:.0f}%"     # a model probability is never shown as certainty
        reasons.append(f"{shown} confidence for {app['name']} (weakest member)")
    if listing["energy_wh"] < buyer["min_energy_wh"]:
        blockers.append(f"energy {listing['energy_wh']} Wh < {buyer['min_energy_wh']} Wh needed")
    else:
        reasons.append(f"{listing['energy_wh']} Wh ≥ {buyer['min_energy_wh']} Wh")
    if listing["price"] > buyer["max_price"]:
        blockers.append(f"price ₹{listing['price']:,.0f} over budget ₹{buyer['max_price']:,.0f}")
    if buyer["needs_test_report"] and not listing["test_report"]:
        blockers.append("buyer requires a test report")
    km = distance(listing["location"], buyer["location"])
    score = 0.0
    if not blockers:
        # the confidence term is the same per-application confidence shown on the passports and Decisions page
        score = (0.35 * min(1.0, listing["energy_wh"] / (1.5 * buyer["min_energy_wh"]))
                 + 0.20 * ((conf if conf is not None else 50.0) / 100)
                 + 0.25 * (1 - listing["price"] / buyer["max_price"])
                 + 0.10 * (1 - min(km, MAX_SCORED_KM) / MAX_SCORED_KM)
                 + 0.10 * (1.0 if listing["verified"] else 0.5))
        reasons.append(f"{km} km away" + (", verified listing" if listing["verified"] else ", unverified: inspect first"))
    return {"listing": listing["id"], "buyer": buyer["id"], "compatible": not blockers, "score": round(score, 4),
            "reasons": reasons, "blockers": blockers, "missing": missing, "distance_km": km}


def match(listings: list[dict], buyers: list[dict]) -> dict:
    from qpiai_opt.opt_modeller import Binary, Model, quicksum

    evals = {(l["id"], b["id"]): evaluate_pair(l, b) for l in listings for b in buyers}
    ok = [(li, bi) for li, l in enumerate(listings) for bi, b in enumerate(buyers) if evals[l["id"], b["id"]]["compatible"]]

    m = Model("cellfee_market_matching")
    x = {(li, bi): Binary(f"m_{li}_{bi}") for li, bi in ok}
    for li in range(len(listings)):
        terms = [x[k] for k in x if k[0] == li]
        if len(terms) > 1:
            m.add_constraint(quicksum(terms) <= 1, label=f"listing_once_{li}")
    for bi in range(len(buyers)):
        terms = [x[k] for k in x if k[1] == bi]
        if len(terms) > 1:
            m.add_constraint(quicksum(terms) <= 1, label=f"buyer_once_{bi}")
    if x:
        m.maximize(quicksum(evals[listings[li]["id"], buyers[bi]["id"]]["score"] * x[li, bi] for li, bi in ok))

    chosen: list[tuple[int, int]] = []
    solver = "Exact MILP (HiGHS) on QpiAI Opt model"
    if ok:
        A_rows, lo, hi = [], [], []
        for li in range(len(listings)):
            A_rows.append([1.0 if k[0] == li else 0.0 for k in ok]); lo.append(0); hi.append(1)
        for bi in range(len(buyers)):
            A_rows.append([1.0 if k[1] == bi else 0.0 for k in ok]); lo.append(0); hi.append(1)
        c = -np.array([evals[listings[li]["id"], buyers[bi]["id"]]["score"] for li, bi in ok])
        res = milp(c, constraints=LinearConstraint(np.array(A_rows), lo, hi),
                   integrality=np.ones(len(ok)), bounds=Bounds(0, 1))
        chosen = [k for k, v in zip(ok, res.x) if v > 0.5]
        client = opt_client()
        if client is not None:
            try:
                from qpiai_opt.opt_solvers import solve

                r = solve(m, client=client)
                sol = opt_assignment(r, m)
                chosen = [k for k in ok if float(sol.get(f"m_{k[0]}_{k[1]}", 0)) > 0.5]
                solver = "QpiAI Opt local solver"
            except Exception:
                pass

    matches = [{**evals[listings[li]["id"], buyers[bi]["id"]], "listing_detail": listings[li],
                "buyer_detail": buyers[bi]} for li, bi in chosen]
    log_evidence("market_matching", {"backend": solver, "summary": f"{len(matches)} matches from {len(ok)} compatible pairs",
                                     "matches": [(mm["listing"], mm["buyer"], mm["score"]) for mm in matches]})
    return {"solver": solver, "matches": matches, "all_pairs": list(evals.values()),
            "compatible_pairs": len(ok), "total_score": round(sum(mm["score"] for mm in matches), 4)}
