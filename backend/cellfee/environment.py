"""Scenario-based environmental estimate: reuse vs a stated baseline.

Functional unit: 1 kWh of storage capacity providing service for the stated period.
All factors are user-editable assumptions with low / central / high values; outputs
are estimates, not measured savings. Avoided manufacturing is credited once and the
recycling step is counted in both scenarios (it is delayed, not avoided), so it is
not double counted.
"""

from __future__ import annotations

DEFAULTS = {
    "new_battery_kgco2_per_kwh": {"low": 55.0, "central": 75.0, "high": 110.0,
                                  "note": "cradle-to-gate manufacturing of a new Li-ion pack (literature range; assumption)"},
    "refurb_kgco2_per_kwh": {"low": 3.0, "central": 6.0, "high": 12.0,
                             "note": "testing, sorting, re-packing, new BMS/enclosure (assumption)"},
    "transport_kgco2_per_tkm": {"low": 0.06, "central": 0.10, "high": 0.15, "note": "road freight (assumption)"},
    "pack_kg_per_kwh": {"low": 6.0, "central": 7.0, "high": 8.5, "note": "module mass incl. casing (assumption)"},
    "extra_losses_kgco2_per_kwh": {"low": 1.0, "central": 3.0, "high": 6.0,
                                   "note": "lower round-trip efficiency of aged cells over the service period (assumption)"},
}


def estimate(soh: float, nominal_kwh: float, distance_km: float, baseline: str = "new_battery",
             overrides: dict | None = None) -> dict:
    f = {k: dict(v) for k, v in DEFAULTS.items()}
    for k, v in (overrides or {}).items():
        if k in f:
            f[k]["central"] = float(v)
    usable_kwh = soh * nominal_kwh
    out = {}
    for case in ("low", "central", "high"):
        # 'low' benefit case = small avoided burden, large reuse burden
        g = lambda key, best: f[key][case if best else {"low": "high", "central": "central", "high": "low"}[case]]
        avoided = usable_kwh * g("new_battery_kgco2_per_kwh", True) if baseline == "new_battery" else 0.0
        reuse = (usable_kwh * (g("refurb_kgco2_per_kwh", False) + g("extra_losses_kgco2_per_kwh", False))
                 + nominal_kwh * g("pack_kg_per_kwh", False) / 1000 * distance_km * g("transport_kgco2_per_tkm", False))
        out[case] = round(avoided - reuse, 2)
    return {
        "baseline": "buy a new battery for the same service" if baseline == "new_battery" else "recycle now (no displaced product)",
        "usable_kwh": round(usable_kwh, 3), "net_kgco2e": out,
        "functional_unit": f"{usable_kwh:.2f} kWh of storage for the second-life service period",
        "assumptions": f, "label": "Estimate under stated assumptions, not a measured saving",
        "equivalents": equivalents(out["central"]),
        "battery_kg_kept_in_use": round(nominal_kwh * f["pack_kg_per_kwh"]["central"], 1),
        "breakdown_central": {   # where the central number comes from (kg CO₂e)
            "avoided_new_battery": round(usable_kwh * f["new_battery_kgco2_per_kwh"]["central"], 2) if baseline == "new_battery" else 0.0,
            "refurbishment": -round(usable_kwh * f["refurb_kgco2_per_kwh"]["central"], 2),
            "extra_losses": -round(usable_kwh * f["extra_losses_kgco2_per_kwh"]["central"], 2),
            "transport": -round(nominal_kwh * f["pack_kg_per_kwh"]["central"] / 1000 * distance_km * f["transport_kgco2_per_tkm"]["central"], 2),
        },
    }


# ----------------------------------------------------------------------------- relatable equivalents (assumptions)
EQUIVALENTS = {
    "car_km": {"kg_per_unit": 0.14, "label": "km not driven in a petrol car",
               "note": "typical Indian petrol hatchback, ~0.14 kg CO₂e per km incl. fuel production (assumption)"},
    "tree_years": {"kg_per_unit": 21.0, "label": "tree-years of CO₂ uptake",
                   "note": "one mature tree absorbs ~21 kg CO₂ per year (commonly cited estimate)"},
    "grid_kwh": {"kg_per_unit": 0.71, "label": "kWh of Indian grid electricity",
                 "note": "India grid emission factor ~0.71 kg CO₂ per kWh (CEA CO₂ baseline database, approx.)"},
    "lpg_cylinders": {"kg_per_unit": 42.6, "label": "domestic LPG cylinders burned",
                      "note": "14.2 kg cylinder × ~3.0 kg CO₂ per kg LPG (assumption)"},
}


def equivalents(kg: float) -> dict:
    """The central net saving expressed in everyday units (each factor is a stated assumption)."""
    return {k: {"value": round(kg / v["kg_per_unit"], 1 if kg / v["kg_per_unit"] < 100 else 0), "label": v["label"], "note": v["note"]}
            for k, v in EQUIVALENTS.items()}


def portfolio(items: list[tuple[float, float]], distance_km: float) -> dict:
    """Totals for many batteries: items = [(soh 0-1, nominal_kwh)]. estimate() is linear in nominal kWh, so the sum
    over batteries equals one estimate at the energy-weighted health."""
    nominal = sum(n for _, n in items)
    if nominal <= 0:
        return {"count": 0, "usable_kwh": 0.0, "net_kgco2e": {"low": 0.0, "central": 0.0, "high": 0.0}, "battery_kg_kept_in_use": 0.0,
                "equivalents": equivalents(0.0)}
    soh = sum(s * n for s, n in items) / nominal
    e = estimate(soh, nominal, distance_km)
    return {"count": len(items), "usable_kwh": e["usable_kwh"], "net_kgco2e": e["net_kgco2e"],
            "battery_kg_kept_in_use": round(nominal * DEFAULTS["pack_kg_per_kwh"]["central"], 1),
            "equivalents": equivalents(e["net_kgco2e"]["central"])}
