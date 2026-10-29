"""Marketplace flow, end to end through the API, on a throw-away database.  Run from backend/:
    python -m tests.test_marketplace

Covers: draft -> details -> report upload with automatic field reading -> price -> photo -> preview -> submit,
the checks (ID mismatch, conflicting SoH, duplicate report, outdated report, unregistered provider), that a
seller-submitted report is never shown as verified, partner confirmation, buyer browse/detail without private
contact, interest -> accept -> contact shared, and that another seller's token cannot edit a listing.
"""

from __future__ import annotations

import base64
import io
import tempfile
from datetime import date, timedelta
from pathlib import Path

from cellfee import config, listings, report_extract

TMP = Path(tempfile.mkdtemp(prefix="cellfee-market-test-"))
config.EVIDENCE_DIR = TMP / "evidence"          # keep test runs out of the real evidence log
listings.DB = TMP / "test.db"
listings.FILES = TMP / "files"

from fastapi.testclient import TestClient  # noqa: E402
from cellfee.api import app  # noqa: E402

C = TestClient(app)


def pdf(lines: list[str]) -> bytes:
    content = "BT /F1 11 Tf 50 780 Td 14 TL\n" + "".join(f"({l}) Tj T*\n" for l in lines) + "ET"
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            f"<< /Length {len(content)} >>\nstream\n{content}\nendstream", "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = "%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out)); out += f"{i} 0 obj\n{o}\nendobj\n"
    x = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n" + "".join(f"{o:010d} 00000 n \n" for o in offs)
    return (out + f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF").encode("latin-1")


def png() -> bytes:
    from PIL import Image
    b = io.BytesIO(); Image.new("RGB", (40, 30), (200, 200, 190)).save(b, "PNG"); return b.getvalue()


b64 = lambda data: base64.b64encode(data).decode()
today = date.today().isoformat()


def new_listing(serial="SN-TEST-0100", report_id="DBT-TEST-1", soh_doc="86", provider="Demo Battery Test Lab (Pune)",
                test_date=today, soh_entered=None):
    r = C.post("/api/listings").json()
    lid, tok = r["id"], r["token"]
    C.patch(f"/api/listings/{lid}", json={"token": tok, "details": {
        "manufacturer": "TestMake", "model": "Pack-A", "chemistry": "LFP", "vehicle": "Test e-scooter", "age_years": 4,
        "serial": serial, "rated_capacity_kwh": 3.0, "rated_voltage_v": 48, "city": "Pune", "form": "pack"}})
    doc = pdf(["TEST DOCUMENT - software test only", f"Tested by: {provider}", f"Report ID: {report_id}",
               f"Test date: {test_date}", f"Battery serial number: {serial}", f"State of Health: {soh_doc} %",
               "Measured capacity: 2.5 kWh", "Internal resistance: 41 mOhm"])
    v = C.post(f"/api/listings/{lid}/report", json={"token": tok, "filename": "report.pdf", "content_b64": b64(doc)}).json()
    if soh_entered is not None:
        C.patch(f"/api/listings/{lid}", json={"token": tok, "report": {"soh_pct": soh_entered, "tests_performed": "capacity, DCIR"}})
    C.patch(f"/api/listings/{lid}", json={"token": tok, "sale": {"price_inr": 45000, "negotiable": True, "condition": "used, no damage",
                                                                "contact_method": "phone", "contact_value": "+91-90000-00000"}})
    C.post(f"/api/listings/{lid}/photos", json={"token": tok, "filename": "label.png", "content_b64": b64(png()), "kind": "label"})
    return lid, tok, v


def test_flow():
    lid, tok, v = new_listing()
    ext = v["extracted"]
    assert ext["soh_pct"]["value"] == 86 and ext["report_id"]["value"] == "DBT-TEST-1" and ext["serial"]["value"] == "SN-TEST-0100"
    assert v["report"]["soh_pct"] == 86                      # pre-filled from the document, editable by the seller
    pre = C.post(f"/api/listings/{lid}/preview", json={"token": tok}).json()
    assert pre["would_be"]["verification"] == "awaiting_provider", pre["would_be"]
    sub = C.post(f"/api/listings/{lid}/submit", json={"token": tok}).json()
    assert sub["verification"] == "awaiting_provider" and sub["status"] == "listed"
    # public view: listed, NOT verified, no private contact
    pub = C.get(f"/api/listings/{lid}").json()
    assert pub["verification"] != "verified" and "contact_value" not in pub["sale"]
    uses = {u["id"] for u in pub["uses"]}
    assert "backup" in uses and "solar" not in uses           # 86% meets the 84% backup floor, not the 88% solar floor
    assert C.get(f"/api/listings/{lid}/report-file").status_code == 200
    assert C.get(f"/api/listings/{lid}/photos/0").headers["content-type"] == "image/png"
    # another seller cannot edit it
    assert C.patch(f"/api/listings/{lid}", json={"token": "wrong", "sale": {"price_inr": 1}}).status_code == 403
    # partner confirmation: wrong SoH -> mismatch; right -> verified
    bad = C.post(f"/api/listings/{lid}/partner-confirm", json={"partner_code": "DEMO-PUNE-2026", "report_id": "DBT-TEST-1", "measured_soh_pct": 80}).json()
    assert bad["verification"] == "mismatch"
    ok = C.post(f"/api/listings/{lid}/partner-confirm", json={"partner_code": "DEMO-PUNE-2026", "report_id": "DBT-TEST-1", "measured_soh_pct": 86}).json()
    assert ok["verification"] == "verified", ok
    assert C.post(f"/api/listings/{lid}/partner-confirm", json={"partner_code": "nope", "report_id": "x", "measured_soh_pct": 1}).status_code == 403
    # buyer interest -> seller accepts -> contacts shared
    it = C.post(f"/api/listings/{lid}/interest", json={"name": "Test Buyer", "contact": "buyer@example.test", "message": "Is it available?"}).json()
    mine = C.post("/api/listings/mine", json={"tokens": [tok]}).json()[0]
    assert mine["interests"][0]["status"] == "pending" and "contact" not in mine["interests"][0]
    C.post(f"/api/listings/{lid}/interests/{it['id']}/accept", json={"token": tok})
    mine = C.post("/api/listings/mine", json={"tokens": [tok]}).json()[0]
    assert mine["status"] == "in_contact" and mine["interests"][0]["contact"] == "buyer@example.test"
    bi = C.post("/api/listings/interests/mine", json={"tokens": [it["token"]]}).json()[0]
    assert bi["status"] == "accepted" and bi["seller_contact"]["value"] == "+91-90000-00000"
    assert C.post(f"/api/listings/{lid}/status", json={"token": tok, "status": "sold"}).json()["status"] == "sold"


def test_checks():
    # ID mismatch: the listing says one serial, the document another
    lid, tok, _ = new_listing(serial="SN-TEST-0200", report_id="DBT-TEST-2")
    C.patch(f"/api/listings/{lid}", json={"token": tok, "details": {"serial": "SN-OTHER-9999"}})
    s = C.post(f"/api/listings/{lid}/submit", json={"token": tok}).json()
    codes = {c["code"] for c in s["checks"]}
    assert "id_mismatch" in codes and s["verification"] == "mismatch" and s["status"] == "draft"
    assert all(c["reason"] for c in s["checks"])             # every warning explains itself
    # conflicting SoH
    lid, tok, _ = new_listing(serial="SN-TEST-0300", report_id="DBT-TEST-3", soh_entered=95)
    assert C.post(f"/api/listings/{lid}/submit", json={"token": tok}).json()["verification"] == "mismatch"
    # duplicate report ID of an already submitted listing -> held
    lid1, tok1, _ = new_listing(serial="SN-TEST-0400", report_id="DBT-TEST-4")
    C.post(f"/api/listings/{lid1}/submit", json={"token": tok1})
    lid2, tok2, _ = new_listing(serial="SN-TEST-0401", report_id="DBT-TEST-4")
    s2 = C.post(f"/api/listings/{lid2}/submit", json={"token": tok2}).json()
    assert s2["verification"] == "held" and "duplicate_report_id" in {c["code"] for c in s2["checks"]}
    # outdated report -> additional testing required (still public, clearly labelled)
    old = (date.today() - timedelta(days=400)).isoformat()
    lid, tok, _ = new_listing(serial="SN-TEST-0500", report_id="DBT-TEST-5", test_date=old)
    assert C.post(f"/api/listings/{lid}/submit", json={"token": tok}).json()["verification"] == "more_testing"
    # unregistered provider -> report uploaded, not yet verified
    lid, tok, _ = new_listing(serial="SN-TEST-0600", report_id="DBT-TEST-6", provider="Some Garage")
    assert C.post(f"/api/listings/{lid}/submit", json={"token": tok}).json()["verification"] == "report_uploaded"
    # no report -> cannot submit
    r = C.post("/api/listings").json()
    C.patch(f"/api/listings/{r['id']}", json={"token": r["token"], "details": {"city": "Pune"},
                                              "sale": {"price_inr": 1000, "contact_method": "phone", "contact_value": "+91-1"}})
    assert C.post(f"/api/listings/{r['id']}/submit", json={"token": r["token"]}).status_code == 422
    # browse never shows held / mismatched listings
    shown = {l["id"] for l in C.get("/api/listings").json()["listings"]}
    assert lid2 not in shown


def test_quick_fill():
    # quick listing: the sample report alone fills the battery details and the report fields
    rep = C.get("/api/listings/sample/report.pdf")
    assert rep.status_code == 200 and rep.content.startswith(b"%PDF")
    assert C.get("/api/listings/sample/photo.png?kind=label").headers["content-type"] == "image/png"
    r = C.post("/api/listings").json()
    v = C.post(f"/api/listings/{r['id']}/report", json={"token": r["token"], "filename": "sample.pdf", "content_b64": b64(rep.content)}).json()
    d, rp = v["details"], v["report"]
    assert (d["manufacturer"], d["chemistry"], d["city"], d["form"], d["age_years"]) == ("Tata AutoComp", "LFP", "Pune", "pack", 4)
    assert d["rated_capacity_kwh"] == 30.2 and d["serial"].startswith("TAT-21-S")
    assert rp["soh_pct"] == 86.5 and rp["measured_capacity_kwh"] == 26.1 and rp["provider"] == "Demo Battery Test Lab (Pune)"
    # free text that merely mentions a word is not taken as a field
    assert "model" not in report_extract.extract_fields("This report covers the model year and the city transport fleet.")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok ", name)
