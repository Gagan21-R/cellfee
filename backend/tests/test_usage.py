"""Usage-baseline checks.  Run from backend/:  python -m tests.test_usage   (or pytest tests/)

1. every stored confidence is within [0, 100];
2. confidences and stop periods are reproducible: re-running usage.evaluate on the stored inputs and the stored raw
   model outputs gives exactly the stored values (what the dashboard displays);
3. pack confidence is the minimum over the pack's members, and the limiter is a member;
4. the live API path returns confidences in range for a real fleet battery.
"""

from __future__ import annotations

import json
import random

from cellfee import config, usage

R = json.loads(config.RESULTS_JSON.read_text())
D = json.loads((config.ARTIFACTS / "fleet_details.json").read_text())
META = json.loads(usage.META.read_text())
FLEET = {b["id"]: b for b in R["fleet"]}


def _pred(stored: dict) -> dict:
    return {"cls": stored["cls"], "q": {float(f): v for f, v in stored["q"].items()}}


def test_confidence_range():
    n = 0
    for d in D.values():
        for a in d["usage"]["applications"]:
            if a["confidence"] is not None:
                assert 0 <= a["confidence"] <= 100, (a["id"], a["confidence"])
                n += 1
    assert n > 1000


def test_reproducible_from_stored_outputs():
    random.seed(7)
    for bid in random.sample(sorted(D), 300):
        b, d = FLEET[bid], D[bid]
        u = usage.evaluate(b["features"], b["p_xgb"], b["p_aqsvc"], b["action"], _pred(d["usage"]["model_outputs"]), META["risk_ref"])
        stored = {a["id"]: a for a in d["usage"]["applications"]}
        for a in u["applications"]:
            s = stored[a["id"]]
            assert a["confidence"] == s["confidence"], (bid, a["id"], a["confidence"], s["confidence"])
            assert a["stop"] == s["stop"], (bid, a["id"])
            assert a["status"] == s["status"], (bid, a["id"])
        assert u["state"] == d["usage"]["state"] and u["risk"] == d["usage"]["risk"]


def test_pack_rule_minimum_over_members():
    for name, pd in R["packs_detail"].items():
        for row in pd["applications"]:
            confs = [next(a for a in D[m]["usage"]["applications"] if a["id"] == row["id"])["confidence"] for m in pd["members"]]
            assert row["confidence"] == min(confs), (name, row["id"])
            assert row["limiter"] in pd["members"]


def test_live_api_path():
    from cellfee.api import AssessIn, api_assess
    f = R["fleet"][0]["features"]
    r = api_assess(AssessIn(soh=f["soh"], fade_100=f["fade_100"], ir_mohm=f["ir_mohm"], ir_rise_100=f["ir_rise_100"],
                            temp_max_c=f["temp_max_c"], charge_time_min=f["charge_time_min"], cycles=f["cycles"]))
    for a in r["usage"]["applications"]:
        assert a["confidence"] is None or 0 <= a["confidence"] <= 100


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok ", name)
