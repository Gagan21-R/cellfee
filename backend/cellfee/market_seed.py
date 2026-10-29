"""Demo marketplace data: fictional sellers, buyers, listings, interests and partner checks.  Run from backend/:
    python -m cellfee.market_seed            # replace earlier demo data (real listings are kept)
    python -m cellfee.market_seed --clear    # remove the demo data only

Everything goes through the real marketplace API (report upload with automatic field reading, checks, submit,
interest, accept / decline, partner confirmation), so every verification state is produced by the same code a real
listing would see. Each demo listing carries `demo: true` and is labelled "Demo listing" in the dashboard.
People, phone numbers (+91-90000-…), e-mails (@example.com), serials and report IDs are invented. Batteries are
described by the vehicle they came from; no manufacturer is involved.

Two demo personas get their keys written to artifacts/market_demo_accounts.json so "My listings & interests" can be
opened as them: Ananya Rao (seller) and Vikram Shetty (buyer).
"""

from __future__ import annotations

import base64
import io
import json
import random
import shutil
import sys
import tempfile
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from . import config, listings

ACCOUNTS = config.ARTIFACTS / "market_demo_accounts.json"
rng = random.Random(2026)

# ----------------------------------------------------------------------------- catalogue (typical second-life stock)
# (vehicle, manufacturer, model, chemistry, kWh, volts, form, base ₹ per kWh at 100% SoH)
BATTERIES = [
    ("Tata Nexon EV (2021)", "Tata Motors", "Nexon EV pack", "LFP", 30.2, 320, "pack", 7200),
    ("Tata Tigor EV (2022)", "Tata Motors", "Tigor EV pack", "LFP", 26.0, 320, "pack", 7000),
    ("Tata Nexon EV (2020)", "Tata Motors", "Nexon EV module", "LFP", 2.5, 32, "module", 7600),
    ("MG ZS EV (2020)", "MG Motor", "ZS EV pack", "NMC", 44.5, 394, "pack", 6400),
    ("MG ZS EV (2020)", "MG Motor", "ZS EV module", "NMC", 3.7, 48, "module", 6800),
    ("Mahindra eVerito (2019)", "Mahindra", "eVerito pack", "NMC", 21.2, 72, "pack", 5600),
    ("Mahindra Treo (2021)", "Mahindra", "Treo pack", "LFP", 7.4, 48, "pack", 7400),
    ("Ather 450X (2021)", "Ather Energy", "450X pack", "NMC", 2.9, 50, "pack", 7800),
    ("Ola S1 Pro (2022)", "Ola Electric", "S1 Pro pack", "NMC", 4.0, 50, "pack", 7000),
    ("TVS iQube (2021)", "TVS Motor", "iQube pack", "NMC", 3.0, 51, "pack", 7200),
    ("Bajaj Chetak (2021)", "Bajaj Auto", "Chetak pack", "NMC", 2.9, 50, "pack", 7200),
    ("Hero Electric Optima (2020)", "Hero Electric", "Optima pack", "LFP", 1.5, 48, "pack", 8200),
    ("Piaggio Ape E-City (2020)", "Piaggio", "Ape E-City pack", "LFP", 4.5, 48, "pack", 7400),
    ("Euler HiLoad (2022)", "Euler Motors", "HiLoad pack", "LFP", 12.4, 76, "pack", 7000),
    ("Electric city bus (2019)", "Olectra", "eBus LFP module", "LFP", 11.0, 76, "module", 6600),
    ("Delivery e-scooter fleet (2022)", "Yulu", "swap battery", "LFP", 1.9, 48, "module", 8000),
]
CITIES = sorted(listings.CITIES)
PARTNER = {p["city"]: p for p in listings.partners()["partners"]}
OTHER_LABS = ["AutoCell Service Garage", "Sai Battery Works", "QuickCheck EV Clinic", "Metro Cell Diagnostics"]

SELLERS = [  # (name, type, city, contact)  — the first is the demo seller persona
    ("Ananya Rao", "individual owner", "Bengaluru"), ("GreenRide Fleet Services", "fleet operator", "Pune"),
    ("Rohan Mehta", "individual owner", "Mumbai"), ("Sunrise E-Rickshaw Co-op", "fleet operator", "Lucknow"),
    ("Priya Nair", "individual owner", "Kochi"), ("VoltCycle Recyclers", "recycler", "Chennai"),
    ("Arjun Singh", "individual owner", "Delhi"), ("CityLoop Logistics", "fleet operator", "Hyderabad"),
    ("Meera Iyer", "individual owner", "Coimbatore"), ("ReCharge Auto Dealers", "used-EV dealer", "Ahmedabad"),
    ("Kabir Khan", "individual owner", "Jaipur"), ("Deccan Bus Depot (demo)", "transit operator", "Nagpur"),
    ("Sneha Kulkarni", "individual owner", "Nashik"), ("EcoMile Couriers", "fleet operator", "Kolkata"),
    ("Farhan Ali", "individual owner", "Bhopal"), ("Second Spark Batteries", "refurbisher", "Indore"),
    ("Harpreet Kaur", "individual owner", "Chandigarh"), ("Coastal Cabs", "fleet operator", "Visakhapatnam"),
    ("Aditya Joshi", "individual owner", "Pune"), ("Lakshmi Traders", "used-EV dealer", "Chennai"),
]
BUYERS = [  # (name, what they need) — the first is the demo buyer persona
    ("Vikram Shetty", "home solar backup"), ("SunHarvest Agro (demo)", "solar water pumps"), ("Neha Gupta", "home UPS"),
    ("TowerLink Telecom (demo)", "telecom tower backup"), ("Rahul Verma", "e-cycle conversion"), ("Kiran Reddy", "shop backup"),
    ("GridBox Microgrids", "village microgrid"), ("Pooja Desai", "home solar"), ("ColdStore Logistics", "cold-room backup"),
    ("Imran Sheikh", "e-rickshaw repair"), ("Divya Menon", "home UPS"), ("Sanjay Patil", "farm pump"),
    ("ChargeHub Stations", "EV charging buffer"), ("Anil Kumar", "workshop backup"), ("Ritu Sharma", "rooftop solar"),
    ("BrightPath Streetlights", "street-light nodes"), ("Manoj Yadav", "e-rickshaw fleet"), ("Kavya Pillai", "home solar"),
    ("ServerNest Data Centre", "server UPS"), ("Gaurav Bansal", "boat electrification"), ("Tanvi Joshi", "home UPS"),
    ("WareMove AGVs", "forklifts and AGVs"), ("Suresh Babu", "solar pump"), ("Nisha Agarwal", "clinic backup"),
    ("Deepak Chauhan", "e-cart build"), ("Asha Fernandes", "homestay backup"), ("Varun Malhotra", "research lab"),
    ("Zoya Siddiqui", "school solar"), ("Prakash Hegde", "dairy chiller backup"), ("Ishaan Kapoor", "camper van"),
]
MESSAGES = [
    "Is it still available? I can come for an inspection this weekend.",
    "What is the lowest price? I need it for {need}.",
    "Can you share the full test report and the BMS log?",
    "Would you deliver to my city? Happy to pay transport.",
    "Can a qualified technician inspect it before I pay?",
    "Interested for {need}. Is the BMS included and working?",
    "Has the pack ever been opened or repaired?",
    "Can you hold it for two days while I arrange payment?",
]


def _phone(k: int) -> str:
    return f"+91-90000-{10000 + k:05d}"


def _email(name: str) -> str:
    return name.lower().replace(" (demo)", "").replace(" ", ".").replace("-", "") + "@example.com"


# ----------------------------------------------------------------------------- generated documents
def _pdf(lines: list[str]) -> bytes:
    esc = lambda s: s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    content = "BT /F1 11 Tf 50 790 Td 15 TL\n" + "".join(f"({esc(l)}) Tj T*\n" for l in lines) + "ET"
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            f"<< /Length {len(content)} >>\nstream\n{content}\nendstream", "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = "%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out)); out += f"{i} 0 obj\n{o}\nendobj\n"
    x = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n" + "".join(f"{o:010d} 00000 n \n" for o in offs)
    return (out + f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF").encode("latin-1")


def _photo(kind: str, title: str, chem: str, soh: float, serial: str, form: str) -> bytes:
    """A simple drawn illustration (clearly marked DEMO PHOTO), not a photograph."""
    from PIL import Image, ImageDraw
    W, H = 640, 420
    bg = {"exterior": (242, 238, 227), "label": (255, 253, 247)}[kind]
    im = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(im)
    case = (62, 60, 55) if chem == "LFP" else (46, 58, 76)
    if kind == "exterior":
        w = 420 if form == "pack" else 300
        x0, y0 = (W - w) // 2, 120
        d.polygon([(x0, y0), (x0 + 60, y0 - 50), (x0 + w + 60, y0 - 50), (x0 + w, y0)], fill=tuple(min(255, c + 40) for c in case))
        d.polygon([(x0 + w, y0), (x0 + w + 60, y0 - 50), (x0 + w + 60, y0 + 160), (x0 + w, y0 + 210)], fill=tuple(max(0, c - 18) for c in case))
        d.rectangle([x0, y0, x0 + w, y0 + 210], fill=case, outline=(11, 11, 11), width=3)
        d.rectangle([x0 + 30, y0 + 30, x0 + 190, y0 + 90], fill=(242, 238, 227))
        for k in range(3):
            d.line([x0 + 42, y0 + 46 + 14 * k, x0 + 170, y0 + 46 + 14 * k], fill=(120, 116, 106), width=4)
        d.ellipse([x0 + w - 70, y0 - 38, x0 + w - 40, y0 - 22], fill=(214, 36, 24))
        d.ellipse([x0 + 90, y0 - 38, x0 + 120, y0 - 22], fill=(30, 29, 27))
        bar = int((w - 60) * soh / 100)
        d.rectangle([x0 + 30, y0 + 150, x0 + w - 30, y0 + 175], outline=(242, 238, 227), width=2)
        d.rectangle([x0 + 33, y0 + 153, x0 + 30 + bar - 3, y0 + 172], fill=(0, 135, 95) if soh >= 80 else (178, 94, 0))
    else:
        d.rectangle([60, 70, W - 60, H - 70], fill=(255, 255, 255), outline=(11, 11, 11), width=3)
        for k, line in enumerate([title, f"Chemistry {chem}", f"S/N {serial}", "Handle as per local battery rules"]):
            d.text((90, 100 + 40 * k), line, fill=(11, 11, 11))
        d.rectangle([W - 200, 100, W - 100, 200], outline=(11, 11, 11), width=2)
        for k in range(0, 100, 12):
            d.line([W - 200 + k, 100, W - 200 + k, 200], fill=(11, 11, 11), width=3 if k % 24 else 1)
    d.rectangle([0, 0, W, 34], fill=(255, 225, 77))
    d.text((14, 11), f"DEMO PHOTO (illustration) - {kind} - {title}", fill=(11, 11, 11))
    b = io.BytesIO(); im.save(b, "PNG"); return b.getvalue()


b64 = lambda data: base64.b64encode(data).decode()


# ----------------------------------------------------------------------------- database helpers
def _patch_doc(lid: str, **extra):
    con = listings.db()
    doc = json.loads(con.execute("SELECT doc FROM listings WHERE id = ?", (lid,)).fetchone()["doc"])
    doc.update(extra)
    con.execute("UPDATE listings SET doc = ? WHERE id = ?", (json.dumps(doc), lid)); con.commit()


def _backdate(lid: str, days: float):
    """Spread demo listings over the past weeks: created / history / interests shifted back consistently."""
    con = listings.db()
    row = con.execute("SELECT * FROM listings WHERE id = ?", (lid,)).fetchone()
    doc, shift = json.loads(row["doc"]), timedelta(days=days)
    for h in doc.get("history", []):
        h["at"] = (datetime.fromisoformat(h["at"]) - shift).isoformat(timespec="seconds")
    if doc.get("partner_confirmation"):     # partner re-test happened a few days after listing
        pc = doc["partner_confirmation"]
        pc["at"] = (datetime.fromisoformat(pc["at"]) - shift * 0.7).isoformat(timespec="seconds")
    con.execute("UPDATE listings SET doc = ?, created = ?, updated = ? WHERE id = ?",
                (json.dumps(doc), row["created"] - shift.total_seconds(), row["updated"] - shift.total_seconds(), lid))
    con.execute("UPDATE interests SET created = created - ? WHERE listing_id = ?", (shift.total_seconds() * rng.uniform(0.1, 0.8), lid))
    con.commit()


def clear() -> int:
    con = listings.db()
    ids = [r["id"] for r in con.execute("SELECT id, doc FROM listings") if json.loads(r["doc"]).get("demo")]
    for lid in ids:
        con.execute("DELETE FROM interests WHERE listing_id = ?", (lid,))
        con.execute("DELETE FROM listings WHERE id = ?", (lid,))
        shutil.rmtree(listings.FILES / lid, ignore_errors=True)
    con.commit()
    ACCOUNTS.unlink(missing_ok=True)
    return len(ids)


# ----------------------------------------------------------------------------- seeding
def seed() -> dict:
    # keep seeding out of the evidence log (it records real runs, not demo set-up)
    config.EVIDENCE_DIR = Path(tempfile.mkdtemp(prefix="cellfee-seed-evidence-"))
    from fastapi.testclient import TestClient
    from .api import app
    C = TestClient(app)
    removed = clear()
    today = date.today()

    # plan: (seller index, scenario).  scenario -> verified | awaiting | unregistered | outdated | mismatch | held | sold | withdrawn | draft
    plan = [(0, "verified"), (0, "awaiting"), (0, "sold"), (0, "mismatch")]
    plan += [(1, "verified"), (1, "verified"), (1, "awaiting"), (1, "outdated")]
    others = list(range(2, len(SELLERS)))
    mix = (["verified"] * 9 + ["awaiting"] * 10 + ["unregistered"] * 6 + ["outdated"] * 3 +
           ["sold"] * 2 + ["withdrawn"] + ["mismatch"] + ["draft"])
    rng.shuffle(mix)
    for k, sc in enumerate(mix):
        plan.append((others[k % len(others)], sc))
    plan.append((others[-1], "held"))     # last, so it is the one that collides with an existing report ID

    sellers, made = {}, []
    serial_no, report_no = 4100, 7300
    for n, (si, sc) in enumerate(plan):
        name, stype, city = SELLERS[si]
        veh, make, model, chem, kwh, volt, form, rate = BATTERIES[(n * 7 + si) % len(BATTERIES)]
        soh = round(rng.uniform(72, 94) if sc != "sold" else rng.uniform(80, 90), 1)
        age = rng.choice([2, 3, 3, 4, 4, 5, 6, 7])
        serial_no += rng.randint(3, 40); report_no += rng.randint(2, 30)
        serial = f"{''.join(ch for ch in make if ch.isalpha())[:3].upper()}-{(today.year - age) % 100:02d}-{serial_no:06d}"
        lab = PARTNER.get(city) or rng.choice(list(PARTNER.values()))
        provider = rng.choice(OTHER_LABS) if sc == "unregistered" else lab["name"]
        report_id = f"{''.join(w[0] for w in provider.split()[:3]).upper()}-{report_no}"
        listed_days_ago = rng.uniform(2, 70)
        tested = today - timedelta(days=int(rng.uniform(220, 420) if sc == "outdated" else listed_days_ago + rng.uniform(3, 60)))
        measured = round(kwh * soh / 100, 2)
        ir = round(rng.uniform(25, 60) * (48 / max(volt, 48)) ** 0.2 * (1.25 - soh / 400), 1)

        r = C.post("/api/listings").json()
        lid, tok = r["id"], r["token"]
        _patch_doc(lid, demo=True, seller={"name": name, "type": stype})
        sellers.setdefault(si, {})[lid] = tok
        C.patch(f"/api/listings/{lid}", json={"token": tok, "details": {
            "manufacturer": make, "model": model, "chemistry": chem, "vehicle": veh, "age_years": age, "serial": serial,
            "rated_capacity_kwh": kwh, "rated_voltage_v": volt, "city": city, "form": form,
            "usage_history": rng.choice(["Daily city commute, home charging", "Fleet duty, two shifts a day, fast-charged",
                                         "Last-mile delivery, swapped daily", "Weekend use, mostly slow charging",
                                         "Shuttle route, depot charging overnight"]),
            "reason": rng.choice(["Vehicle sold / upgraded", "Range no longer enough for fleet duty", "Vehicle written off (battery undamaged)",
                                  "Fleet replacing packs at 80% SoH", "Clearing surplus stock"])}})
        doc_serial = f"{serial[:-1]}{(int(serial[-1]) + 3) % 10}" if sc == "mismatch" else serial
        if sc == "held":                       # re-uses the withdrawn listing's report ID -> held for review
            report_id = next(m["report_id"] for m in made if m["scenario"] == "withdrawn")
        pdf = _pdf([f"BATTERY HEALTH REPORT - DEMO DOCUMENT (fictional, generated by CELLFEE seed)", f"Tested by: {provider}",
                    f"Report ID: {report_id}", f"Test date: {tested.isoformat()}", f"Battery serial number: {doc_serial}",
                    f"Chemistry: {chem}", f"State of Health: {soh} %", f"Measured capacity: {measured} kWh",
                    f"Internal resistance: {ir} mOhm", "Tests: capacity discharge at C/3, DCIR pulse, visual inspection, BMS read-out",
                    "Limitations: cells not individually opened; thermal imaging not performed"])
        if sc != "draft":
            C.post(f"/api/listings/{lid}/report", json={"token": tok, "filename": f"{report_id}.pdf", "content_b64": b64(pdf)})
            C.patch(f"/api/listings/{lid}", json={"token": tok, "report": {
                "tests_performed": "Capacity discharge (C/3), DCIR pulse, visual inspection, BMS read-out",
                "limitations": "Cells not individually opened; thermal imaging not performed"}})
        price = round(kwh * rate * soh / 100 * rng.uniform(0.9, 1.08) / 500) * 500
        C.patch(f"/api/listings/{lid}", json={"token": tok, "sale": {
            "price_inr": price, "negotiable": rng.random() < 0.6,
            "condition": rng.choice(["Used, no visible damage; terminals clean", "Minor scuffs on the casing; no swelling or leaks",
                                     "Good condition; removed by an authorised workshop", "Casing intact, one mounting bracket bent"]),
            "known_faults": rng.choice(["None known", "None known", "BMS logged one over-temperature event last summer",
                                        "One module ~3% weaker than the rest (per report)"]),
            "warranty": rng.choice(["Sold as-is", "Sold as-is", "7-day return if the report values cannot be reproduced",
                                    "30-day refurbisher warranty on the BMS"]),
            "inspection_allowed": rng.random() < 0.9,
            "transport": rng.choice(["Buyer collects", "Can arrange transport within 300 km at cost",
                                     "Shipped by a dangerous-goods certified carrier at cost"]),
            **(lambda m: {"contact_method": m, "contact_value": _email(name) if m == "email" else _phone(si)})(
                rng.choice(["phone", "phone", "whatsapp", "email"]))}})
        if sc != "draft":
            for kind in ("exterior", "label"):
                C.post(f"/api/listings/{lid}/photos", json={"token": tok, "filename": f"{kind}.png", "kind": kind,
                                                            "content_b64": b64(_photo(kind, f"{make} {model}", chem, soh, serial, form))})
            C.post(f"/api/listings/{lid}/submit", json={"token": tok})
        if sc == "verified":
            p = next(p for p in listings.partners()["partners"] if p["name"] == provider)
            C.post(f"/api/listings/{lid}/partner-confirm", json={"partner_code": p["code"], "report_id": report_id,
                                                                "measured_soh_pct": round(soh + rng.uniform(-0.6, 0.6), 1),
                                                                "note": "Demo partner re-test"})
        made.append({"id": lid, "token": tok, "scenario": sc, "seller": si, "report_id": report_id, "days": listed_days_ago})

    # buyers' interest
    open_ids = [m for m in made if m["scenario"] in ("verified", "awaiting", "unregistered", "outdated", "sold")]
    buyer_keys, n_int = {}, 0
    for bi, (bname, need) in enumerate(BUYERS):
        k = 5 if bi == 0 else rng.choice([2, 2, 3, 3, 4])
        for m in rng.sample(open_ids, k):
            r = C.post(f"/api/listings/{m['id']}/interest", json={
                "name": bname, "contact": _email(bname) if rng.random() < 0.5 else _phone(100 + bi),
                "message": rng.choice(MESSAGES).format(need=need)})
            if r.status_code != 200:
                continue
            n_int += 1
            buyer_keys.setdefault(bi, {})[r.json()["id"]] = r.json()["token"]
            m.setdefault("interests", []).append((bi, r.json()["id"]))
    # sellers respond: some accept (contacts shared), some decline; demo persona keeps a few pending
    vikram = iter(["accept", "accept", "decline"])             # the demo buyer: 2 accepted, 1 declined, the rest pending
    for m in made:
        for j, (bi, iid) in enumerate(m.get("interests", [])):
            roll = rng.random()
            if m["seller"] == 0 and m["scenario"] == "awaiting":
                continue                                        # Ananya still has requests to answer
            if bi == 0:
                act = next(vikram, "pending")
                if act != "pending":
                    C.post(f"/api/listings/{m['id']}/interests/{iid}/{act}", json={"token": m["token"]})
                continue
            if m["scenario"] == "sold" and j == 0:
                C.post(f"/api/listings/{m['id']}/interests/{iid}/accept", json={"token": m["token"]})   # the buyer it was sold to
            elif m["scenario"] == "sold":
                C.post(f"/api/listings/{m['id']}/interests/{iid}/decline", json={"token": m["token"]})
            elif roll < 0.25:
                C.post(f"/api/listings/{m['id']}/interests/{iid}/accept", json={"token": m["token"]})
            elif roll < 0.38:
                C.post(f"/api/listings/{m['id']}/interests/{iid}/decline", json={"token": m["token"]})
    for m in made:
        if m["scenario"] in ("sold", "withdrawn"):
            C.post(f"/api/listings/{m['id']}/status", json={"token": m["token"], "status": m["scenario"]})
        _backdate(m["id"], m["days"])

    accounts = {"_about": "DEMO personas for the marketplace (fictional). Loading them in the dashboard stores these keys in the browser.",
                "seller": {"name": SELLERS[0][0], "about": f"{SELLERS[0][1]}, {SELLERS[0][2]}", "keys": sellers[0]},
                "buyer": {"name": BUYERS[0][0], "about": f"looking for {BUYERS[0][1]}", "keys": buyer_keys.get(0, {})}}
    ACCOUNTS.write_text(json.dumps(accounts, indent=1), encoding="utf-8")
    shutil.rmtree(config.EVIDENCE_DIR, ignore_errors=True)
    con = listings.db()
    states = {}
    for r in con.execute("SELECT status, verification, doc FROM listings"):
        if json.loads(r["doc"]).get("demo"):
            states[f"{r['status']}/{r['verification']}"] = states.get(f"{r['status']}/{r['verification']}", 0) + 1
    public = C.get("/api/listings").json()["listings"]
    return {"removed_old_demo": removed, "listings": len(made), "in_browse": sum(1 for l in public if l.get("demo")),
            "people": len(SELLERS) + len(BUYERS), "sellers": len(SELLERS), "buyers": len(BUYERS), "interests": n_int, "states": states}


if __name__ == "__main__":
    if "--clear" in sys.argv:
        print({"removed": clear()})
    else:
        t = time.time()
        print(json.dumps(seed(), indent=1), f"\n{time.time() - t:.0f}s")
