"""Export pipeline results in the data contract of the scroll experience (experience/index.html).

Contract:
  meta:  qcloud_job_id, opt_job_id, shots, generated_at (+ informative extras)
  cells: id, soh, capacity_ah, resistance_mohm, p_xgb, p_aqsvc, disposition, pack

The experience animates one module of at most 24 cells (4 columns x 6 rows), taken from batch 1 of the
fleet (one truckload of ~33): the module holds every reuse and test battery of that batch and fills the
remaining slots with recycle batteries; meta.module_note states this.
"""

from __future__ import annotations

import json

from . import config

MAX_CELLS = 24


def build(results: dict) -> dict:
    fleet = [b for b in results["fleet"] if b.get("batch", 1) == 1]   # the showcase batch
    pack_letter = {name: chr(ord("A") + k) for k, name in enumerate(sorted({b["pack"] for b in fleet if b["pack"]}))}
    by_action = {a: [b for b in fleet if b["action"] == a] for a in ("reuse", "test", "recycle")}
    chosen = by_action["reuse"] + by_action["test"]
    chosen += by_action["recycle"][: max(0, MAX_CELLS - len(chosen))]
    chosen = sorted(chosen[:MAX_CELLS], key=lambda b: b["id"])

    cells = [{
        "id": b["id"].replace("RB-", "C"),
        "soh": round(b["soh"], 4),
        "capacity_ah": round(b["soh"] * config.NOMINAL_CAPACITY_AH, 3),
        "resistance_mohm": round(b["features"]["ir_mohm"], 2),
        "p_xgb": round(b["p_xgb"], 3),
        "p_aqsvc": round(b["p_aqsvc"], 3),
        "disposition": b["action"],
        "pack": pack_letter.get(b["pack"]) if b["pack"] else None,
        "source": f"MIT–Stanford–Toyota cell {b['source_cell']} · cycle {b['cycle']}",
    } for b in chosen]

    ft = results["qml"]["fidelity_test"]
    qcloud_jobs = ft.get("job_ids") or []
    plan = results["plan"]
    return {
        "meta": {
            "qcloud_job_id": qcloud_jobs[0] if qcloud_jobs else "",
            "opt_job_id": "",
            "shots": ft.get("shots", 0),
            "generated_at": results.get("generated", ""),
            "qcloud_device": ft.get("device", ""),
            "opt_solver": plan.get("solved_by", ""),
            "module_note": f"{len(cells)} of {len(fleet)} batteries in batch 1 of {len(results['fleet']):,} "
                           f"(all reuse and test cells, remaining slots recycle)",
            "fleet_size": len(fleet),
        },
        "cells": cells,
    }


def write_file() -> None:
    results = json.loads(config.RESULTS_JSON.read_text(encoding="utf-8"))
    out = config.ROOT / "experience" / "cellfee_results.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(build(results), indent=2), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    write_file()
